# -*- coding: utf-8 -*-
"""武器选择商店：开局自动弹出 + 局内按 B 随时打开。

规则
----
每名玩家仅可携带三件武器：匕首（近战，固定）+ 一把副武器 + 一把主武器。
商店列出每个槽位的可选项，价格全部为 0（不启用经济系统），
点击即装备并切换到手。配装约束由游戏主脚本的 LOADOUT 保证，
商店只是它的可视操作面板。

    shop = Shop(on_pick=lambda slot, key: ...)
    shop.toggle()          # B 键
"""
from __future__ import annotations

from ursina import Entity, Text, camera, color, window

import ui_theme as T
from ui_theme import BT, CsButton, KeyCap, Panel, label, px, rgba

from weapons.config import CATALOG, SLOTS

SLOT_CN = {'primary': '主武器', 'side': '副武器', 'melee': '近战'}


class Shop:
    """武器选择面板（全屏遮罩 + 双列武器卡片）。"""

    def __init__(self, parent=None, on_pick=None, loadout_getter=None):
        from menu import _Overlay
        self.on_pick = on_pick or (lambda slot, key: None)
        self.loadout_getter = loadout_getter or (lambda: {})
        self.root = _Overlay(parent)

        self.panel = Panel(self.root.root, px(700), px(430), alpha=246,
                           brackets=True, accent_top=True, border_col=T.C_LINE)
        w, h = px(700), px(430)

        label(self.panel, '武器商店', 24, x=-w / 2 + px(24), y=h / 2 - px(34),
              col=T.C_TEXT)
        label(self.panel, 'LOADOUT', 11, x=-w / 2 + px(26), y=h / 2 - px(58),
              col=T.C_ACCENT)
        label(self.panel, '所有武器免费 · 限带 匕首 + 副武器 + 主武器',
              12, x=w / 2 - px(24), y=h / 2 - px(34), origin=(0.5, 0),
              col=T.C_TEXT_MUTE)
        Entity(parent=self.panel, model='quad', scale=(w - px(48), BT),
               position=(0, h / 2 - px(76), -0.004), color=rgba(T.C_LINE, 180))

        # 两列卡片：主武器 / 副武器（近战固定持有，不入商店）
        self.cards = {}
        col_x = {-1: -w / 4 + px(6), 1: w / 4 - px(6)}
        for col, slot in ((-1, 'primary'), (1, 'side')):
            cx = col_x[col]
            label(self.panel, SLOT_CN[slot], 15, x=cx, y=h / 2 - px(104),
                  origin=(0.5, 0), col=T.C_TEXT_DIM)
            for i, key in enumerate(SLOTS[slot]):
                spec = CATALOG[key]
                card = self._make_card(cx, h / 2 - px(140) - i * px(118), spec, slot)
                self.cards[key] = card

        # 底部提示
        KeyCap(self.panel, 'B', x=-w / 2 + px(34), y=-h / 2 + px(28), h_px=20, size_px=12)
        label(self.panel, '关闭商店', 13, x=-w / 2 + px(66), y=-h / 2 + px(28),
              col=T.C_TEXT_MUTE)
        KeyCap(self.panel, '1', x=-w / 2 + px(190), y=-h / 2 + px(28), h_px=20, size_px=12)
        label(self.panel, '主武器', 13, x=-w / 2 + px(222), y=-h / 2 + px(28),
              col=T.C_TEXT_MUTE)
        KeyCap(self.panel, '2', x=-w / 2 + px(316), y=-h / 2 + px(28), h_px=20, size_px=12)
        label(self.panel, '副武器', 13, x=-w / 2 + px(348), y=-h / 2 + px(28),
              col=T.C_TEXT_MUTE)
        KeyCap(self.panel, '3', x=-w / 2 + px(442), y=-h / 2 + px(28), h_px=20, size_px=12)
        label(self.panel, '匕首', 13, x=-w / 2 + px(474), y=-h / 2 + px(28),
              col=T.C_TEXT_MUTE)
        label(self.panel, '价格全部为 0', 11, x=w / 2 - px(24), y=-h / 2 + px(28),
              origin=(0.5, 0), col=T.C_TEXT_MUTE)

        self.refresh()
        self.relayout()

    # ---------------------------------------------------------- 卡片
    def _make_card(self, cx, cy, spec, slot):
        card_w, card_h = px(292), px(100)
        card = Entity(parent=self.panel, position=(cx, cy, -0.01))
        Entity(parent=card, model='quad', scale=(card_w, card_h),
               color=rgba(T.C_PANEL_2, 170))
        Entity(parent=card, model='quad', scale=(card_w, BT),
               position=(0, card_h / 2 - BT / 2, -0.002), color=rgba(T.C_LINE, 160))
        label(card, spec['name'], 19, x=-card_w / 2 + px(16), y=card_h / 2 - px(26),
              col=T.C_TEXT)
        label(card, spec.get('cn', ''), 12, x=-card_w / 2 + px(16),
              y=card_h / 2 - px(48), col=T.C_TEXT_MUTE)
        label(card, '¥0 · 免费', 13, x=card_w / 2 - px(16), y=card_h / 2 - px(26),
              origin=(0.5, 0), col=T.C_OK)
        # 状态标签（已装备 / 点击装备）：卡片右侧垂直居中，z 提到按钮前面。
        # 必须显式指定中文字体并带初始文本：ursina 的 Text 用空串创建会按
        # 拉丁字体定字，之后再填中文会缺字形（渲染成空白）。
        st = label(card, ' ', 13, x=card_w / 2 - px(16),
                   y=px(0), origin=(0.5, 0), col=T.C_OK,
                   font=T.FONT_CJK, z=-0.03)
        btn = CsButton(card, card_w, px(34), x=0, y=-card_h / 2 + px(22),
                       text='装备', hint='', size_px=14,
                       on_click=lambda s=slot, k=spec['key']: self.on_pick(s, k))
        card.state_label = st
        card.btn = btn
        card.spec_key = spec['key']
        return card

    # ---------------------------------------------------------- 状态
    def refresh(self):
        """按当前配装点亮"已装备"。"""
        ld = self.loadout_getter()
        for key, card in self.cards.items():
            equipped = any(ld.get(s) == key for s in ('primary', 'side'))
            card.state_label.text = '√ 已装备' if equipped else ' '
            card.state_label.color = rgba(T.C_OK if equipped else T.C_ACCENT, 235)

    # ---------------------------------------------------------- 开关
    def toggle(self):
        if self.visible:
            self.close()
        else:
            self.open()

    def open(self):
        self.refresh()
        self.root.show()

    def close(self):
        self.root.hide()

    @property
    def visible(self):
        return self.root.visible

    def relayout(self):
        self.root.dim.scale = (window.aspect_ratio + 0.6, 1.6)
