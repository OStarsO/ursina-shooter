# -*- coding: utf-8 -*-
"""cube 拼装掩体地图（大厅/走廊/箱体 + 三出生点 + 边界墙）。

设计目标
    * 纯几何数据（OBSTACLES 为 AABB 列表），不导入引擎 —— 服务端 netsim
      的弹道/碰撞与客户端渲染共用**同一份**几何，判定不会两边不一致。
    * 布局对称（中心对称 + 左右镜像），红蓝出生点公平：各 3 个，位于两端
      开阔走廊，出生即面向中场。
    * 边界：外圈 4.2m 高实体墙 + 12m 高隐形墙（防止极端情况下越出坠落）。

坐标系：ursina 左手系，+Z 为北，红队南侧（z<0）、蓝队北侧（z>0）。
单位：米。场地 80×80，墙内可走范围约 ±38。
"""

from __future__ import annotations

import math

ARENA_HALF = 40.0
WALL_H = 4.2
INVIS_H = 12.0

# 实体障碍（AABB：x0, y0, z0, x1, y1, z1）
OBSTACLES = []
# 隐形边界（只挡人不挡子弹：子弹穿过隐形墙属正常，防止玩家越界）
INVISIBLE = []


def _box(x0, y0, z0, x1, y1, z1, solid=True):
    (OBSTACLES if solid else INVISIBLE).append(
        (min(x0, x1), min(y0, y1), min(z0, z1),
         max(x0, x1), max(y0, y1), max(z0, z1)))


# ---------------- 外周实体墙 ----------------
_T = 0.6     # 半厚
_box(-ARENA_HALF, 0, ARENA_HALF - _T, ARENA_HALF, WALL_H, ARENA_HALF + _T)
_box(-ARENA_HALF, 0, -ARENA_HALF - _T, ARENA_HALF, WALL_H, -ARENA_HALF + _T)
_box(ARENA_HALF - _T, 0, -ARENA_HALF, ARENA_HALF + _T, WALL_H, ARENA_HALF)
_box(-ARENA_HALF - _T, 0, -ARENA_HALF, -ARENA_HALF + _T, WALL_H, ARENA_HALF)

# ---------------- 隐形高墙（防越界坠落） ----------------
for _x in (-ARENA_HALF, ARENA_HALF):
    _box(_x - 0.2, 0, -ARENA_HALF, _x + 0.2, INVIS_H, ARENA_HALF, solid=False)
for _z in (-ARENA_HALF, ARENA_HALF):
    _box(-ARENA_HALF, 0, _z - 0.2, ARENA_HALF, INVIS_H, _z + 0.2, solid=False)

# ---------------- 中央高台（可上台，四角掩体） ----------------
_box(-4.0, 0, -4.0, 4.0, 1.1, 4.0)            # 台体
for _sx in (-1, 1):
    for _sz in (-1, 1):
        _box(_sx * 3.0 - 0.5, 1.1, _sz * 3.0 - 0.5,
             _sx * 3.0 + 0.5, 2.6, _sz * 3.0 + 0.5)   # 台上四角矮墙

# ---------------- 走廊：两段错开的纵墙形成 S 形通道 ----------------
_box(-24.0, 0, -2.2, -4.0, 3.0, -1.0)          # 南侧长墙（西半）
_box(4.0, 0, 1.0, 24.0, 3.0, 2.2)              # 北侧长墙（东半）
_box(-8.0, 0, -10.0, -6.8, 2.6, -2.2)          # 走廊入口短墙（西）
_box(6.8, 0, 2.2, 8.0, 2.6, 10.0)              # 走廊入口短墙（东）

# ---------------- 箱体（对称布置，可当掩体/掩身） ----------------
_CRATES = [
    (-14, -12, 1.4), (-14, 12, 1.4), (14, -12, 1.4), (14, 12, 1.4),
    (-26, -4, 1.2), (-26, 4, 1.2), (26, -4, 1.2), (26, 4, 1.2),
    (-3, -18, 1.6), (3, 18, 1.6),
]
for _cx, _cz, _cs in _CRATES:
    _box(_cx - _cs / 2, 0, _cz - _cs / 2, _cx + _cs / 2, _cs, _cz + _cs / 2)
# 两只叠高的箱（常见蹲点）
_box(-3.6, 1.6, -18.6, -1.6, 3.2, -17.4)
_box(1.6, 1.6, 17.4, 3.6, 3.2, 18.6)

# ---------------- 两侧小房间（L 形三面墙，内可藏人） ----------------
for _side in (-1, 1):
    _x0 = _side * 32.0
    _box(_x0 - 0.5, 0, 14.0, _x0 + 0.5, 3.0, 26.0)      # 朝向场地内侧的墙
    _box(_x0 - 6.0, 0, 14.0, _x0 + 0.5, 3.0, 15.0)      # 南墙
    _box(_x0 - 6.0, 0, 25.0, _x0 + 0.5, 3.0, 26.0)      # 北墙
    _box(_x0 - 0.5, 0, -26.0, _x0 + 0.5, 3.0, -14.0)    # 镜像：南侧房间
    _box(_x0 - 6.0, 0, -26.0, _x0 + 0.5, 3.0, -25.0)
    _box(_x0 - 6.0, 0, -15.0, _x0 + 0.5, 3.0, -14.0)

