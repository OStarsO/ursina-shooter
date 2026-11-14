# -*- coding: utf-8 -*-
"""人机（Bot）：PvP 单挑与团队竞技的人机补齐 + 三档难度。

难度（房主可选）：
    简单 easy    反应 1.15s · 角度误差 σ7.5° · 射击间隔 0.85s · 伤害 ×0.6
    普通 normal  反应 0.60s · 角度误差 σ3.2° · 射击间隔 0.45s · 伤害 ×1.0
    困难 hard    反应 0.30s · 角度误差 σ1.5° · 射击间隔 0.28s · 伤害 ×1.3

行为：
    巡航 → 视线内发现玩家/敌人 → 转身瞄准（反应延迟）→ 点射（间隔节流）
    → 目标丢失 / 击倒 → 巡航；被击倒播 Death 动画并延时重生。

伤害判定：
    Bot 与玩家使用同一套 combat 三区倍率。命中部位按"瞄准点离地高度"
    用 combat.classify_zone_by_height 划分（头 / 躯干 / 肢体），与玩家
    被击中时的判定完全一致。

联机：Bot 的每次命中会通过 hit_claim 上报房间服务器，由服务器按
anticheat.AntiCheat 的规则（射速 / 单发伤害上限 / 部位倍率 / 目标存活）
验证后才计入权威比分，详见 anticheat.py。
"""

import math
import random

from ursina import Entity, color, raycast, Vec3

import combat
from combat import ZONE_MULTIPLIERS, classify_zone_by_height
from weapons.config import CATALOG as WEAPON_CATALOG

# 队伍着色（RGB 0-1，覆盖 Soldier 模型材质色）
TEAM_TINT = {'red': (1.0, 0.55, 0.5), 'blue': (0.55, 0.68, 1.0)}

DIFFICULTY = {
    'easy':   dict(label='简单', react=1.15, err=7.5, interval=0.85,
                   speed=3.2, hp=80, dmg_mult=0.6, range_m=36),
    'normal': dict(label='普通', react=0.60, err=3.2, interval=0.45,
                   speed=5.2, hp=100, dmg_mult=1.0, range_m=46),
    'hard':   dict(label='困难', react=0.30, err=1.5, interval=0.28,
                   speed=6.8, hp=120, dmg_mult=1.3, range_m=56),
}
DIFFICULTY_ORDER = ('easy', 'normal', 'hard')


