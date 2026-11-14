# -*- coding: utf-8 -*-
"""1v1 单挑地图：duel_arena.glb 的加载、碰撞与出生点。

模型来源与授权（详见 maps/LICENSES.md 与 README.md）
    模型名   fps/tps map（50×100 米封闭竞技场）
    作者     theking1322（https://poly.pizza/u/theking1322 ）
    来源页面 https://poly.pizza/m/Ga47MW6Mgr
    直接下载 https://static.poly.pizza/781482f7-966f-40e6-b514-415a2721fc6d.glb
    授权     CC-BY 3.0（https://creativecommons.org/licenses/by/3.0/ ）
             —— 免费且明确允许商用/修改/再分发，唯一义务是保留署名。
             本项目按 CC-BY 要求在代码注释、maps/LICENSES.md 与 README.md
             中保留作者署名与来源链接。

技术要点
    * GLB 自带真实基色（16 个材质、无贴图、全 OPAQUE），加载时用
      ``load_glb(keep_colors=True)`` 保留原色，**不套**枪械调色板，
      否则整张地图会被洗成统一的枪灰色。
    * GLB 没有碰撞体：这里给每个网格按世界包围盒自动生成隐形 BoxCollider，
      小于 0.3 米的碎件跳过（数量少、对走位无影响）。
    * 出生点在场地两端（相距 80 米），各自正对中央高台，符合 1v1 的
      对称开局；目标刷新范围收进墙内。
"""
from __future__ import annotations

from ursina import Entity

from weapons.loader import load_glb

MAP_PATH = 'maps/duel_arena.glb'

# 出生点：场地两端东北/西南开阔带（射线探测：正前方与右斜 45 米全通，
# 左斜 18.6 米），两点关于场地中心点对称，保证 1v1 公平
SPAWN = {
    1: (20.0, 1.4, -43.5, 0.0),    # (x, y, z, 面向 yaw)
    2: (-20.0, 1.4, 43.5, 180.0),
}

# 团队竞技（本图兼任团队对战地图）：红队北线、蓝队南线，
# 队内出生点沿各自底线横排（间距 8 米），全部经过开阔带，面向对方半场
TEAM_SPAWNS = {
    'red': [                        # 红队：南侧底线（z 为负），面向 +Z
        (20.0, 1.4, -43.5, 0.0),
        (12.0, 1.4, -43.5, 0.0),
        (28.0, 1.4, -43.5, 0.0),
        (4.0, 1.4, -43.5, 0.0),
        (36.0, 1.4, -43.5, 0.0),
    ],
    'blue': [                       # 蓝队：北侧底线（z 为正），面向 -Z
        (-20.0, 1.4, 43.5, 180.0),
        (-12.0, 1.4, 43.5, 180.0),
        (-28.0, 1.4, 43.5, 180.0),
        (-4.0, 1.4, 43.5, 180.0),
        (-36.0, 1.4, 43.5, 180.0),
    ],
}

# 团队模式阵营色（红 / 蓝，与 HUD 计分板配色一致）
TEAM_COLORS = {
    'red': (196, 74, 58),
    'blue': (86, 132, 220),
}

# 团队模式胜利条件：先达到该分数的阵营获胜
VICTORY_SCORE = 50

# 目标刷新范围 (x_min, x_max, z_min, z_max) 与高度上限
TARGET_AREA = (-18, 18, -38, 38)
TARGET_Y_MAX = 6

# 小于该尺寸（米）的网格不生成碰撞体
_MIN_COLLIDER_SIZE = 0.3


class DuelArena(Entity):
    """加载单挑竞技场并生成碰撞。"""

    def __init__(self, path=MAP_PATH):
        super().__init__(name='duel_arena')
        # keep_colors=True：保留 GLB 自带配色（见模块 docstring 的授权说明）
        self.node = load_glb(path, center=False, keep_colors=True)
        self.node.reparentTo(self)
        self.collider_count = 0
        self._build_colliders()

    def _build_colliders(self):
        """按每个网格的世界包围盒生成隐形碰撞盒。"""
        render = base.render               # ShowBase 注入的 builtin
        for gn in self.node.findAllMatches('**/+GeomNode'):
            try:
                # getTightBounds(render) → 世界坐标包围盒（竞技场自身无变换，
                # 世界坐标即本地坐标）
                mn, mx = gn.getTightBounds(render)
            except Exception:
                continue
            size = (mx.x - mn.x, mx.y - mn.y, mx.z - mn.z)
            if min(size) < _MIN_COLLIDER_SIZE:
                continue
            center = ((mn.x + mx.x) * 0.5, (mn.y + mx.y) * 0.5, (mn.z + mx.z) * 0.5)
            Entity(parent=self, position=center, scale=size, collider='box')
            self.collider_count += 1

    def spawn(self, slot=1):
        """返回出生点 (position, yaw)。"""
        x, y, z, yaw = SPAWN.get(slot, SPAWN[1])
        return (x, y, z), yaw

    def spawn_team(self, team='red', index=0):
        """团队模式出生点：返回 (position, yaw)，索引越界时取模轮换。"""
        pts = TEAM_SPAWNS.get(team) or TEAM_SPAWNS['red']
        x, y, z, yaw = pts[index % len(pts)]
        return (x, y, z), yaw


def load():
    """便捷入口：加载竞技场，失败时返回 None（游戏继续用开阔训练场）。"""
    try:
        arena = DuelArena()
        print(f'[地图] 单挑竞技场已加载：{MAP_PATH} | 碰撞体 {arena.collider_count} 个 '
              '| 作者 theking1322 | CC-BY 3.0')
        return arena
    except Exception as exc:
        print('[地图] 单挑竞技场加载失败，退回训练场：', exc)
        return None