# ---------------- 出生点（每队 3 个，端线开阔带） ----------------
SPAWNS = {
    'red': [(-26.0, 1.4, -34.0, 0.0), (0.0, 1.4, -34.0, 0.0), (26.0, 1.4, -34.0, 0.0)],
    'blue': [(-26.0, 1.4, 34.0, 180.0), (0.0, 1.4, 34.0, 180.0), (26.0, 1.4, 34.0, 180.0)],
}

# 玩家可走边界（服务端夹取用，留 1m 缓冲）
BOUND = ARENA_HALF - 1.6
Y_MIN, Y_MAX = -2.0, 6.0

# 训练场目标刷新范围（与旧地图数据对齐）
TARGET_AREA = (-28, 28, -30, 30)
TARGET_Y_MAX = 4.0


def spawn_team(team='red', index=0):
    pts = SPAWNS.get(team) or SPAWNS['red']
    x, y, z, yaw = pts[index % len(pts)]
    return (x, y, z), yaw


def spawn_duel(slot=1):
    return spawn_team('red' if slot == 1 else 'blue', 0)


# ------------------------------------------------------------------ 几何工具

def aabb_ray(origin, direction, max_dist, boxes):
    """射线 vs AABB 列表（slab 法），返回 (距离, 索引) 或 (None, -1)。"""
    ox, oy, oz = origin
    dx, dy, dz = direction
    best_t, best_i = None, -1
    for i, (x0, y0, z0, x1, y1, z1) in enumerate(boxes):
        t0, t1 = 0.0, max_dist
        ok = True
        for o, d, lo, hi in ((ox, dx, x0, x1), (oy, dy, y0, y1), (oz, dz, z0, z1)):
            if abs(d) < 1e-9:
                if o < lo or o > hi:
                    ok = False
                    break
                continue
            ta, tb = (lo - o) / d, (hi - o) / d
            if ta > tb:
                ta, tb = tb, ta
            t0 = max(t0, ta)
            t1 = min(t1, tb)
            if t0 > t1:
                ok = False
                break
        if ok and t0 <= max_dist and (best_t is None or t0 < best_t):
            best_t, best_i = t0, i
    return best_t, best_i


def ray_capsule(origin, direction, base, height=1.8, radius=0.45):
    """射线 vs 竖直胶囊（简化成圆柱）：返回距离或 None。"""
    ox, oy, oz = origin
    dx, dy, dz = direction
    bx, by, bz = base
    # 水平面圆柱求交
    a = dx * dx + dz * dz
    if a < 1e-9:
        return None
    fx, fz = ox - bx, oz - bz
    b = 2 * (fx * dx + fz * dz)
    c = fx * fx + fz * fz - radius * radius
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    sq = math.sqrt(disc)
    for t in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)):
        if t <= 0:
            continue
        y = oy + dy * t
        if by <= y <= by + height:
            return t
    return None


def point_blocked(x, z, radius=0.45, boxes=None):
    """点（含半径）是否落在障碍里（水平投影判定，用于移动/出生校验）。"""
    boxes = OBSTACLES if boxes is None else boxes
    for x0, y0, z0, x1, y1, z1 in boxes:
        if (x0 - radius <= x <= x1 + radius) and (z0 - radius <= z <= z1 + radius):
            return True
    return False


def clamp_to_bounds(pos):
    x, y, z = pos
    return (max(-BOUND, min(BOUND, x)), y, max(-BOUND, min(BOUND, z)))


# ------------------------------------------------------------------ 场景构建

def build(parent=None):
    """在 ursina 场景里生成本图（客户端用）；返回创建的方块数量。"""
    from ursina import Entity, color

    concrete = color.rgb32(74, 80, 88)
    concrete_dark = color.rgb32(58, 62, 70)
    crate = color.rgb32(126, 96, 62)
    steel = color.rgb32(96, 104, 116)

    count = 0

    def cube(x0, y0, z0, x1, y1, z1, col, collider=True):
        nonlocal count
        sx, sy, sz = x1 - x0, y1 - y0, z1 - z0
        Entity(parent=parent, model='cube', collider='box' if collider else None,
               position=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
               scale=(sx, sy, sz), color=col)
        count += 1

    for box in OBSTACLES:
        x0, y0, z0, x1, y1, z1 = box
        h = y1 - y0
        # 箱体配色：高度 ≤ 3.4 且面积小 → 木箱；否则混凝土
        area = (x1 - x0) * (z1 - z0)
        col = crate if (h <= 3.4 and area <= 12) else (
            concrete_dark if h >= WALL_H - 0.3 else concrete)
        if (x1 - x0) <= 1.2 and h >= 2.5 and area <= 12:
            col = steel
        cube(*box, col)

    # 隐形墙不渲染
    return count


class CoverArena:
    """与旧 DuelArena 相同的出生点接口（射击.py 无缝替换）。"""

    def __init__(self):
        self.block_count = build()

    def spawn(self, slot=1):
        return spawn_duel(slot)

    def spawn_team(self, team='red', index=0):
        return spawn_team(team, index)


def load():
    """构建掩体地图；失败返回 None（游戏退回开阔训练场）。"""
    try:
        arena = CoverArena()
        print(f'[地图] 掩体地图已生成：{arena.block_count} 个方块 | '
              f'红蓝各 3 个出生点 | 外周墙 4.2m + 隐形墙 12m')
        return arena
    except Exception as exc:  # noqa: BLE001
        print('[地图] 掩体地图构建失败，退回开阔训练场：', exc)
        return None
