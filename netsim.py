# -*- coding: utf-8 -*-
"""服务端权威世界模拟：玩家状态、机器人 AI、弹道命中、血量与胜负。

纯标准库 + cover_map / combat / weapons.config（都是无引擎模块），
可脱离 ursina 在启动器进程（房主服务端）里跑，也能直接单测。

职责边界
    客户端只上送「我在哪、朝哪看、用什么武器、是否开火」和每次开火的
    起点/方向；**命中判定、伤害数值、血量、死亡、比分、回合结束**全部
    在这里计算，客户端只负责表现。作弊（改伤害/超射速/穿墙）在服务端
    的弹道与射速校验下不成立。

协议
    set_state(mid, {...})   玩家状态（20Hz 由客户端调用）
    fire(mid, origin, dir)  单次开火（服务端按射速节流 + 弹道判定）
    tick(dt)                推进机器人/复活/计时/胜负
    snapshot()              下行快照（含实体、比分、事件、结算）
"""

from __future__ import annotations

import math
import random

import cover_map
import combat
from weapons.config import CATALOG

# 与 bots.py 的三档难度保持一致（这里不能 import bots：那个模块依赖 ursina）
DIFFICULTY = {
    'easy':   dict(label='简单', react=1.15, err=7.5, interval=0.85,
                   speed=3.2, hp=80, dmg_mult=0.6, range_m=36),
    'normal': dict(label='普通', react=0.60, err=3.2, interval=0.45,
                   speed=5.2, hp=100, dmg_mult=1.0, range_m=46),
    'hard':   dict(label='困难', react=0.30, err=1.5, interval=0.28,
                   speed=6.8, hp=120, dmg_mult=1.3, range_m=56),
}

HEAD_Y = 1.55
BODY_Y = 0.75
HEIGHT = 1.8
RADIUS = 0.45
MAX_DIST = 130.0
RESULT_HOLD = 8.0          # 结算页在服务端保留时长，随后广播 lobby


def zone_of(hit_y, base_y):
    h = hit_y - base_y
    if h >= HEAD_Y:
        return 'head'
    if h >= BODY_Y:
        return 'body'
    return 'limb'


