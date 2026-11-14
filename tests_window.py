# -*- coding: utf-8 -*-
"""winfix.py 窗口状态保持测试（需要桌面窗口环境，用 `py -3.11 tests_window.py` 运行）。

流程：
  1. 建 Ursina 小窗口，模拟启动期的 window.position / window.size 赋值
     （把启动值写进 window(WindowProperties) 累加器，与 射击.py 启动序列一致）；
  2. 用"新鲜" WindowProperties 请求新的 origin/size，模拟用户拖动 + 缩放窗口
     （OS 侧改变，不经 ursina 属性赋值，因此累加器里仍是启动旧值）；
  3. 对照组：不装补丁，切换 mouse.locked —— 复现"窗口跳回旧位置、缩回旧尺寸"；
  4. 安装补丁后再拖动 + 缩放一次，反复切换 mouse.locked / mouse.visible，
     断言窗口的位置和尺寸始终保持在用户设置的状态。
"""
import sys

sys.path.insert(0, '.')

PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


from ursina import Ursina
app = Ursina(title='winfix-test', borderless=False, development_mode=False,
             size=(640, 480))
from ursina import window, mouse, application
from panda3d.core import WindowProperties
import winfix


def pump(n=30):
    """推进 n 帧，让 requestProperties 的异步应用落地。"""
    for _ in range(n):
        base.taskMgr.step()


def current():
    p = base.win.getProperties()
    return (p.getXOrigin(), p.getYOrigin(), p.getXSize(), p.getYSize())


# ---- 1. 启动期赋值（模拟 射击.py 的 window.position / window.size）----
window.position = (80, 80)
window.size = (640, 480)
pump(10)
check('启动期窗口位于初始状态', current()[:2] == (80, 80), f'{current()}')

# ---- 2. 模拟用户拖动 + 缩放（OS 侧改变，不经 ursina 属性赋值）----
USER_STATE = (260, 200, 900, 560)
req = WindowProperties()
req.setOrigin(USER_STATE[0], USER_STATE[1])
req.setSize(USER_STATE[2], USER_STATE[3])
base.win.requestProperties(req)
pump(30)
check('用户拖动/缩放已生效', current() == USER_STATE, f'{current()}')

# ---- 3. 对照组：未装补丁，锁定切换应把窗口弹回启动值（复现 bug）----
mouse.locked = True          # FPC 初始化/点击继续时正是这条路径
pump(30)
after = current()
check('未装补丁时窗口被弹回（bug 复现）', after == (80, 80, 640, 480), f'{after}')

# ---- 4. 安装补丁，重演"拖动缩放 → 点击进入游戏"----
base.win.requestProperties(req)   # 恢复用户设置的状态
pump(30)
check('恢复用户窗口状态', current() == USER_STATE, f'{current()}')

installed = winfix.install()
check('winfix.install() 返回 True', installed is True)
check('install 幂等（二次调用不报错）', winfix.install() is True)

# ---- 5. 再次模拟用户拖动 + 缩放到新状态 ----
USER_STATE2 = (300, 240, 1000, 600)
req2 = WindowProperties()
req2.setOrigin(USER_STATE2[0], USER_STATE2[1])
req2.setSize(USER_STATE2[2], USER_STATE2[3])
base.win.requestProperties(req2)
pump(30)
check('第二次拖动/缩放已生效', current() == USER_STATE2, f'{current()}')

# ---- 6. 反复切换锁定/光标（暂停→继续、计分板、FPC 启停都走这几条路）----
for value in (False, True, False, True):
    mouse.locked = value
    pump(10)
for value in (True, False, True, False):
    mouse.visible = value
    pump(10)
after2 = current()
check('锁定/光标切换后窗口位置保持', after2[:2] == USER_STATE2[:2], f'{after2}')
check('锁定/光标切换后窗口尺寸保持', after2[2:] == USER_STATE2[2:], f'{after2}')

# ---- 7. window.position 改为实时读取（fullscreen 往返记录 windowed_position 用）----
check('window.position 实时反映系统窗口',
      tuple(int(v) for v in window.position) == USER_STATE2[:2],
      f'{tuple(window.position)}')

# ---- 8. 输入法屏蔽：install() 时已摘除游戏窗口的 IME 上下文 ----
import os as _os
if _os.name == 'nt':
    check('游戏窗口 IME 已摘除', winfix._ime_blocked() is True)
    check('摘除前原上下文已保存', winfix._ime_old_himc not in (None, 0))
    # 锁定切换（上面第 6 步已跑过多次）不应导致 IME 补丁失效
    mouse.locked = False
    pump(10)
    mouse.locked = True
    pump(10)
    check('锁定切换后 IME 仍被摘除', winfix._ime_blocked() is True)

application.quit()
print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
