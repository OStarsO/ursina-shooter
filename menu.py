"""CS:GO 风格的暂停菜单与计分板。

暂停菜单：左侧竖排导航 + 右侧内容区（继续 / 设置 / 退出）。
设置项的改动通过回调交给游戏本体应用并写回 settings.json。

计分板：按住 TAB 显示，T / CT 两栏，本机玩家行高亮。
"""
from __future__ import annotations

from ursina import Entity, Text, camera, color, destroy, window

import ui_theme as T
from ui_theme import BT, CsButton, KeyCap, Panel, label, px, rgba, ui_half_w


class _Overlay:
    """带全屏遮罩的浮层基类。"""

    def __init__(self, parent=None):
        self.root = Entity(parent=parent or camera.ui, enabled=False, name='overlay',
                           position=(0, 0, -0.5))
        self.dim = Entity(parent=self.root, model='quad', scale=(4, 3), z=0.02,
                          color=rgba((3, 5, 8), 198))

    def show(self):
        self.root.enabled = True
        self.dim.scale = (window.aspect_ratio + 0.6, 1.6)

    def hide(self):
        self.root.enabled = False

    @property
    def visible(self):
        return self.root.enabled


class PauseMenu(_Overlay):
    """左侧导航 + 右侧内容的暂停面板。"""

    PAGE_RESUME, PAGE_SETTINGS, PAGE_QUIT, PAGE_KEYS = 0, 1, 2, 3

    def __init__(self, parent=None, settings=None, on_resume=None, on_quit=None,
                 on_setting=None, stats_provider=None, on_keybind=None):
        super().__init__(parent)
        self.settings = settings or {}
        self.on_resume = on_resume or (lambda: None)
        self.on_quit = on_quit or (lambda: None)
        self.on_setting = on_setting or (lambda k, v: None)
        self.stats_provider = stats_provider or (lambda: {})
        self.on_keybind = on_keybind or (lambda a, k: None)
        self.page = self.PAGE_RESUME
        self.binding_action = None        # 正在等待按键的动作
        self.key_rows = {}

        self.panel = Panel(self.root, px(880), px(486), alpha=244, brackets=True,
                           accent_top=True, border_col=T.C_LINE)
        w, h = px(880), px(486)

        # 顶部标题
        label(self.panel, '游戏已暂停', 24, x=-w / 2 + px(24), y=h / 2 - px(34),
              col=T.C_TEXT)
        label(self.panel, 'PAUSED',
              11, x=-w / 2 + px(26), y=h / 2 - px(58), col=T.C_ACCENT)
        Entity(parent=self.panel, model='quad', scale=(w - px(48), BT),
               position=(0, h / 2 - px(76), -0.004), color=rgba(T.C_LINE, 180))

        # 左侧导航
        self.nav = []
        items = [('继续游戏', 'ESC', self.PAGE_RESUME),
                 ('设置', '', self.PAGE_SETTINGS),
                 ('键位', '', self.PAGE_KEYS),
                 ('退出游戏', '', self.PAGE_QUIT)]
        for i, (text, hint, page) in enumerate(items):
            b = CsButton(self.panel, px(252), px(46),
                         x=-w / 2 + px(24) + px(126),
                         y=h / 2 - px(118) - i * px(52),
                         text=text, hint=hint, size_px=19,
                         on_click=lambda p=page: self.set_page(p))
            self.nav.append(b)

        Entity(parent=self.panel, model='quad', scale=(BT, h - px(96)),
               position=(-w / 2 + px(300), -px(6), -0.004), color=rgba(T.C_LINE, 150))

        # 底部提示
        KeyCap(self.panel, 'ESC', x=-w / 2 + px(34), y=-h / 2 + px(28), h_px=20, size_px=12)
        label(self.panel, '返回游戏', 13, x=-w / 2 + px(66), y=-h / 2 + px(28), col=T.C_TEXT_MUTE)
        label(self.panel, 'UI v1.2  ·  CS:GO 风格', 11, x=w / 2 - px(24), y=-h / 2 + px(28),
              origin=(0.5, 0), col=T.C_TEXT_MUTE)

        cx = px(104)  # 内容区中心相对面板中心的偏移
        self.content_x = cx
        self.pages = {}
        self._build_resume(cx, w, h)
        self._build_settings(cx, w, h)
        self._build_keybinds(cx, w, h)
        self._build_quit(cx, w, h)
        self.set_page(self.PAGE_RESUME)
        self.relayout()

    # ---------------------------------------------------------- 页面
    def _build_resume(self, cx, w, h):
        page = Entity(parent=self.panel, x=cx)
        self.pages[self.PAGE_RESUME] = page
        label(page, '本局数据', 13, x=-px(230), y=px(150), col=T.C_TEXT_MUTE)
        rows = [('得分', 'score'), ('击杀', 'kills'), ('死亡', 'deaths'), ('存活时间', 'time')]
        for i, (name, key) in enumerate(rows):
            y = px(120) - i * px(44)
            Entity(parent=page, model='quad', scale=(px(460), px(38)),
                   position=(0, y, -0.002), color=rgba(T.C_PANEL_2, 150))
            label(page, name, 15, x=-px(214), y=y, col=T.C_TEXT_DIM)
            t = label(page, '0', 20, x=px(214), y=y, origin=(0.5, 0), col=T.C_TEXT, style='num')
            self.pages.setdefault('stat_texts', {})[key] = t
        label(page, '本局为训练场：5 秒未受伤会自动回血', 12, x=-px(230), y=-px(96),
              col=T.C_TEXT_MUTE)

    def _build_settings(self, cx, w, h):
        page = Entity(parent=self.panel, x=cx, enabled=False)
        self.pages[self.PAGE_SETTINGS] = page
        label(page, '设置', 20, x=-px(230), y=px(150), col=T.C_TEXT)
        label(page, 'SETTINGS', 11, x=-px(230), y=px(128), col=T.C_ACCENT)

        self.rows = {}
        self._setting_row(page, '灵敏度', 'sensitivity', px(100), step=5, lo=5, hi=200,
                          fmt=lambda v: f'{int(v)}')
        self._setting_row(page, '主音量', 'volume', px(62), step=0.05, lo=0.0, hi=1.0,
                          fmt=lambda v: f'{v * 100:.0f}%')
        self._setting_row(page, '音效音量', 'volume_sfx', px(24), step=0.05, lo=0.0, hi=1.0,
                          fmt=lambda v: f'{v * 100:.0f}%')
        self._setting_row(page, '界面音量', 'volume_ui', -px(14), step=0.05, lo=0.0, hi=1.0,
                          fmt=lambda v: f'{v * 100:.0f}%')
        self._cycle_row(page, '准星样式', 'crosshair', -px(52),
                        [('cross', '十字'), ('dot', '圆点'), ('t', 'T 形'), ('thick', '粗十字')])
        self._cycle_row(page, '画质档位', 'quality', -px(90),
                        [('low', '低'), ('medium', '中'), ('high', '高')])
        self._cycle_row(page, '分辨率', 'resolution', -px(128), None)
        self._toggle_row(page, '全屏', 'fullscreen', -px(166))
        self._toggle_row(page, '击杀者镜头', 'killcam', -px(200))

    def _setting_row(self, page, title, key, y, *, step, lo, hi, fmt):
        Entity(parent=page, model='quad', scale=(px(460), px(1)),
               position=(0, y - px(21), -0.002), color=rgba(T.C_LINE_SOFT, 200))
        label(page, title, 15, x=-px(230), y=y, col=T.C_TEXT_DIM)
        val = label(page, '', 18, x=px(70), y=y, origin=(0.5, 0), col=T.C_TEXT, style='num')

        def bump(delta):
            cur = float(self.settings.get(key, 0))
            nv = min(hi, max(lo, cur + delta * step))
            nv = round(nv, 3)
            self.settings[key] = nv
            val.text = fmt(nv)
            self.on_setting(key, nv)

        CsButton(page, px(34), px(34), x=px(120), y=y, text='−', size_px=18,
                 align='center', on_click=lambda: bump(-1))
        CsButton(page, px(34), px(34), x=px(160), y=y, text='+', size_px=18,
                 align='center', on_click=lambda: bump(1))

        val.text = fmt(float(self.settings.get(key, 0)))
        self.rows[key] = val

    def _cycle_row(self, page, title, key, y, options):
        Entity(parent=page, model='quad', scale=(px(460), px(1)),
               position=(0, y - px(21), -0.002), color=rgba(T.C_LINE_SOFT, 200))
        label(page, title, 15, x=-px(230), y=y, col=T.C_TEXT_DIM)
        if options is None:      # 分辨率：预设 + 当前值
            cur = str(self.settings.get(key) or '1600x900')
            presets = ['1280x720', '1600x900', '1920x1080', '2560x1440', '3840x2160']
            if cur not in presets:
                presets.append(cur)
            options = [(v, v.replace('x', ' × ')) for v in presets]
        values = [v for v, _ in options]
        labels = {v: t for v, t in options}
        cur = self.settings.get(key, values[0])
        if cur not in values:
            cur = values[0]
        val = label(page, labels[cur], 16, x=px(70), y=y, origin=(0.5, 0),
                    col=T.C_TEXT, font=T.FONT_CJK)

        def step(delta):
            nonlocal cur
            i = (values.index(cur) + delta) % len(values)
            cur = values[i]
            self.settings[key] = cur
            val.text = labels[cur]
            self.on_setting(key, cur)

        CsButton(page, px(34), px(34), x=px(120), y=y, text='‹', size_px=18,
                 align='center', on_click=lambda: step(-1))
        CsButton(page, px(34), px(34), x=px(160), y=y, text='›', size_px=18,
                 align='center', on_click=lambda: step(1))
        self.rows[key] = val

    def _build_keybinds(self, cx, w, h):
        page = Entity(parent=self.panel, x=cx, enabled=False)
        self.pages[self.PAGE_KEYS] = page
        label(page, '键位设置', 20, x=-px(230), y=px(150), col=T.C_TEXT)
        label(page, 'KEYBINDS', 11, x=-px(230), y=px(128), col=T.C_ACCENT)
        label(page, '点击「改键」后按任意键完成绑定；移动为 WASD 固定', 11,
              x=-px(230), y=px(104), col=T.C_TEXT_MUTE)

        keymap = self.settings.setdefault('keymap', {})
        actions = [('reload', '换弹'), ('shop', '武器商店'), ('inspect', '检视武器'),
                   ('third', '第三人称'), ('scoreboard', '计分板'), ('pause', '暂停菜单')]
        for i, (action, title) in enumerate(actions):
            y = px(74) - i * px(44)
            Entity(parent=page, model='quad', scale=(px(460), px(1)),
                   position=(0, y - px(22), -0.002), color=rgba(T.C_LINE_SOFT, 200))
            label(page, title, 15, x=-px(230), y=y, col=T.C_TEXT_DIM)
            _cur = keymap.get(action) or DEFAULT_KEYS.get(action, '?')
            cap = label(page, f'[ {_cur} ]', 14, x=-px(40), y=y,
                        origin=(0.5, 0), col=T.C_ACCENT, style='num')
            self.key_rows[action] = cap
            CsButton(page, px(78), px(32), x=px(120), y=y, text='改键', size_px=14,
                     align='center', on_click=lambda a=action: self.begin_bind(a))
            CsButton(page, px(78), px(32), x=px(202), y=y, text='恢复', size_px=14,
                     align='center', dim=True,
                     on_click=lambda a=action: self.reset_bind(a))
        label(page, '提示：F1/F2 调试血量；绑定会写入 settings.json', 11,
              x=-px(230), y=-px(206), col=T.C_TEXT_MUTE)

    # ---------------------------------------------------------- 键位
    def begin_bind(self, action):
        self.binding_action = action
        cap = self.key_rows.get(action)
        if cap:
            cap.text = '[ 按任意键… ]'

    def capture_key(self, key):
        """游戏输入层调用：若正在等键，则完成绑定并返回 True。"""
        if not self.binding_action:
            return False
        action = self.binding_action
        self.binding_action = None
        if key in ('escape',):
            _cur = self.settings.get('keymap', {}).get(action) or DEFAULT_KEYS.get(action, '?')
            self.key_rows[action].text = f'[ {_cur} ]'
            return True
        self.settings.setdefault('keymap', {})[action] = key
        self.key_rows[action].text = f'[ {key} ]'
        self.on_keybind(action, key)
        return True

    def reset_bind(self, action):
        keymap = self.settings.setdefault('keymap', {})
        keymap.pop(action, None)
        self.key_rows[action].text = f'[ {DEFAULT_KEYS.get(action, "?")} ]'
        self.on_keybind(action, '')

    def _build_quit(self, cx, w, h):
        Entity(parent=page, model='quad', scale=(px(460), px(1)),
               position=(0, y - px(30), -0.002), color=rgba(T.C_LINE_SOFT, 200))
        label(page, title, 16, x=-px(230), y=y, col=T.C_TEXT_DIM)
        val = label(page, '', 22, x=px(96), y=y, origin=(0.5, 0), col=T.C_TEXT, style='num')

        def bump(delta):
            cur = float(self.settings.get(key, 0))
            nv = min(hi, max(lo, cur + delta * step))
            nv = round(nv, 3)
            self.settings[key] = nv
            val.text = fmt(nv)
            self.on_setting(key, nv)

        CsButton(page, px(40), px(40), x=px(146), y=y, text='−', size_px=20,
                 align='center', on_click=lambda: bump(-1))
        CsButton(page, px(40), px(40), x=px(190), y=y, text='+', size_px=20,
                 align='center', on_click=lambda: bump(1))

        cur = float(self.settings.get(key, 0))
        val.text = fmt(cur)
        self.rows[key] = val

    def _toggle_row(self, page, title, key, y):
        Entity(parent=page, model='quad', scale=(px(460), px(1)),
               position=(0, y - px(30), -0.002), color=rgba(T.C_LINE_SOFT, 200))
        label(page, title, 16, x=-px(230), y=y, col=T.C_TEXT_DIM)
        # 这里会显示"开/关"，必须用中文字体，否则字形缺失会变成空白
        val = label(page, '', 20, x=px(96), y=y, origin=(0.5, 0), col=T.C_TEXT,
                    font=T.FONT_CJK)

        def toggle():
            nv = not bool(self.settings.get(key, False))
            self.settings[key] = nv
            val.text = '开' if nv else '关'
            self.on_setting(key, nv)

        b = CsButton(page, px(84), px(40), x=px(168), y=y, text='切换', size_px=17,
                     align='center', on_click=toggle)
        val.text = '开' if self.settings.get(key) else '关'
        self.rows[key] = val

    def _build_quit(self, cx, w, h):
        page = Entity(parent=self.panel, x=cx, enabled=False)
        self.pages[self.PAGE_QUIT] = page
        label(page, '退出游戏', 20, x=-px(230), y=px(150), col=T.C_TEXT)
        label(page, 'QUIT', 11, x=-px(230), y=px(128), col=T.C_ACCENT)
        label(page, '确定要退出到桌面吗？未保存的进度会丢失。', 14, x=-px(230), y=px(72),
              col=T.C_TEXT_DIM)
        CsButton(page, px(220), px(52), x=-px(118), y=px(0), text='退出到桌面',
                 size_px=19, accent=T.C_DANGER, on_click=self.on_quit)
        CsButton(page, px(220), px(52), x=px(118), y=px(0), text='取消', size_px=19,
                 dim=True, on_click=lambda: self.set_page(self.PAGE_RESUME))

    # ---------------------------------------------------------- 逻辑
    def set_page(self, page):
        self.page = page
        for i, p in enumerate((self.PAGE_RESUME, self.PAGE_SETTINGS,
                               self.PAGE_KEYS, self.PAGE_QUIT)):
            self.pages[p].enabled = (p == page)
            self.nav[i].set_active(p == page)
        if page == self.PAGE_RESUME:
            self.refresh_stats()

    def refresh_stats(self):
        texts = self.pages.get('stat_texts', {})
        data = self.stats_provider() or {}
        for key, t in texts.items():
            t.text = str(data.get(key, '0'))

    def show(self, page=None):
        super().show()
        if page is not None:
            self.set_page(page)
        else:
            self.set_page(self.page)

    def relayout(self):
        self.panel.x = 0
        self.panel.y = 0
        self.dim.scale = (window.aspect_ratio + 0.6, 1.6)
        self.refresh_stats()


