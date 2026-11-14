# -*- coding: utf-8 -*-
"""修复 ursina 窗口位置/尺寸被意外还原的问题。

根因
----
ursina 的全局 ``window`` 对象继承自 panda3d 的 ``WindowProperties``，
本质上是一个**属性累加器**：任何一次 ``window.size`` / ``window.position`` /
``window.borderless`` / ``window.fullscreen`` 赋值都会把"当时的值"永久标记为
待应用（setOrigin / setSize / setUndecorated 置位后不会自动清除）。

而 ursina 的 ``Mouse.locked`` / ``Mouse.visible`` 赋值（点击"继续"回到游戏、
Esc 暂停菜单、Tab 计分板、FirstPersonController 的 on_enable/on_disable 等都
会触发）内部会调用 ``base.win.request_properties(window)``，把累加器里
**全部**已标记的属性连同鼠标模式/光标可见性一起重新下发给系统窗口。

于是出现两个 bug：
1. 用户把窗口拖到新位置 → 下一次鼠标锁定切换 → 启动时的旧 origin 被重新
   下发 → 窗口跳回原位；
2. 用户把窗口放大 → 点击进入游戏 → 启动时的旧 size 被重新下发 → 窗口缩回
   原尺寸。

修复方式
--------
接管 ``Mouse.locked`` / ``Mouse.visible`` 的赋值入口：在 ursina 原有逻辑
下发属性之前，把系统窗口**当前实际**的 origin / size 写回累加器，使重新
下发的值与现状一致（等于无操作）。无论何时、由谁触发，用户的拖动位置与
缩放尺寸都不会被回滚。

同时把 ``Window.position`` 的读取改为实时查询系统窗口，避免
``window.fullscreen`` 切换（F11 / 设置页）记录 windowed_position 时读到
累加器里的陈旧 origin，保证全屏往返后窗口回到用户拖放的位置。

用法：在 ``Ursina()`` 创建之后调用一次 ``winfix.install()``（幂等）。
测试见 ``tests_window.py``（含未安装补丁时 bug 的复现对照组）。

输入法屏蔽（IME block）
-----------------------
射击游戏里中文输入法是致命干扰：按 R（换弹）/ T / B 等键会被输入法
截获成拼音候选。Windows 下用 imm32 的 ``ImmAssociateContext(hwnd, NULL)``
把输入法上下文从游戏窗口**彻底摘除**——比"聚焦时切英文模式"更彻底：
不管当前选的是什么输入法，游戏窗口内的按键 100% 直达游戏。

方案说明与局限：
  - 摘除是按窗口句柄（HWND）生效的：只影响游戏窗口，其他程序（聊天、
    浏览器）的输入法完全不受影响；游戏进程退出时自动恢复原上下文。
  - 全屏切换可能导致 panda3d 重建底层窗口（HWND 变化），所以在每次
    鼠标锁定状态切换（进入/退出游戏、暂停、计分板）时都会重新确认，
    失效就立刻重新摘除。
  - 代价：游戏窗口内无法输入中文。本游戏没有任何文本输入框，
    因此无实际影响；若未来加聊天框，需在聊天框获得焦点时临时
    恢复上下文（ImmAssociateContext(hwnd, old_himc)）。
"""

import os


# ============================ 输入法屏蔽（Windows） ============================

_ime_old_himc = None          # 摘除前的原输入法上下文（退出时恢复）
_ime_blocked_hwnd = None      # 已摘除输入法的窗口句柄