class Bot:
    """一个人机。``collider`` 实体带 ``bot_ref`` 引用，供子弹解析命中。"""

    def __init__(self, name, team, difficulty='normal', position=(0, 0, 0),
                 heading=0, fire_audio=None, on_hit_player=None,
                 on_killed=None):
        self.name = name
        self.team = team
        self.member_id = None              # 房间成员 id（联机命中上报用）
        self.diff_key = difficulty if difficulty in DIFFICULTY else 'normal'
        self.cfg = DIFFICULTY[self.diff_key]
        self.weapon_key = 'ak'
        spec = WEAPON_CATALOG[self.weapon_key]['ammo']
        self.base_damage = spec.get('damage', 30)
        self.on_hit_player = on_hit_player        # fn(dmg, zone, bot)
        self.on_killed = on_killed                # fn(bot, zone)  玩家击倒时
        self.fire_audio = fire_audio

        self.root = Entity(position=position, rotation_y=heading)
        self.collider = Entity(parent=self.root, model=None, collider='box',
                               scale=(0.9, 1.8, 0.9), position=(0, 0.9, 0))
        self.collider.bot_ref = self

        self.actor = None
        self.anims = {}
        try:
            from direct.actor.Actor import Actor as PandaActor
            self.actor = PandaActor('characters/soldier.glb')
            self.actor.reparentTo(self.root)
            mn, mx = self.actor.getTightBounds()
            self.actor.setPos(0, 0, -mn.z)
            self.actor.setSz(1.8 / max(0.01, mx.z - mn.z))
            tint = TEAM_TINT.get(team, (1, 1, 1))
            self.actor.setColorScale(*tint, 1.0)
            for n in self.actor.getAnimNames():
                if n:
                    self.anims[n.lower()] = n
            self.anims.setdefault('run', self.anims.get('run_shoot', 'Run'))
            self.anims.setdefault('idle', self.anims.get('idle_gun_pointing', 'Idle'))
            self.anims.setdefault('death', self.anims.get('death', 'Death'))
            self.actor.loop(self.anims['idle'])
        except Exception as exc:
            print(f'[bot] {name} 模型加载失败，降级为方块:', exc)
            from ursina import destroy
            destroy(self.collider)
            self.collider = Entity(parent=self.root, model='cube', collider='box',
                                   scale=(0.9, 1.8, 0.9), position=(0, 0.9, 0),
                                   color=color.rgb32(86, 132, 220))
            self.collider.bot_ref = self

        # ---- 状态 ----
        self.max_hp = self.cfg['hp']
        self.hp = self.max_hp
        self.alive = True
        self.respawn_left = 0.0
        self.react_left = 0.0
        self.fire_cd = 0.0
        self._waypoint = None
        self._home = Vec3(*position[:3]) if not isinstance(position, Vec3) else position
        self._speed_now = 0.0

    # ---------------- 动画 ----------------
    def _anim(self, name):
        if self.actor is not None:
            anim = self.anims.get(name)
            if anim:
                try:
                    self.actor.loop(anim)
                except Exception:
                    pass

    # ---------------- 感知 ----------------
    def can_see(self, target_pos, max_dist, ignore=()):
        eye = self.root.world_position + Vec3(0, 1.55, 0)
        direction = target_pos - eye
        dist = direction.length()
        if dist > max_dist:
            return False
        hit = raycast(eye, direction.normalized(), distance=dist,
                      ignore=(self.collider,) + tuple(ignore))
        # 射线终点没撞到别的东西（或撞到的就是目标本体）= 视线通畅
        return (not hit.hit) or hit.distance >= dist - 0.6

    # ---------------- 行为 ----------------
    def _pick_waypoint(self):
        ang = random.uniform(0, 6.283)
        r = random.uniform(4.0, 10.0)
        self._waypoint = Vec3(self._home.x + math.cos(ang) * r,
                              self._home.y, self._home.z + math.sin(ang) * r)

    def _walk_toward(self, point, dt, turn_speed=6.0):
        to = point - self.root.position
        to.y = 0
        dist = to.length()
        if dist < 0.5:
            return 0.0
        # 面向目标平滑转身
        target_h = math.degrees(math.atan2(to.x, to.z))
        self.root.rotation_y += (target_h - self.root.rotation_y) * min(1.0, dt * turn_speed)
        step = self.cfg['speed'] * dt
        self.root.position += to.normalized() * min(step, dist)
        self._speed_now = self.cfg['speed']
        return dist

    def _fire_at(self, target_pos, dt):
        """对目标开火：角度误差决定命中；命中部位按瞄准点高度划分。"""
        if self.fire_cd > 0.0:
            return
        self.fire_cd = self.cfg['interval']
        dist = max(1.0, (target_pos - self.root.world_position).length())
        # 高斯角度误差；人体有效半径 0.45 米，超出即脱靶
        sigma = self.cfg['err']
        miss_deg = abs(random.gauss(0.0, sigma))
        hit_radius = 0.45
        allow_deg = math.degrees(math.atan2(hit_radius, dist))
        if miss_deg > allow_deg * 1.35:
            return                                  # 脱靶
        # 命中：按瞄准点高度划部位（与玩家被击中的判定同源）
        aim_y = min(1.85, max(0.0, random.gauss(1.18, 0.42)))
        zone = classify_zone_by_height(aim_y)
        dmg = combat.zone_damage(self.base_damage * self.cfg['dmg_mult'], zone)
        if self.on_hit_player is not None:
            self.on_hit_player(dmg, zone, self)
        if self.fire_audio is not None:
            try:
                self.fire_audio.play()
            except Exception:
                pass

    def update(self, dt, target_pos=None, target_alive=True, world_ignore=()):
        """target_pos：玩家（或对手）位置；world_ignore：视线检测忽略列表。"""
        self.fire_cd = max(0.0, self.fire_cd - dt)

        if not self.alive:
            self.respawn_left -= dt
            if self.respawn_left <= 0.0:
                self.respawn()
            return

        engaged = False
        if target_alive and target_pos is not None:
            engaged = self.can_see(target_pos, self.cfg['range_m'],
                                   ignore=world_ignore)
        if engaged:
            # 转向目标 + 反应延迟 + 点射
            to = target_pos - self.root.position
            to.y = 0
            target_h = math.degrees(math.atan2(to.x, to.z))
            self.root.rotation_y += (target_h - self.root.rotation_y) * min(1.0, dt * 8.0)
            self.react_left -= dt
            if self.react_left <= 0.0:
                self._fire_at(target_pos, dt)
            self._speed_now = 0.0
            self._anim('idle')
        else:
            self.react_left = self.cfg['react']     # 丢失视线 → 重新计时反应
            if self._waypoint is None:
                self._pick_waypoint()
            left = self._walk_toward(self._waypoint, dt)
            if left < 0.6:
                self._pick_waypoint()
            self._anim('run' if self._speed_now > 0.5 else 'idle')

        self._speed_now = 0.0

    # ---------------- 受击 / 死亡 ----------------
    def take_damage(self, base_damage, zone):
        """玩家子弹命中：返回 (是否击倒, 实际伤害)。"""
        if not self.alive:
            return False, 0.0
        dmg = combat.zone_damage(base_damage, zone)
        self.hp -= dmg
        if self.hp <= 0:
            self.knock_down()
            return True, dmg
        return False, dmg

    def knock_down(self):
        self.alive = False
        self.respawn_left = 3.0
        self.hp = 0
        if self.actor is not None:
            try:
                self.actor.play(self.anims['death'])
            except Exception:
                self._anim('death')

    def respawn(self):
        self.alive = True
        self.hp = self.max_hp
        self.respawn_left = 0.0
        self.react_left = self.cfg['react']
        self.root.position = self._home
        if self.actor is not None:
            self._anim('idle')

    def destroy(self):
        from ursina import destroy
        if self.actor is not None:
            self.actor.cleanup()
            self.actor.removeNode()
        destroy(self.collider)
        destroy(self.root)
