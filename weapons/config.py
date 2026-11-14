# -*- coding: utf-8 -*-
"""武器目录：模型路径、视图模型姿态、检视动画关键帧、弹道参数。

这个文件**不导入引擎**，只放纯数据，方便单测直接读。

坐标系约定（视图模型 = 挂在摄像机下的第一人称武器）
    原点  摄像机位置
    +X    屏幕右      +Y  屏幕上      +Z  镜头朝向（正前方）
模型自身的前向是 +X，所以基础姿态里 rotation_y 会把它转到 +Z。

字段说明
    kind          gun=枪械  melee=近战
    model         GLB 相对路径（相对项目根目录）
    length        模型最长边缩放到的世界长度（1 世界单位 ≈ 1 米）
    pos / rot     基础姿态（挂在摄像机下的位置与欧拉角）
    muzzle        枪口位置，单位是"归一化模型空间"（模型最长边 = 1）
    inspect       检视动画：时长(秒) + 关键帧 [(归一化时间, 位置偏移, 角度偏移)]
    swing         近战挥砍关键帧（仅 melee）
    ammo          弹药与节奏：mag_size / reserve / rpm / reload_time / damage / auto
    recoil        后坐力：kick=每发视角上抬角度, vm=视图模型后坐倍率,
                  recover=每秒回落角度
    spread        散布（度）：base=基础, heat=每发增量, max=上限,
                  move=满速移动惩罚, zoom_mult=开镜倍率（None=不支持开镜）

模型来源与授权（全部 CC0 1.0，见 weapons/LICENSES.md）
    usp_pistol.glb      https://poly.pizza/m/52kQzphmeF   Quaternius
    deagle_pistol.glb   https://poly.pizza/m/Z7aOjJu583   Quaternius
    ak47_rifle.glb      https://poly.pizza/m/K2lXTYFSLC   Quaternius
    awm_sniper.glb      https://poly.pizza/m/i65hEldsw6   Quaternius
    bayonet_knife.glb   https://poly.pizza/m/D81P2smzCy   Quaternius
"""

# ---------------------------------------------------------------- 配色
# glTF 里自带的 PBR 基色几乎是纯黑（0.01~0.06），在无 PBR 管线的场景里
# 会糊成一团黑块。这里按材质名重映射成 CS:GO 风格的枪械配色。
MATERIAL_PALETTE = {
    'Metal':       (78, 82, 88),     # 枪身主体
    'LightMetal':  (124, 129, 136),  # 套筒/滑轨高光件
    'LightMetal2': (146, 150, 157),  # 刀刃
    'DarkMetal':   (52, 55, 60),     # 深色附件
    'Black':       (34, 36, 40),     # 握把胶木
    'Black2':      (26, 27, 31),
    'DarkWood':    (92, 62, 38),
    'Wood':        (110, 76, 44),
}
PALETTE_FALLBACK = (96, 100, 107)

# ---------------------------------------------------------------- 检视（F 键）
# 手枪：抬枪 → 左侧倾（看套筒铭文）→ 停一拍 → 翻到右侧 → 回正
INSPECT_PISTOL = [
    # 偏移是**相对**基础姿态的增量，所以角度都控制在几十度内：
    # 再大就会把枪转到背后（第一人称下等于看不见）
    (0.00, (0.000, 0.000, 0.000), (0, 0, 0)),
    (0.14, (0.008, 0.030, -0.030), (5, -12, 4)),      # 抬枪
    (0.34, (0.014, 0.050, -0.052), (9, -34, 16)),     # 侧倾看左侧铭文
    (0.50, (0.016, 0.052, -0.054), (10, -40, 18)),    # 停一拍
    (0.68, (0.010, 0.036, -0.032), (-7, 22, -10)),    # 翻到右侧
    (0.85, (0.004, 0.014, -0.014), (-4, 8, -3)),
    (1.00, (0.000, 0.000, 0.000), (0, 0, 0)),
]

# 步枪/狙击：抵肩 → 翻过来检查弹匣与导轨 → 拉近看准星 → 回正
INSPECT_RIFLE = [
    (0.00, (0.000, 0.000, 0.000), (0, 0, 0)),
    (0.15, (0.010, 0.026, -0.028), (6, -10, 5)),
    (0.36, (0.018, 0.046, -0.050), (12, -30, 18)),    # 翻过来看弹匣
    (0.56, (0.020, 0.048, -0.052), (14, -42, 22)),    # 停一拍
    (0.74, (0.010, 0.030, -0.030), (-6, 20, -9)),     # 转回看准星
    (0.88, (0.004, 0.012, -0.012), (-3, 7, -3)),
    (1.00, (0.000, 0.000, 0.000), (0, 0, 0)),
]