class Scoreboard(_Overlay):
    """T / CT 两栏计分板。"""

    COLS = (('玩家', 0), ('击杀', 0), ('死亡', 0), ('助攻', 0), ('延迟', 0))

    def __init__(self, parent=None, provider=None):
        super().__init__(parent)
        self.provider = provider or (lambda: {'rows': [], 'left': '', 'right': ''})
        self.panel = Panel(self.root, px(900), px(468), alpha=244, brackets=True,
                           accent_top=True)
        w, h = px(900), px(468)

        self.title = label(self.panel, '训练场', 22, x=-w / 2 + px(26), y=h / 2 - px(36),
                           col=T.C_TEXT)
        self.sub = label(self.panel, 'TRAINING', 11, x=-w / 2 + px(28), y=h / 2 - px(58),
                         col=T.C_ACCENT)
        self.score = label(self.panel, '', 22, x=w / 2 - px(26), y=h / 2 - px(36),
                           origin=(0.5, 0), col=T.C_TEXT, style='num')
        Entity(parent=self.panel, model='quad', scale=(w - px(52), BT),
               position=(0, h / 2 - px(76), -0.004), color=rgba(T.C_LINE, 180))

        # 表头
        self.head = Entity(parent=self.panel)
        cols = [('玩家', -w / 2 + px(26), (-0.5, 0)), ('击杀', w / 2 - px(210), (0.5, 0)),
                ('死亡', w / 2 - px(150), (0.5, 0)), ('助攻', w / 2 - px(92), (0.5, 0)),
                ('延迟', w / 2 - px(30), (0.5, 0))]
        for name, x, origin in cols:
            label(self.head, name, 12, x=x, y=h / 2 - px(92), origin=origin, col=T.C_TEXT_MUTE)
        Entity(parent=self.panel, model='quad', scale=(w - px(52), BT),
               position=(0, h / 2 - px(104), -0.004), color=rgba(T.C_LINE_SOFT, 200))

        self.body = Entity(parent=self.panel)
        self.rows_root = Entity(parent=self.body)
        self.empty = label(self.panel, '等待玩家加入…', 14, x=0, y=-px(40), origin=(0, 0),
                           col=T.C_TEXT_MUTE)
        self.foot = label(self.panel, '联机对战同步将在下一版本接入', 11, x=0,
                          y=-h / 2 + px(30), origin=(0, 0), col=T.C_TEXT_MUTE)

        KeyCap(self.panel, 'TAB', x=-w / 2 + px(34), y=-h / 2 + px(28), h_px=18, size_px=11)
        label(self.panel, '按住查看', 12, x=-w / 2 + px(62), y=-h / 2 + px(28), col=T.C_TEXT_MUTE)

    def refresh(self):
        data = self.provider() or {}
        self.title.text = data.get('title', '训练场')
        self.sub.text = T.spaced(data.get('sub', 'TRAINING'))
        self.score.text = data.get('score', '')
        rows = data.get('rows', [])

        for child in list(self.rows_root.children):
            destroy(child)
        self.empty.enabled = not rows

        w = px(900)
        slots = 7
        # 空槽位：既撑满面板，也提示房间还能坐几个人
        for i in range(len(rows), slots):
            y = px(112) - i * px(44)
            Entity(parent=self.rows_root, model='quad', scale=(w - px(52), px(40)),
                   position=(0, y, -0.002), color=rgba(T.C_PANEL_2, 55))
            label(self.rows_root, '—', 15, x=-w / 2 + px(26) + px(26), y=y,
                  col=T.C_TEXT_MUTE, alpha=120)
            for x in (w / 2 - px(210), w / 2 - px(150), w / 2 - px(92), w / 2 - px(30)):
                label(self.rows_root, '·', 16, x=x, y=y, origin=(0.5, 0), col=T.C_TEXT_MUTE,
                      alpha=90)

        for i, row in enumerate(rows):
            y = px(112) - i * px(44)
            bg = Entity(parent=self.rows_root, model='quad', scale=(w - px(52), px(40)),
                        position=(0, y, -0.002),
                        color=rgba(T.C_PANEL_HI if row.get('self') else T.C_PANEL_2,
                                   190 if row.get('self') else 110))
            if row.get('self'):
                Entity(parent=self.rows_root, model='quad', scale=(px(3), px(40)),
                       position=(-w / 2 + px(26) + px(1.5), y, -0.004),
                       color=rgba(T.C_ACCENT, 240))
            team_col = T.C_TEAM_T if row.get('team') == 'T' else T.C_TEAM_CT
            Entity(parent=self.rows_root, model='quad', scale=(px(2), px(28)),
                   position=(-w / 2 + px(26) + px(8), y, -0.003), color=rgba(team_col, 220))
            label(self.rows_root, row.get('team', 'T'), 13, x=-w / 2 + px(26) + px(20), y=y,
                  col=team_col, alpha=225)
            label(self.rows_root, row.get('name', ''), 16, x=-w / 2 + px(26) + px(40), y=y,
                  col=T.C_TEXT if row.get('self') else T.C_TEXT_DIM)
            # 右侧数字列（右对齐更好读）
            for key, x in (('kills', w / 2 - px(210)), ('deaths', w / 2 - px(150)),
                           ('assists', w / 2 - px(92)), ('ping', w / 2 - px(30))):
                label(self.rows_root, str(row.get(key, 0)), 18, x=x, y=y, origin=(0.5, 0),
                      col=T.C_TEXT if row.get('self') else T.C_TEXT_DIM, style='num')

    def show(self):
        super().show()
        self.refresh()

    def relayout(self):
        self.dim.scale = (window.aspect_ratio + 0.6, 1.6)


