# -*- coding: utf-8 -*-
"""木偶人训练靶：分部位伤害判定的木制人形靶。

结构（约 1.8 米高，木质配色）：
    头    球体（判断区：head，×4.0）
    胸    方块（判断区：body，×1.25）
    躯干  方块（判断区：body，×1.25）
    手臂  两根细柱（判断区：limb，×0.75）
    腿    两根细柱（判断区：limb，×0.75）
    底座  立柱 + 十字底座（不参与判定）

每个部位是独立 collider，玩家子弹命中的部位实体带 ``dummy_part`` 标记，
伤害走 combat.zone_damage()（木偶人与玩家同一套倍率）。

部分木偶人会左右巡航（训练移动靶）；被击倒后播放倒地并延时重生。
"""

from ursina import Entity, color, random

import combat
import ui_theme as T

WOOD = color.rgb32(168, 126, 84)          # 浅木色
WOOD_DARK = color.rgb32(126, 90, 58)      # 深木色（关节/底座）
HEAD_MARK = color.rgb32(214, 84, 66)      # 头部红圈提示色


class Dummy:
    """一只木偶人。``parts`` 里每个部位实体都带 dummy_part / dummy 引用。"""

    def __init__(self, position=(0, 0, 0), heading=0, moving=False,
                 hp=100, tint=None):
        self.root = Entity(position=position, rotation_y=heading)
        self.hp = hp
        self.max_hp = hp
        self.alive = True
        self.moving = moving
        self.respawn_left = 0.0
        self._phase = random.uniform(0.0, 6.28)
        self._origin_x = position[0]
        self._falling = 0.0

        parts = []
        # ---- 头 ----
        head = Entity(parent=self.root, model='sphere', collider='box',
                      position=(0, 1.64, 0), scale=(0.30, 0.32, 0.30),
                      color=WOOD)
        # ---- 胸 ----
        chest = Entity(parent=self.root, model='cube', collider='box',
                       position=(0, 1.29, 0), scale=(0.52, 0.34, 0.30),
                       color=WOOD)
        # ---- 躯干（腰腹） ----
        torso = Entity(parent=self.root, model='cube', collider='box',
                       position=(0, 0.87, 0), scale=(0.42, 0.42, 0.27),
                       color=WOOD)
        # ---- 手臂 ×2 ----
        arm_l = Entity(parent=self.root, model='cube', collider='box',
                       position=(-0.36, 1.16, 0), scale=(0.14, 0.56, 0.14),
                       color=WOOD_DARK)
        arm_r = Entity(parent=self.root, model='cube', collider='box',
                       position=(0.36, 1.16, 0), scale=(0.14, 0.56, 0.14),
                       color=WOOD_DARK)
        # ---- 腿 ×2 ----
        leg_l = Entity(parent=self.root, model='cube', collider='box',
                       position=(-0.15, 0.40, 0), scale=(0.17, 0.72, 0.17),
                       color=WOOD_DARK)
        leg_r = Entity(parent=self.root, model='cube', collider='box',
                       position=(0.15, 0.40, 0), scale=(0.17, 0.72, 0.17),
                       color=WOOD_DARK)
        # ---- 底座（不参与判定） ----
        Entity(parent=self.root, model='cube',
               position=(0, 0.03, 0), scale=(0.72, 0.07, 0.72),
               color=WOOD_DARK)
        Entity(parent=self.root, model='cube',
               position=(0, 0.015, 0), scale=(1.05, 0.04, 1.05),
               color=WOOD_DARK)

        zone_map = {'head': head, 'chest': chest, 'torso': torso,
                    'arm_l': arm_l, 'arm_r': arm_r,
                    'leg_l': leg_l, 'leg_r': leg_r}
        zone_of = {'head': 'head', 'chest': 'body', 'torso': 'body',
                   'arm_l': 'limb', 'arm_r': 'limb',
                   'leg_l': 'limb', 'leg_r': 'limb'}
        for key, ent in zone_map.items():
            ent.dummy_part = zone_of[key]
            ent.dummy = self
            parts.append(ent)
        self.parts = parts
        self.head = head

        if tint is not None:                 # 阵营染色（团队模式蓝队靶）
            _dark = tuple(max(0, int(c * 0.72)) for c in tint)
            for ent in parts:
                ent.color = color.rgb32(*(_dark if ent in (arm_l, arm_r,
                                                           leg_l, leg_r) else tint))

    # ---------------- 命中 ----------------
    def take_damage(self, base_damage, zone):
        """按部位结算伤害；返回 (是否击倒, 实际伤害)。"""
        if not self.alive:
            return False, 0
        dmg = combat.zone_damage(base_damage, zone)
        self.hp -= dmg
        if self.hp <= 0:
            self.knock_down()
            return True, dmg
        return False, dmg

    def knock_down(self):
        """倒地：整棵绕 X 轴向后翻倒，等待重生。"""
        self.alive = False
        self.respawn_left = 2.2
        self._falling = 1.0

    def respawn(self):
        self.alive = True
        self.hp = self.max_hp
        self.respawn_left = 0.0
        self._falling = 0.0
        self.root.rotation_x = 0

    # ---------------- 每帧 ----------------
    def update(self, dt):
        if not self.alive:
            # 翻倒动画（0.35 秒转 90°），随后等待重生
            if self._falling > 0.0:
                self._falling = max(0.0, self._falling - dt / 0.35)
                self.root.rotation_x = 90.0 * (1.0 - self._falling)
            self.respawn_left -= dt
            if self.respawn_left <= 0.0:
                self.respawn()
            return
        if self.moving:
            # 巡航：正弦左右移动 ±2.4 米
            self._phase += dt * 0.9
            self.root.x = self._origin_x + 2.4 * (0.5 + 0.5 * __import__('math').sin(self._phase))

    def destroy(self):
        from ursina import destroy
        for ent in self.parts:
            destroy(ent)
        destroy(self.root)


def spawn_dummy_range(center=(-6, 0, -10), count=8, spacing=3.4,
                      tint=None, moving_ratio=0.35):
    """一排训练木偶：一半固定一半巡航，返回 Dummy 列表。"""
    dummies = []
    cx, cy, cz = center
    for i in range(count):
        x = cx + (i - (count - 1) / 2) * spacing
        moving = i % int(max(1, round(1 / max(moving_ratio, 0.01)))) == 0
        d = Dummy(position=(x, cy, cz + (1.6 if i % 3 == 0 else 0)),
                  heading=random.uniform(-14, 14),
                  moving=moving, tint=tint)
        dummies.append(d)
    return dummies