def _find_game_hwnd():
    """枚举本进程可见的顶层窗口，返回游戏渲染窗口的 HWND（找不到返回 0）。

    游戏进程里只有一个带标题的可见窗口（渲染窗口）；启动器是独立进程，
    不会混进来。若标题里有游戏标题则优先精确匹配。
    """
    if os.name != 'nt':
        return 0
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    pid = os.getpid()
    found = []

    try:
        game_title = None
        try:
            from ursina import window as _w
            game_title = str(_w.title or '')
        except Exception:
            pass

        def _cb(hwnd, lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            # 精确匹配游戏标题的放最前，其余可见窗口作候选
            if game_title and buf.value == game_title:
                found.insert(0, hwnd)
            else:
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        return 0
    return found[0] if found else 0


def install_ime_block():
    """把输入法从游戏窗口摘除（Windows only，非 Windows / 失败时安全跳过）。

    返回 True 表示已生效；False 表示环境不适用（非 Windows / 找不到窗口）。
    每次鼠标锁定状态切换会自动重新确认（见 install() 内的挂钩）。
    """
    global _ime_old_himc, _ime_blocked_hwnd
    if os.name != 'nt':
        return False
    try:
        import atexit
        import ctypes
        user32 = ctypes.windll.user32
        imm32 = ctypes.windll.imm32
    except Exception:
        return False

    hwnd = _find_game_hwnd()
    if not hwnd:
        return False

    if _ime_blocked_hwnd == hwnd:
        return True                      # 已经摘除过同一个窗口
    # 摘除前如果还有旧上下文挂在前一个窗口上，先把那个窗口恢复
    _restore_ime()
    try:
        _ime_old_himc = imm32.ImmAssociateContext(hwnd, None)
    except Exception:
        _ime_old_himc = None
        return False
    _ime_blocked_hwnd = hwnd
    atexit.register(_restore_ime)
    return True


def _restore_ime():
    """进程退出 / 窗口重建时恢复原输入法上下文（尽力而为，失败忽略）。"""
    global _ime_old_himc, _ime_blocked_hwnd
    if os.name != 'nt' or not _ime_blocked_hwnd or not _ime_old_himc:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        imm32 = ctypes.windll.imm32
        if user32.IsWindow(_ime_blocked_hwnd):
            imm32.ImmAssociateContext(_ime_blocked_hwnd, _ime_old_himc)
    except Exception:
        pass
    _ime_old_himc = None
    _ime_blocked_hwnd = None


def _ime_blocked():
    """当前窗口的输入法是否已被摘除（供测试用）。"""
    if os.name != 'nt':
        return False
    try:
        import ctypes
        imm32 = ctypes.windll.imm32
        hwnd = _find_game_hwnd()
        if not hwnd:
            return False
        # ImmGetContext 返回 NULL 说明窗口没有输入法上下文 = 已摘除
        return not imm32.ImmGetContext(hwnd)
    except Exception:
        return False


def install():
    """在 Ursina() 创建之后调用一次；重复调用安全（幂等）。

    返回 True 表示补丁已生效（或此前已生效），
    返回 False 表示环境不适用（如 window_type == 'none' 的无头模式）。
    """
    try:
        from ursina import window, mouse, application
        from ursina import Vec2
    except Exception:
        return False
    if application.window_type == 'none':
        return False

    mouse_cls = type(mouse)
    if getattr(mouse_cls, '_winfix_installed', False):
        return True

    def _sync_live_state():
        # 把系统窗口当前真实的 origin/size 写回 window 累加器，
        # 这样紧随其后的 request_properties 重新下发的就是"当前值"，等于无操作。
        try:
            props = base.win.getProperties()
            if props.hasOrigin():
                window.setOrigin(props.getXOrigin(), props.getYOrigin())
            if props.hasSize():
                window.setSize(props.getXSize(), props.getYSize())
        except Exception:
            pass  # 窗口句柄不可用等情况不阻断原有逻辑

    # ---- Mouse.locked / Mouse.visible：下发前同步真实窗口状态 ----
    locked_prop = mouse_cls.locked
    visible_prop = mouse_cls.visible

    def _locked_set(self, value):
        _sync_live_state()
        # 窗口重建（如全屏切换）会让摘除失效，锁定切换时顺带重新确认
        if os.name == 'nt' and _ime_old_himc is None:
            install_ime_block()
        locked_prop.fset(self, value)

    def _visible_set(self, value):
        _sync_live_state()
        if os.name == 'nt' and _ime_old_himc is None:
            install_ime_block()
        visible_prop.fset(self, value)

    mouse_cls.locked = property(locked_prop.fget, _locked_set)
    mouse_cls.visible = property(visible_prop.fget, _visible_set)

    # ---- Window.position：改为实时读取系统窗口原点 ----
    # 原实现读累加器（getOrigin），补丁同步之间会读到陈旧值；
    # fullscreen 切换用它记录 windowed_position，读旧值会导致退出全屏后
    # 窗口不回到用户拖放的位置。setter 保持原样（写入即应用）。
    win_cls = type(window)
    pos_prop = win_cls.position

    def _position_get(self):
        if application.window_type == 'none':
            return Vec2(0, 0)
        try:
            props = base.win.getProperties()
            if props.hasOrigin():
                return Vec2(props.getXOrigin(), props.getYOrigin())
        except Exception:
            pass
        return pos_prop.fget(self)      # 退路：沿用 ursina 原始读取

    win_cls.position = property(_position_get, pos_prop.fset)

    mouse_cls._winfix_installed = True

    # ---- 输入法屏蔽：装补丁时立即生效 ----
    if os.name == 'nt':
        install_ime_block()

    return True
