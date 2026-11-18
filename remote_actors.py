# -*- coding: utf-8 -*-
"""远端实体渲染：把服务端快照里的玩家/机器人画出来（含插值与死亡动画）。

数据流：netsim.snapshot() → GameNet.inbox → 这里 update()
    * 位置/朝向用指数插值平滑（15Hz 快照 → 60fps 渲染不抖）
    * 队伍着色：红/蓝，机器人额外在昵称后加「BOT」
    * 头顶：昵称 + 血条（受伤可见，满血淡出）
    * 死亡：播 Death 动画；服务端复活后自动复位

本模块只做表现，不做任何伤害/命中计算（全部服务端权威）。
"""

import math

from ursina import Entity, Text, color, destroy

import ui_theme as T
from bots import CHAR_MODEL, TEAM_RING, TEAM_TINT

HP_W = 0.86


class RemoteActor:
    """单个远端实体（玩家或机器人）。"""

    def __init__(self, data):
        self.id = data["id"]
        self.name = str(data.get("name") or f"P{self.id}")
        self.team = data.get("team", "red")
        self.is_bot = bool(data.get("bot"))
        self.root = Entity(name=f"remote_{self.id}")
        self.root.position = tuple(data.get("pos") or (0, 0, 0))
        self.root.rotation_y = float(data.get("yaw", 0))

        self.actor = None
        self.anims = {}
        try:
            from direct.actor.Actor import Actor as PandaActor
            self.actor = PandaActor(CHAR_MODEL)
            self.actor.reparentTo(self.root)
            mn, mx = self.actor.getTightBounds()
            self.actor.setPos(0, 0, -mn.z)
            self.actor.setSz(1.8 / max(0.01, mx.z - mn.z))
            tint = TEAM_TINT.get(self.team, (1, 1, 1))
            self.actor.setColorScale(*tint, 1.0)
            for n in self.actor.getAnimNames():
                if n:
                    self.anims[n.lower()] = n
            self.anims.setdefault("run", self.anims.get("run_shoot", "Run"))
            self.anims.setdefault("idle", self.anims.get("idle_gun_pointing", "Idle"))
            self.anims.setdefault("death", self.anims.get("death", "Death"))
            self.actor.loop(self.anims["idle"])
            _ring = TEAM_RING.get(self.team, (200, 200, 200))
            Entity(parent=self.root, model="quad", rotation_x=90,
                   scale=(1.15, 1.15), y=0.04,
                   color=color.rgba32(_ring[0], _ring[1], _ring[2], 110))
        except Exception as exc:  # noqa: BLE001
            print(f"[remote] {self.name} 模型加载失败，用方块代替:", exc)
            self.actor = None
            Entity(parent=self.root, model="cube", scale=(0.9, 1.8, 0.9),
                   position=(0, 0.9, 0), color=color.rgb32(
                       196 if self.team == "red" else 86,
                       74 if self.team == "red" else 132,
                       58 if self.team == "red" else 220))

        # 头顶昵称
        label = self.name + ("  BOT" if self.is_bot else "")
        self.tag = Text(parent=self.root, text=label, y=2.05, origin=(0, 0),
                        scale=7, color=color.rgba(235, 242, 250, 230),
                        font=(T.FONT_CJK if any("\u4e00" <= ch <= "\u9fff" for ch in label)
                              else T.FONT_NUM),
                        billboard=True)
        # 血条（常驻但满血时淡出）
        self.hp_bg = Entity(parent=self.root, model="quad", billboard=True,
                            scale=(HP_W, 0.09), y=1.88, z=0.001,
                            color=color.rgba(10, 14, 20, 190))
        self.hp_fill = Entity(parent=self.root, model="quad", billboard=True,
                              scale=(HP_W - 0.03, 0.06), y=1.88, z=0.0,
                              color=color.rgba(90, 220, 140, 235))
        self.hp_fill.origin = (-0.5, 0)

        self.alive = bool(data.get("alive", True))
        self.hp = float(data.get("hp", 100))
        self.max_hp = max(1.0, float(data.get("hp", 100)))
        self.weapon = data.get("weapon", "ak")
        self._dead_t = 0.0
        self._run_anim = False
        self._last_pos = tuple(self.root.position)

    # ------------------------------------------------------------------
    def apply(self, data, dt):
        target = tuple(data.get("pos") or self.root.position)
        cur = tuple(self.root.position)
        k = min(1.0, dt * 12.0)
        self.root.position = (cur[0] + (target[0] - cur[0]) * k,
                              cur[1] + (target[1] - cur[1]) * k,
                              cur[2] + (target[2] - cur[2]) * k)

        # 最短路径转朝向
        target_yaw = float(data.get("yaw", self.root.rotation_y))
        diff = (target_yaw - self.root.rotation_y + 180) % 360 - 180
        self.root.rotation_y += diff * min(1.0, dt * 10.0)

        self.hp = float(data.get("hp", self.hp))
        self.max_hp = max(self.max_hp, self.hp)
        alive = bool(data.get("alive", True))
        self.weapon = data.get("weapon", self.weapon)

        moved = math.dist((self._last_pos[0], self._last_pos[2]),
                          (self.root.x, self.root.z))
        self._last_pos = (self.root.x, self.root.y, self.root.z)
        speed = moved / max(1e-4, dt)

        if alive != self.alive:
            self.alive = alive
            if not alive:
                self._dead_t = 0.0
                self._play("death")
            else:
                self._play("idle")
        if self.alive:
            self._play("run" if speed > 1.5 else "idle")

        # 血条
        ratio = max(0.0, min(1.0, self.hp / self.max_hp))
        self.hp_fill.scale_x = (HP_W - 0.03) * ratio
        self.hp_fill.x = -(HP_W - 0.03) * 0.5
        vis = self.alive and ratio < 0.999
        self.hp_bg.enabled = vis
        self.hp_fill.enabled = vis
        self.hp_fill.color = color.rgba(
            90, 220, 140, 235) if ratio > 0.55 else (
            color.rgba(250, 190, 70, 235) if ratio > 0.25 else color.rgba(240, 80, 80, 235))
        self.tag.enabled = True
        self.tag.color = color.rgba(235, 242, 250, 150 if not self.alive else 230)

        if not self.alive:
            self._dead_t += dt
            if self._dead_t > 1.4:
                self.tag.enabled = False

    def _play(self, name):
        if self.actor is None:
            return
        anim = self.anims.get(name)
        if not anim:
            return
        try:
            self.actor.loop(anim)
        except Exception:  # noqa: BLE001
            pass

    def destroy(self):
        if self.actor is not None:
            try:
                self.actor.cleanup()
                self.actor.removeNode()
            except Exception:  # noqa: BLE001
                pass
        destroy(self.root)


class RemoteWorld:
    """快照实体集合 → 场景对象集合（自动增删）。"""

    def __init__(self):
        self.actors = {}
        self.last_seq = -1

    def update(self, entities, self_id, dt):
        seen = set()
        for data in entities or []:
            mid = data.get("id")
            if mid == self_id:
                continue
            seen.add(mid)
            actor = self.actors.get(mid)
            if actor is None:
                actor = RemoteActor(data)
                self.actors[mid] = actor
            actor.apply(data, dt)
        for mid in list(self.actors):
            if mid not in seen:
                self.actors.pop(mid).destroy()

    def entity(self, mid):
        return self.actors.get(mid)

    def clear(self):
        for actor in self.actors.values():
            actor.destroy()
        self.actors.clear()

    def nearest(self):
        """调试/结算用：返回任意存活远端实体。"""
        for a in self.actors.values():
            if a.alive:
                return a
        return None