class World:
    def __init__(self, members, mode='team5', score_target=50, time_limit=300,
                 respawn=3.0, seed=None):
        self.mode = mode
        self.score_target = int(score_target or 0)
        self.time_limit = float(time_limit or 0)
        self.time_left = float(self.time_limit)
        self.respawn_seconds = float(respawn or 3.0)
        self.damage_mult = 1.0
        self.obstacles = list(cover_map.OBSTACLES)
        self.entities = {}
        self.events = []
        self.seq = 0
        self.result = None
        self.finished_at = None
        self.rng = random.Random(seed)
        self._ids = {}
        for m in members:
            self._add(m)

    # ---------------- 成员 ----------------
    def _add(self, m):
        mid = int(m["id"])
        team = m.get("team") or "red"
        is_bot = bool(m.get("is_bot"))
        diff = (m.get("difficulty") or "normal") if is_bot else "normal"
        cfg = DIFFICULTY.get(diff, DIFFICULTY["normal"])
        pos, yaw = cover_map.spawn_team(team, len(self._ids) % 3)
        e = {
            "id": mid,
            "name": m.get("nickname") or f"P{mid}",
            "team": team,
            "bot": is_bot,
            "difficulty": diff,
            "pos": [pos[0], pos[1] - 1.4, pos[2]],   # 脚底
            "yaw": yaw,
            "pitch": 0.0,
            "weapon": "ak" if is_bot else "usp",
            "firing": False,
            "hp": int(cfg["hp"]) if is_bot else 100,
            "max_hp": int(cfg["hp"]) if is_bot else 100,
            "alive": True,
            "respawn_t": 0.0,
            "kills": 0,
            "deaths": 0,
            "score": 0,
            "god": False,
            "speed_mult": 1.0,
            "last_fire": {},
            "ai": {
                "cfg": cfg,
                "react_left": cfg["react"],
                "fire_cd": 0.0,
                "waypoint": None,
            },
        }
        self.entities[mid] = e
        self._ids[mid] = True
        self.score = {"red": 0, "blue": 0}

    def add_bot(self, mid, name, team, difficulty='normal'):
        self._add({"id": mid, "nickname": name, "team": team,
                   "is_bot": True, "difficulty": difficulty})

    # ---------------- 玩家输入 ----------------
    def set_state(self, mid, data):
        e = self.entities.get(int(mid))
        if e is None:
            return False
        try:
            pos = data.get("pos") or e["pos"]
            x = max(-cover_map.BOUND, min(cover_map.BOUND, float(pos[0])))
            z = max(-cover_map.BOUND, min(cover_map.BOUND, float(pos[2])))
            y = max(cover_map.Y_MIN, min(cover_map.Y_MAX, float(pos[1])))
            x, z, warned = self._check_speed(e, x, z)
            if warned:
                self.events.append({"t": "speed_warn", "id": e["id"],
                                    "speed": round(warned, 1)})
            e["pos"] = [x, y, z]
            e["yaw"] = float(data.get("yaw", e["yaw"]))
            e["pitch"] = float(data.get("pitch", e["pitch"]))
            if data.get("weapon") in CATALOG:
                e["weapon"] = data["weapon"]
            e["firing"] = bool(data.get("firing", False))
            if not e["bot"] and "alive" in data:
                # 客户端只允许"已死"上报，不允许自杀式复活（复活由服务端判定）
                if not data["alive"]:
                    e["alive"] = False
        except (TypeError, ValueError, IndexError):
            return False
        return True

    # 客户端上报间隔约 50ms；允许跳跃/斜坡的短暂超速，这里给 1.6 倍余量
    SPEED_BASE = 8.0
    SPEED_TOLERANCE = 1.6
    SPEED_EXTRA = 2.0

    def _check_speed(self, e, x, z):
        """水平位移/时间 超过上限 → 夹取并返回 (x, z, 实测速度)。"""
        now = self.seq_t()
        prev = e.get("_state_pos") or (e["pos"][0], e["pos"][2])
        prev_t = e.get("_state_t")
        dt = max(0.02, min(0.5, now - prev_t)) if prev_t is not None else 0.05
        dist = math.hypot(x - prev[0], z - prev[1])
        max_speed = (self.SPEED_BASE * float(e.get("speed_mult", 1.0))
                     * self.SPEED_TOLERANCE + self.SPEED_EXTRA)
        limit = max_speed * dt
        warned = 0.0
        if e.pop("_tp_allow", False):
            pass                              # 传送后首个状态不做校验
        elif dist > limit and dist > 0.6:
            k = limit / dist
            x = prev[0] + (x - prev[0]) * k
            z = prev[1] + (z - prev[1]) * k
            warned = dist / dt
            e["speed_hits"] = e.get("speed_hits", 0) + 1
        e["_state_pos"] = (x, z)
        e["_state_t"] = now
        return x, z, warned

    def fire(self, mid, origin, direction):
        """一次开火：射速校验 → 弹道 → 伤害。返回事件 dict 或 None。"""
        e = self.entities.get(int(mid))
        if e is None or not e["alive"] or self.result:
            return None
        weapon = e["weapon"]
        spec = CATALOG.get(weapon)
        if spec is None:
            return None
        if spec.get("kind") == "melee":
            rpm, base = 110, spec.get("damage", 55)
        else:
            rpm, base = (spec.get("ammo") or {}).get("rpm", 1), \
                (spec.get("ammo") or {}).get("damage", 20)
        now = self.seq_t()
        min_iv = 60.0 / max(1, rpm) * 0.9
        last = e["last_fire"].get(weapon)
        if last is not None and now - last < min_iv:
            return None                      # 超射速：丢弃
        e["last_fire"][weapon] = now

        origin = tuple(float(v) for v in origin)
        direction = tuple(float(v) for v in direction)
        norm = math.sqrt(sum(v * v for v in direction)) or 1.0
        direction = tuple(v / norm for v in direction)
        target, dist = self._ray_target(origin, direction, e["id"])
        if target is None:
            return None
        hit_y = origin[1] + direction[1] * dist
        zone = zone_of(hit_y, target["pos"][1])
        dmg = base * combat.ZONE_MULTIPLIERS.get(zone, 1.0) * self.damage_mult
        if target["god"]:
            self.events.append({"t": "blocked", "attacker": e["id"],
                                "victim": target["id"]})
            return None
        dmg = round(dmg, 1)
        target["hp"] = max(0.0, target["hp"] - dmg)
        self.events.append({"t": "hit", "attacker": e["id"],
                            "victim": target["id"], "damage": dmg,
                            "zone": zone, "weapon": weapon,
                            "pos": [round(v, 2) for v in origin]})
        if target["hp"] <= 0:
            self._kill(e, target, weapon, zone)
        return {"target": target["id"], "damage": dmg, "zone": zone}

    def _ray_target(self, origin, direction, shooter_id):
        t_obs, _ = cover_map.aabb_ray(origin, direction, MAX_DIST, self.obstacles)
        best_t = t_obs if t_obs is not None else MAX_DIST
        target = None
        for e in self.entities.values():
            if e["id"] == shooter_id or not e["alive"]:
                continue
            t = cover_map.ray_capsule(origin, direction, e["pos"], HEIGHT, RADIUS)
            if t is not None and t < best_t:
                best_t, target = t, e
        return target, best_t

    def _kill(self, killer, victim, weapon, zone):
        victim["alive"] = False
        victim["hp"] = 0
        victim["deaths"] += 1
        victim["respawn_t"] = self.respawn_seconds
        killer["kills"] += 1
        killer["score"] += 10
        if killer["team"] != victim["team"]:
            self.score[killer["team"]] += 1
        self.events.append({
            "t": "kill", "killer": killer["id"], "victim": victim["id"],
            "weapon": weapon, "zone": zone,
            "killer_name": killer["name"], "victim_name": victim["name"],
            "team": killer["team"],
        })
        self._check_victory()

    def kill_now(self, mid, killer_id=None):
        e = self.entities.get(int(mid))
        if e is None:
            return False
        killer = self.entities.get(int(killer_id)) if killer_id else None
        if killer is None:
            # 管理员处决：自己扣血判死，不计入他人击杀
            e["alive"] = False
            e["hp"] = 0
            e["deaths"] += 1
            e["respawn_t"] = self.respawn_seconds
            self.events.append({"t": "kill", "killer": 0, "victim": e["id"],
                                "weapon": "admin", "zone": "body",
                                "killer_name": "管理员", "victim_name": e["name"],
                                "team": ""})
            return True
        self._kill(killer, e, "admin", "body")
        return True

    def teleport(self, mid, x, z):
        e = self.entities.get(int(mid))
        if e is None:
            return False
        e["pos"][0] = max(-cover_map.BOUND, min(cover_map.BOUND, float(x)))
        e["pos"][2] = max(-cover_map.BOUND, min(cover_map.BOUND, float(z)))
        e["_tp_allow"] = True
        e["_state_pos"] = (e["pos"][0], e["pos"][2])
        return True

    def set_god(self, ids, on=True):
        for e in self.entities.values():
            if ids is None or e["id"] in ids:
                e["god"] = bool(on)

    def set_damage(self, mult):
        self.damage_mult = max(0.1, min(10.0, float(mult)))

    def set_respawn(self, sec):
        self.respawn_seconds = max(0.0, float(sec))

    def set_speed(self, ids, mult):
        for e in self.entities.values():
            if ids is None or e["id"] in ids:
                e["speed_mult"] = max(0.5, min(5.0, float(mult)))

    # ---------------- 推进 ----------------
    def seq_t(self):
        # 用 seq 作为逻辑时钟（每次 tick 递增），避免依赖系统时间便于单测
        return self.seq * 0.05

    def tick(self, dt=0.05):
        self.seq += 1
        if self.result:
            return
        for e in self.entities.values():
            if e["bot"]:
                self._bot_tick(e, dt)
            if not e["alive"]:
                e["respawn_t"] -= dt
                if e["respawn_t"] <= 0:
                    self._respawn(e)
        if self.time_limit:
            self.time_left = max(0.0, self.time_left - dt)
            if self.time_left <= 0:
                self._finish("time")

    def _respawn(self, e):
        pos, yaw = cover_map.spawn_team(e["team"], e["id"] % 3)
        e["pos"] = [pos[0], pos[1] - 1.4, pos[2]]
        e["yaw"] = yaw
        e["hp"] = e["max_hp"]
        e["alive"] = True
        e["respawn_t"] = 0.0
        e["ai"]["react_left"] = e["ai"]["cfg"]["react"]
        e["_state_pos"] = (e["pos"][0], e["pos"][2])
        e["_state_t"] = self.seq_t()
        e["_tp_allow"] = True
        self.events.append({"t": "respawn", "id": e["id"]})

    def _bot_tick(self, e, dt):
        ai = e["ai"]
        cfg = ai["cfg"]
        if not e["alive"]:
            return
        ai["fire_cd"] = max(0.0, ai["fire_cd"] - dt)
        eye = (e["pos"][0], e["pos"][1] + 1.55, e["pos"][2])
        target, dist = self._nearest_enemy(e)
        if target is not None and dist <= cfg["range_m"] and self._los(eye, target):
            # 转身并点射
            dx = target["pos"][0] - e["pos"][0]
            dz = target["pos"][2] - e["pos"][2]
            e["yaw"] = math.degrees(math.atan2(dx, dz))
            ai["react_left"] -= dt
            if ai["react_left"] <= 0 and ai["fire_cd"] <= 0:
                ai["fire_cd"] = cfg["interval"]
                self._bot_fire(e, target, eye, dist)
        else:
            ai["react_left"] = cfg["react"]
            if ai["waypoint"] is None:
                self._bot_pick_waypoint(e)
            wp = ai["waypoint"]
            dx, dz = wp[0] - e["pos"][0], wp[1] - e["pos"][2]
            d = math.hypot(dx, dz)
            if d < 0.8:
                ai["waypoint"] = None
            else:
                step = min(d, cfg["speed"] * e["speed_mult"] * dt)
                nx = e["pos"][0] + dx / d * step
                nz = e["pos"][2] + dz / d * step
                if not cover_map.point_blocked(nx, nz, 0.5):
                    e["pos"][0], e["pos"][2] = nx, nz
                else:
                    ai["waypoint"] = None
                e["yaw"] = math.degrees(math.atan2(dx, dz))

    def _nearest_enemy(self, e):
        best, best_d = None, 1e9
        for o in self.entities.values():
            if o["id"] == e["id"] or not o["alive"] or o["team"] == e["team"]:
                continue
            d = math.dist(e["pos"], o["pos"])
            if d < best_d:
                best, best_d = o, d
        return best, best_d

    def _los(self, eye, target):
        tx = target["pos"][0] - eye[0]
        ty = (target["pos"][1] + 1.2) - eye[1]
        tz = target["pos"][2] - eye[2]
        d = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
        direction = (tx / d, ty / d, tz / d)
        t_obs, _ = cover_map.aabb_ray(eye, direction, d, self.obstacles)
        return t_obs is None or t_obs >= d - 0.4

    def _bot_fire(self, e, target, eye, dist):
        cfg = e["ai"]["cfg"]
        # 高斯角度误差：人体半径 0.45m 对应的角度内即命中
        sigma = cfg["err"]
        miss = abs(self.rng.gauss(0.0, sigma))
        allow = math.degrees(math.atan2(RADIUS, max(1.0, dist)))
        if miss > allow * 1.35:
            self.events.append({"t": "bot_shot", "id": e["id"], "hit": False})
            return
        aim_y = min(HEIGHT - 0.05, max(0.0, self.rng.gauss(1.18, 0.42)))
        tx = target["pos"][0] - eye[0]
        tz = target["pos"][2] - eye[2]
        ty = (target["pos"][1] + aim_y) - eye[1]
        d = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
        base = 36 * cfg["dmg_mult"]
        zone = combat.classify_zone_by_height(aim_y)
        dmg = round(base * combat.ZONE_MULTIPLIERS.get(zone, 1.0) * self.damage_mult, 1)
        if target["god"]:
            self.events.append({"t": "blocked", "attacker": e["id"], "victim": target["id"]})
            return
        target["hp"] = max(0.0, target["hp"] - dmg)
        self.events.append({"t": "hit", "attacker": e["id"], "victim": target["id"],
                            "damage": dmg, "zone": zone, "weapon": "ak",
                            "bot_shot": True})
        if target["hp"] <= 0:
            self._kill(e, target, "ak", zone)

    def _bot_pick_waypoint(self, e):
        for _ in range(8):
            ang = self.rng.uniform(0, math.tau)
            r = self.rng.uniform(6, 22)
            x = max(-cover_map.BOUND + 2, min(cover_map.BOUND - 2, e["pos"][0] + math.cos(ang) * r))
            z = max(-cover_map.BOUND + 2, min(cover_map.BOUND - 2, e["pos"][2] + math.sin(ang) * r))
            if not cover_map.point_blocked(x, z, 0.8):
                e["ai"]["waypoint"] = (x, z)
                return
        e["ai"]["waypoint"] = (0.0, 0.0)

    # ---------------- 胜负 ----------------
    def _check_victory(self):
        if not self.score_target:
            return
        for team in ("red", "blue"):
            if self.score[team] >= self.score_target:
                self._finish("score", team)
                return

    def _finish(self, reason, winner=None):
        if self.result:
            return
        if winner is None:
            if self.score["red"] == self.score["blue"]:
                winner = ""       # 平局
            else:
                winner = "red" if self.score["red"] > self.score["blue"] else "blue"
        rows = []
        for e in self.entities.values():
            if e["bot"] and e["kills"] == 0 and e["deaths"] == 0:
                continue
            rows.append({
                "id": e["id"], "name": e["name"], "team": e["team"],
                "bot": e["bot"], "kills": e["kills"], "deaths": e["deaths"],
                "assists": 0, "score": e["score"],
            })
        rows.sort(key=lambda r: (r["score"], r["kills"]), reverse=True)
        mvp = rows[0] if rows else None
        self.result = {
            "reason": reason, "winner": winner,
            "score": dict(self.score), "rows": rows,
            "mvp": ({"name": mvp["name"], "team": mvp["team"], "score": mvp["score"]}
                    if mvp else None),
        }
        self.finished_at = self.seq * 0.05
        self.events.append({"t": "match_end", "result": self.result})

    def force_end(self, reason="admin"):
        self._finish(reason)

    # ---------------- 快照 ----------------
    def snapshot(self):
        ents = []
        for e in self.entities.values():
            ents.append({
                "id": e["id"], "name": e["name"], "team": e["team"],
                "bot": e["bot"], "pos": [round(v, 2) for v in e["pos"]],
                "yaw": round(e["yaw"], 1), "pitch": round(e["pitch"], 1),
                "hp": int(round(e["hp"])), "alive": e["alive"],
                "weapon": e["weapon"], "firing": e["firing"],
                "kills": e["kills"], "deaths": e["deaths"], "score": e["score"],
            })
        snap = {
            "t": "snapshot", "seq": self.seq,
            "time_left": int(math.ceil(self.time_left)) if self.time_limit else 0,
            "score": dict(self.score), "state": "ended" if self.result else "playing",
            "entities": ents, "events": list(self.events),
            "result": self.result,
        }
        self.events = []
        return snap
