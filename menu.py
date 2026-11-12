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

    PAGE_RESUME, PAGE_SETTINGS, PAGE_QUIT = 0, 1, 2

    def __init__(self, parent=None, settings=None, on_resume=None, on_quit=None,
                 on_setting=None, stats_provider=None):
        super().__init__(parent)
        self.settings = settings or {}
        self.on_resume = on_resume or (lambda: None)
        self.on_quit = on_quit or (lambda: None)
        self.on_setting = on_setting or (lambda k, v: None)
        self.stats_provider = stats_provider or (lambda: {})
        self.page = self.PAGE_RESUME

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
                 ('退出游戏', '', self.PAGE_QUIT)]
        for i, (text, hint, page) in enumerate(items):
            b = CsButton(self.panel, px(252), px(52),
                         x=-w / 2 + px(24) + px(126),
                         y=h / 2 - px(120) - i * px(60),
                         text=text, hint=hint, size_px=20,
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
        self._setting_row(page, '灵敏度', 'sensitivity', px(76), step=5, lo=5, hi=200,
                          fmt=lambda v: f'{int(v)}')
        self._setting_row(page, '音量', 'volume', px(0), step=0.05, lo=0.0, hi=1.0,
                          fmt=lambda v: f'{v * 100:.0f}%')
        self._toggle_row(page, '全屏', 'fullscreen', -px(76))

        label(page, '改动会立即生效并写入 settings.json', 12, x=-px(230), y=-px(150),
              col=T.C_TEXT_MUTE)

    def _setting_row(self, page, title, key, y, *, step, lo, hi, fmt):
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
        for i, p in enumerate((self.PAGE_RESUME, self.PAGE_SETTINGS, self.PAGE_QUIT)):
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