# 匕首：抬腕 → 翻过来看刀背 → 刀刃朝上端详 → 收枪
INSPECT_KNIFE = [
    (0.00, (0.000, 0.000, 0.000), (0, 0, 0)),
    (0.13, (0.006, 0.030, -0.026), (7, -10, 6)),      # 抬腕
    (0.33, (0.010, 0.048, -0.046), (13, -30, 32)),    # 翻过来看刀背
    (0.55, (0.012, 0.054, -0.052), (17, -40, 56)),    # 刀刃朝上端详
    (0.75, (0.008, 0.028, -0.028), (-6, 18, -14)),
    (0.90, (0.003, 0.010, -0.010), (-3, 6, -5)),
    (1.00, (0.000, 0.000, 0.000), (0, 0, 0)),
]

# 近战挥砍：只有 0.34 秒，起手往外撇 → 向左下划过 → 收回
SWING_KNIFE = [
    (0.00, (0.000, 0.000, 0.000), (0, 0, 0)),
    (0.22, (-0.030, 0.030, -0.020), (6, 26, -16)),    # 起手往外撇
    (0.48, (0.045, -0.045, 0.040), (-14, -34, 30)),   # 向左下划过
    (0.72, (0.010, -0.020, 0.010), (-4, -12, 10)),
    (1.00, (0.000, 0.000, 0.000), (0, 0, 0)),
]


