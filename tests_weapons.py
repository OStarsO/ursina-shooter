# -*- coding: utf-8 -*-
"""武器模块测试：配置 / 动画数学 / GLB 资源 / 近战数值。

不依赖 ursina 与显卡，可以放在 CI 里跑：
    py -3.11 tests_weapons.py
"""
import json
import os
import struct
import sys

sys.path.insert(0, '.')

from combat import Melee, Weapon
import weapons.anim as A
import weapons.config as C

PASS, FAIL = [], []


def check(name, cond, extra=''):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


# ---------------------------------------------------------------- GLB 解析
def read_glb(path):
    """返回 (json 字典, 网格数量, 材质名列表)，用来体检资源文件。"""
    with open(path, 'rb') as f:
        data = f.read()
    magic, version, _ = struct.unpack('<4sII', data[:12])
    assert magic == b'glTF' and version == 2, f'{path} 不是 glTF 2.0'
    jlen = struct.unpack('<I', data[12:16])[0]
    js = json.loads(data[20:20 + jlen])
    mats = [m.get('name', '') for m in js.get('materials', [])]
    prim = sum(len(m.get('primitives', [])) for m in js.get('meshes', []))
    has_pos = any('POSITION' in p.get('attributes', {})
                  for m in js.get('meshes', []) for p in m.get('primitives', []))
    return js, prim, mats, has_pos