# ============================ 死亡面板 ============================

ZONE_CN = {'head': '头部', 'body': '躯干', 'limb': '肢体'}
DEFAULT_KEYS = {'reload': 'r', 'shop': 'b', 'inspect': 'f', 'third': 'v',
                'scoreboard': 'tab', 'pause': 'escape'}


class DeathPanel(_Overlay):
    """阵亡面板：击杀者 / 武器 / 命中部位 / 伤害 + 重生倒计时。

    ``show(...)`` 时按死因区分文案；``killcam`` 打开时由游戏本体把镜头
    切到击杀者身上（见 射击.py 的 _start_killcam）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panel = Panel(self.root, px(620), px(292), alpha=246, brackets=True,
                           accent_top=True, border_col=T.C_LINE)
        w, h = px(620), px(292)
        self.title = label(self.panel, '你已阵亡', 26, x=-w / 2 + px(26), y=h / 2 - px(38),
                           col=T.C_DANGER, font=T.FONT_CJK)
        label(self.panel, 'ELIMINATED', 11, x=-w / 2 + px(28), y=h / 2 - px(62),
              col=T.C_MUTED)
        Entity(parent=self.panel, model='quad', scale=(w - px(52), BT),
               position=(0, h / 2 - px(80), -0.004), color=rgba(T.C_LINE, 180))

        self.lbl_killer = label(self.panel, '', 20, x=-w / 2 + px(28), y=px(52),
                                col=T.C_TEXT, font=T.FONT_CJK)
        self.lbl_weapon = label(self.panel, '', 15, x=-w / 2 + px(28), y=px(18),
                                col=T.C_TEXT_DIM, font=T.FONT_CJK)
        self.lbl_zone = label(self.panel, '', 15, x=-w / 2 + px(28), y=-px(12),
                              col=T.C_TEXT_DIM, font=T.FONT_CJK)
        self.lbl_cause = label(self.panel, '', 13, x=-w / 2 + px(28), y=-px(42),
                               col=T.C_MUTED, font=T.FONT_CJK)
        self.lbl_cam = label(self.panel, '', 12, x=w / 2 - px(28), y=-px(42),
                             origin=(0.5, 0), col=T.C_MUTED, font=T.FONT_CJK)
        self.lbl_timer = label(self.panel, '', 30, x=w / 2 - px(30), y=h / 2 - px(120),
                               origin=(0.5, 0), col=T.C_ACCENT, style='num')
        label(self.panel, '重生倒计时', 11, x=w / 2 - px(30), y=h / 2 - px(146),
              origin=(0.5, 0), col=T.C_MUTED, font=T.FONT_CJK)

    def show_death(self, killer=None, weapon='', zone='', damage=0,
                   respawn=3.0, killcam=False, cause='击杀'):
        killer = str(killer or '未知')
        self.lbl_killer.text = f'击杀者  {killer}'
        self.lbl_weapon.text = f'武器    {weapon or "未知"}'
        zone_cn = ZONE_CN.get(zone, zone or '—')
        self.lbl_zone.text = f'命中部位  {zone_cn}   ·   伤害 {int(round(damage))}'
        self.lbl_cause.text = f'死因：{cause}'
        self.lbl_cam.text = '击杀者镜头：开' if killcam else '击杀者镜头：关（设置可开）'
        self.remaining = max(0.0, float(respawn))
        self.lbl_timer.text = f'{self.remaining:.1f}'
        self.show()

    def tick(self, dt):
        if not self.visible:
            return
        self.remaining = max(0.0, self.remaining - dt)
        self.lbl_timer.text = f'{self.remaining:.1f}'
        if self.remaining <= 0.0:
            self.hide()

    def relayout(self):
        self.dim.scale = (window.aspect_ratio + 0.6, 1.6)


# ============================ 结算页 ============================

class ResultsPage(_Overlay):
    """回合结算：红蓝比分 / 本局 KDA / MVP；单机与联机共用。"""

    def __init__(self, parent=None, on_leave=None):
        super().__init__(parent)
        self.on_leave = on_leave or (lambda: None)
        self.panel = Panel(self.root, px(940), px(520), alpha=248, brackets=True,
                           accent_top=True)
        w, h = px(940), px(520)
        self.w, self.h = w, h
        self.title = label(self.panel, '对 局 结 算', 26, x=-w / 2 + px(28), y=h / 2 - px(40),
                           col=T.C_TEXT, font=T.FONT_CJK)
        self.reason = label(self.panel, '', 11, x=-w / 2 + px(30), y=h / 2 - px(66),
                            col=T.C_MUTED, font=T.FONT_CJK)
        self.winner = label(self.panel, '', 34, x=0, y=h / 2 - px(112), origin=(0, 0),
                            col=T.C_ACCENT, font=T.FONT_CJK)
        self.score = label(self.panel, '', 42, x=w / 2 - px(40), y=h / 2 - px(108),
                           origin=(0.5, 0), col=T.C_TEXT, style='num')
        Entity(parent=self.panel, model='quad', scale=(w - px(56), BT),
               position=(0, h / 2 - px(130), -0.004), color=rgba(T.C_LINE, 180))

        # 表头
        cols = [('玩家', -w / 2 + px(28), (-0.5, 0)), ('队伍', -px(70), (-0.5, 0)),
                ('击杀', w / 2 - px(210), (0.5, 0)), ('死亡', w / 2 - px(150), (0.5, 0)),
                ('得分', w / 2 - px(80), (0.5, 0))]
        for name, x, origin in cols:
            label(self.panel, name, 12, x=x, y=h / 2 - px(150), origin=origin, col=T.C_MUTED)

        self.rows_root = Entity(parent=self.panel)
        self.mvp = label(self.panel, '', 16, x=-w / 2 + px(28), y=-h / 2 + px(86),
                         col=T.C_ACCENT, font=T.FONT_CJK)
        self.btn_leave = CsButton(self.panel, px(220), px(48), x=px(0), y=-h / 2 + px(40),
                                  text='返回大厅', size_px=18, on_click=self._leave)
        self.hint = label(self.panel, '按 ESC 或点击返回大厅', 12, x=w / 2 - px(28),
                          y=-h / 2 + px(34), origin=(0.5, 0), col=T.C_MUTED, font=T.FONT_CJK)

    def show_result(self, result, on_leave=None):
        if on_leave is not None:
            self.on_leave = on_leave
        result = result or {}
        score = result.get('score') or {'red': 0, 'blue': 0}
        winner = result.get('winner') or ''
        team_cn = {'red': '红队', 'blue': '蓝队'}
        self.winner.text = (f'{team_cn.get(winner, "平局")} 胜利' if winner
                            else '平局')
        self.winner.color = rgba((196, 74, 58) if winner == 'red' else
                                 (86, 132, 220) if winner == 'blue' else T.C_TEXT, 250)
        self.score.text = f'{score.get("red", 0)} : {score.get("blue", 0)}'
        reason_cn = {'score': '达到目标比分', 'time': '时间到',
                     'admin': '房主结束'}.get(result.get('reason'), '对局结束')
        self.reason.text = f'MATCH RESULT · {reason_cn}'

        for child in list(self.rows_root.children):
            destroy(child)
        rows = result.get('rows') or []
        w, h = self.w, self.h
        for i, row in enumerate(rows[:7]):
            y = h / 2 - px(186) - i * px(38)
            is_mvp = (result.get('mvp') or {}).get('name') == row.get('name')
            bg = Entity(parent=self.rows_root, model='quad',
                        scale=(w - px(56), px(34)), position=(0, y, -0.002),
                        color=rgba(T.C_PANEL_HI if is_mvp else T.C_PANEL_2,
                                   170 if is_mvp else 90))
            team_col = (T.C_TEAM_RED if row.get('team') == 'red' else T.C_TEAM_BLUE)
            Entity(parent=self.rows_root, model='quad', scale=(px(2), px(24)),
                   position=(-w / 2 + px(28) + px(6), y, -0.003), color=rgba(team_col, 220))
            name = ('★ ' if is_mvp else '') + str(row.get('name', ''))
            label(self.rows_root, name, 15, x=-w / 2 + px(40), y=y,
                  col=T.C_TEXT if is_mvp else T.C_TEXT_DIM, font=T.FONT_CJK)
            label(self.rows_root, team_cn.get(row.get('team'), '—'), 12, x=-px(70), y=y,
                  origin=(-0.5, 0), col=team_col, font=T.FONT_CJK)
            for key, x in (('kills', w / 2 - px(210)), ('deaths', w / 2 - px(150)),
                           ('score', w / 2 - px(80))):
                label(self.rows_root, str(row.get(key, 0)), 17, x=x, y=y, origin=(0.5, 0),
                      col=T.C_TEXT if is_mvp else T.C_TEXT_DIM, style='num')
        mvp = result.get('mvp') or {}
        self.mvp.text = (f'MVP  {mvp.get("name", "—")}   ·   {mvp.get("score", 0)} 分'
                         if mvp else '')
        self.show()

    def _leave(self):
        self.hide()
        self.on_leave()

    def relayout(self):
        self.dim.scale = (window.aspect_ratio + 0.6, 1.6)