CATALOG = {
    # ------------------------------------------------ 手枪（副武器）
    'usp': {
        'key': 'usp',
        'name': 'USP-S',            # HUD 显示名
        'cn': '手枪',
        'kind': 'gun',
        'slot': 'side',             # 装备槽：primary=主武器 side=副武器 melee=近战
        'model': 'weapons/models/usp_pistol.glb',
        'length': 0.26,
        'pos': (0.082, -0.072, 0.340),
        'rot': (-1.0, -100.0, 3.0),
        'muzzle': (0.50, 0.10, 0.0),
        'inspect': {'duration': 2.1, 'keys': INSPECT_PISTOL},
        'swing': None,
        'ammo': {'mag_size': 12, 'reserve': 24, 'rpm': 352, 'reload_time': 2.2,
                 'damage': 34, 'auto': False},
        # 手枪：轻后坐、快恢复（点射手感干脆）
        'recoil': {'kick': 0.8, 'vm': 1.0, 'recover': 8.0},
        'spread': {'base': 0.5, 'heat': 0.5, 'max': 3.0, 'move': 1.2},
    },
    # ------------------------------------------------ 沙漠之鹰（大口径手枪）
    'deagle': {
        'key': 'deagle',
        'name': 'DESERT EAGLE',
        'cn': '沙漠之鹰',
        'kind': 'gun',
        'slot': 'side',
        'model': 'weapons/models/deagle_pistol.glb',
        'length': 0.28,
        'pos': (0.088, -0.080, 0.340),
        'rot': (-1.5, -100.0, 3.0),
        'muzzle': (0.50, 0.08, 0.0),
        'inspect': {'duration': 2.1, 'keys': INSPECT_PISTOL},
        'swing': None,
        'ammo': {'mag_size': 7, 'reserve': 35, 'rpm': 267, 'reload_time': 2.2,
                 'damage': 53, 'auto': False},
        # 沙鹰：单发重后坐，但恢复较快，不至脱手
        'recoil': {'kick': 2.2, 'vm': 1.8, 'recover': 7.0},
        'spread': {'base': 1.0, 'heat': 1.2, 'max': 5.0, 'move': 1.6},
    },
    # ------------------------------------------------ AK-47（全自动步枪）
    'ak': {
        'key': 'ak',
        'name': 'AK-47',
        'cn': '突击步枪',
        'kind': 'gun',
        'slot': 'primary',
        'model': 'weapons/models/ak47_rifle.glb',
        'length': 0.44,
        'pos': (0.100, -0.100, 0.300),
        'rot': (-2.0, -99.0, 2.0),
        'muzzle': (0.50, 0.10, 0.0),
        'inspect': {'duration': 2.4, 'keys': INSPECT_RIFLE},
        'swing': None,
        'ammo': {'mag_size': 30, 'reserve': 90, 'rpm': 600, 'reload_time': 2.4,
                 'damage': 36, 'auto': True},
        # 步枪：连发持续上抬（压枪手感），停火后快速回位
        'recoil': {'kick': 1.15, 'vm': 1.5, 'recover': 9.0},
        'spread': {'base': 0.7, 'heat': 0.45, 'max': 4.5, 'move': 2.0},
    },
    # ------------------------------------------------ AWM（栓动狙击）
    'awm': {
        'key': 'awm',
        'name': 'AWM',
        'cn': '狙击枪',
        'kind': 'gun',
        'slot': 'primary',
        'model': 'weapons/models/awm_sniper.glb',
        'length': 0.48,
        'pos': (0.115, -0.105, 0.300),
        'rot': (-2.0, -99.0, 2.0),
        'muzzle': (0.50, 0.14, 0.0),
        'inspect': {'duration': 2.6, 'keys': INSPECT_RIFLE},
        'swing': None,
        'ammo': {'mag_size': 5, 'reserve': 30, 'rpm': 41, 'reload_time': 3.6,
                 'damage': 115, 'auto': False},
        # 狙击：单发猛顶（开镜减半），恢复慢一拍，强调"打一枪 re 一下"
        'recoil': {'kick': 4.2, 'vm': 2.6, 'recover': 6.0},
        'spread': {'base': 5.0, 'heat': 0.0, 'max': 5.0, 'move': 3.0, 'zoom_mult': 0.03},
        'zoom_fov': 18,             # 右键开镜后的视野角
    },
    # ------------------------------------------------ 刺刀（近战）
    'knife': {
        'key': 'knife',
        'name': 'BAYONET',          # HUD 显示名
        'cn': '刺刀',
        'kind': 'melee',
        'slot': 'melee',
        'model': 'weapons/models/bayonet_knife.glb',
        'length': 0.32,
        'pos': (0.100, -0.115, 0.300),
        'rot': (-10.0, -96.0, -18.0),
        # 刀刃是 LightMetal / LightMetal2，单独提亮成钢色
        'palette': {'LightMetal': (172, 178, 188), 'LightMetal2': (202, 206, 214),
                    'DarkMetal': (58, 62, 68), 'Black': (34, 36, 40)},
        'muzzle': (0.50, 0.0, 0.0),
        'inspect': {'duration': 1.8, 'keys': INSPECT_KNIFE},
        'swing': {'duration': 0.34, 'keys': SWING_KNIFE},
        'damage': 110,              # 近战：一刀带走一个满血目标
        'ammo': None,
    },
}

# 装备槽 → 可选武器（武器选择商店按这里出列，价格全部为 0）
SLOTS = {
    'primary': ('ak', 'awm'),       # 主武器：步枪 / 狙击
    'side': ('usp', 'deagle'),      # 副武器：手枪
    'melee': ('knife',),            # 近战：匕首（固定）
}
# 默认出厂配装：主 AK + 副 USP + 匕首
DEFAULT_LOADOUT = {'primary': 'ak', 'side': 'usp', 'melee': 'knife'}

# 装备顺序：数字键 1~5 对应下标 0~4，滚轮循环（保留给旧接口与测试；
# 运行时实际可切换的武器由玩家配装决定：匕首 + 副武器 + 主武器）
ORDER = ('usp', 'deagle', 'ak', 'awm', 'knife')


def find(key):
    """按 key 取武器配置，未知 key 抛 KeyError（配置错误要早暴露）。"""
    return CATALOG[key]


def by_index(i):
    """数字键取武器 key，越界返回 None。"""
    return ORDER[i] if 0 <= i < len(ORDER) else None


def spread_at(spec, heat=0.0, move_k=0.0, zoomed=False):
    """当前散布角（度）：基础 + 连射积累 + 移动惩罚，开镜乘 zoom_mult。"""
    sp = spec.get('spread') or {}
    deg = sp.get('base', 0.5) + heat * sp.get('heat', 0.0) + move_k * sp.get('move', 0.0)
    deg = min(deg, sp.get('max', 5.0))
    if zoomed:
        mult = sp.get('zoom_mult')
        if mult is not None:
            deg *= mult
    return deg