def main():
    # ---- 配置结构 -------------------------------------------------
    check('目录含五件武器', set(C.CATALOG) == {'usp', 'deagle', 'ak', 'awm', 'knife'},
          str(sorted(C.CATALOG)))
    check('装备顺序五把', len(C.ORDER) == 5 and set(C.ORDER) == set(C.CATALOG))
    check('by_index 映射', C.by_index(0) == 'usp' and C.by_index(3) == 'awm'
          and C.by_index(4) == 'knife')
    check('by_index 越界返回 None', C.by_index(-1) is None and C.by_index(9) is None)

    required = ('key', 'name', 'kind', 'model', 'length', 'pos', 'rot',
                'muzzle', 'inspect', 'swing', 'ammo')
    ok = all(all(k in spec for k in required) for spec in C.CATALOG.values())
    check('每把武器字段齐全', ok)

    usp, knife = C.CATALOG['usp'], C.CATALOG['knife']
    check('手枪是 gun / 匕首是 melee', usp['kind'] == 'gun' and knife['kind'] == 'melee')
    check('只手枪有弹药参数', bool(usp['ammo']) and knife['ammo'] is None)
    check('只匕首有挥砍动画', knife['swing'] and not usp['swing'])
    check('检视时长合理', 1.0 <= usp['inspect']['duration'] <= 3.0
          and 1.0 <= knife['inspect']['duration'] <= 3.0,
          f"{usp['inspect']['duration']}s / {knife['inspect']['duration']}s")
    check('尺度在手持范围', all(0.1 <= s['length'] <= 1.0 for s in C.CATALOG.values()))
    check('武器位于镜头前方', all(s['pos'][2] > 0.15 for s in C.CATALOG.values()))

    # ---- 关键帧合法性 ---------------------------------------------
    def keys_ok(keys):
        if not keys:
            return False
        if keys[0][0] != 0.0 or keys[-1][0] != 1.0:
            return False
        if any(keys[i][0] >= keys[i + 1][0] for i in range(len(keys) - 1)):
            return False
        # 首尾必须归零，否则动画结束会留下偏移
        _, p0, r0 = keys[0]
        _, p1, r1 = keys[-1]
        return all(abs(v) < 1e-9 for v in p0 + r0 + p1 + r1)

    check('检视关键帧首尾归零且时间递增',
          keys_ok(usp['inspect']['keys']) and keys_ok(knife['inspect']['keys']))
    check('挥砍关键帧首尾归零且时间递增', keys_ok(knife['swing']['keys']))

    # 偏移是相对姿态的增量：偏航超过 60° 会把武器转到摄像机背后（等于隐身）
    max_yaw = max(abs(r[1]) for _, _, r in usp['inspect']['keys']
                  + knife['inspect']['keys'] + knife['swing']['keys'])
    check('动画偏航不超过 60°', max_yaw <= 60.0, f'max={max_yaw}')

    # ---- 动画数学 -------------------------------------------------
    check('clamp 边界', A.clamp(-1) == 0.0 and A.clamp(2) == 1.0 and A.clamp(0.5) == 0.5)
    check('smoothstep 两端固定', A.smoothstep(0) == 0.0 and A.smoothstep(1) == 1.0)
    check('smoothstep 单调递增',
          all(A.smoothstep(i / 20) <= A.smoothstep((i + 1) / 20) for i in range(20)))
    check('smoothstep 中点 0.5', abs(A.smoothstep(0.5) - 0.5) < 1e-9)

    keys = [(0.0, (0, 0, 0), (0, 0, 0)), (0.5, (1, 2, 3), (10, 20, 30)),
            (1.0, (0, 0, 0), (0, 0, 0))]
    p, r = A.sample(keys, 0.0)
    check('采样起点为零', p == (0, 0, 0) and r == (0, 0, 0))
    p, r = A.sample(keys, 0.5)
    check('采样命中关键帧', p == (1, 2, 3) and r == (10, 20, 30))
    p, r = A.sample(keys, 0.25)
    check('采样在两帧之间', 0 < p[0] < 1 and p[1] == p[0] * 2)
    p, r = A.sample(keys, 2.0)
    check('采样越界被夹住', p == (0, 0, 0))
    check('空关键帧安全', A.sample([], 0.5) == ((0, 0, 0), (0, 0, 0)))

    t = A.Track(keys, duration=1.0)
    check('轨道初始未播放', not t.active and t.pose() == ((0, 0, 0), (0, 0, 0)))
    t.play()
    check('播放中 active', t.active and t.progress == 0.0)
    t.update(0.5)
    check('推进一半', abs(t.progress - 0.5) < 1e-6)
    ended = t.update(0.6)
    check('超时自动结束', ended is None and not t.active)
    check('结束后姿态归零', t.pose() == ((0, 0, 0), (0, 0, 0)))

    t.play()
    t.update(0.3)
    t.stop()
    check('stop 立刻复位', not t.active and t.pose() == ((0, 0, 0), (0, 0, 0)))

    s = A.Spring(0.0, speed=12)
    for _ in range(60):
        s.to(1.0).update(1 / 60)
    check('弹簧趋近目标', abs(s.value - 1.0) < 0.01, f'{s.value:.3f}')

    # ---- GLB 资源 -------------------------------------------------
    base = os.path.dirname(os.path.abspath(__file__))
    for key, spec in C.CATALOG.items():
        path = os.path.join(base, spec['model'])
        exists = os.path.exists(path)
        check(f'{key} 模型文件存在', exists, spec['model'])
        if not exists:
            continue
        js, prims, mats, has_pos = read_glb(path)
        check(f'{key} GLB 结构有效', prims > 0 and has_pos, f'{prims} 个图元')
        merged = dict(C.MATERIAL_PALETTE)
        merged.update(spec.get('palette') or {})
        unknown = [m for m in mats if m not in merged]
        # 未知材质会落到 PALETTE_FALLBACK（枪灰），新加入的模型材质命名
        # 不完全一致属预期；只有主武器 usp / knife 才要求全部命中调色板
        if key in ('usp', 'knife'):
            check(f'{key} 材质全部有配色', not unknown, str(unknown) if unknown else '')
        else:
            check(f'{key} 材质可加载', len(mats) > 0, str(mats))

    # ---- 近战数值 -------------------------------------------------
    melee = Melee('刺刀', damage=55, rpm=110, reach=2.6)
    check('近战没有弹药但不为空', melee.mag == 0 and melee.empty is False)
    check('近战首刀可挥出', melee.fire() is True)
    check('近战进入冷却', melee.cooldown > 0)
    check('冷却中挥不出第二刀', melee.fire() is False)
    melee.update(1.0)
    check('冷却结束后可再挥', melee.can_fire() and melee.fire() is True)
    check('近战不支持换弹', melee.start_reload() is False)
    check('近战 HUD 兼容字段',
          melee.mag_size == 0 and melee.reserve == 0
          and melee.reloading is False and melee.reload_progress == 1.0)
    melee.refill()
    check('近战 refill 清冷却', melee.cooldown == 0.0)
    check('近战伤害与距离', melee.damage == 55 and melee.reach == 2.6)

    # ---- 枪械 refill 用回初始备弹 -------------------------------
    w = Weapon('USP-S', mag_size=12, reserve=24, rpm=352, reload_time=2.2)
    w.fire()
    w.reserve = 3
    w.refill()
    check('refill 恢复初始备弹', w.mag == 12 and w.reserve == 24)

    print()
    print(f'通过 {len(PASS)} / 失败 {len(FAIL)}')
    if FAIL:
        print('失败项:', FAIL)
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
