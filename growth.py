# -*- coding: utf-8 -*-
"""轻量成长系统：XP / 等级 / 解锁 / 成就（纯逻辑，可单测）。

设计取舍
    * 不做经济、开箱、付费；XP 只来自每局结算，纯本地存档（profile.json）。
    * 等级解锁外观：准星样式、武器涂装、玩家臂章——只影响表现，不影响数值。
    * 成就 14 个，覆盖首杀/连杀/爆头/场次/胜场/MVP/等级/模式广度；
      达成由 ``apply_match()`` 统一判定，返回新解锁列表供 HUD 横幅与结算页展示。

存档结构（profile.json，游戏目录）
    xp / level / matches / wins / losses / draws / kills / deaths / assists
    headshots / mvps / best_streak / best_by_mode / modes_played
    history[≤20] / achievements{id: 达成时间} / skin / updated
"""

from __future__ import annotations

import time

MAX_LEVEL = 12
# 升到 Lv.n 所需累计 XP（索引 = 等级；索引 0/1 都为 0）
LEVEL_XP = [0, 0, 120, 300, 560, 900, 1320, 1840, 2460, 3180, 4000, 5000, 6200]

# 等级解锁：crosshair 准星 / skin 涂装 / armband 臂章
UNLOCKS = {
    2: {'crosshair': ['dot']},
    3: {'crosshair': ['t']},
    4: {'crosshair': ['thick']},
    5: {'skin': ['digital']},
    7: {'armband': ['veteran']},
    9: {'skin': ['carbon']},
    10: {'armband': ['elite']},
}

CROSSHAIR_CN = {'cross': '十字', 'dot': '圆点', 't': 'T 形', 'thick': '粗十字'}
SKIN_CN = {'default': '原版', 'digital': '数码迷彩', 'carbon': '碳纤维'}
ARMBAND_CN = {'default': '无', 'veteran': '老兵臂章', 'elite': '精英臂章'}

ACHIEVEMENTS = [
    ('first_blood', '首杀', '完成第一次击杀'),
    ('triple_kill', '三杀', '单局击杀 3 人'),
    ('penta_kill', '五连杀', '单局连续击杀 5 人且未阵亡'),
    ('headhunter', '爆头王', '累计爆头 20 次'),
    ('sharp_eye', '精准射手', '单局爆头 5 次'),
    ('veteran_10', '十场老兵', '完成 10 场对局'),
    ('veteran_100', '百场老兵', '完成 100 场对局'),
    ('winner_10', '常胜将军', '累计 10 场胜利'),
    ('mvp_first', '初露锋芒', '首次获得 MVP'),
    ('mvp_5', '全场最佳', '累计 5 次 MVP'),
    ('century', '百人斩', '累计击杀 100 人'),
    ('explorer', '全能选手', '三种模式各完成 1 局'),
    ('level_5', '步步高升', '达到等级 5'),
    ('level_10', '身经百战', '达到等级 10'),
]
ACH_BY_ID = {a[0]: a for a in ACHIEVEMENTS}


def default_profile():
    return {
        'xp': 0, 'level': 1,
        'matches': 0, 'wins': 0, 'losses': 0, 'draws': 0,
        'kills': 0, 'deaths': 0, 'assists': 0,
        'headshots': 0, 'mvps': 0, 'best_streak': 0,
        'best_by_mode': {}, 'modes_played': [],
        'history': [], 'achievements': {},
        'skin': 'default', 'armband': 'default',
        'updated': '',
    }


def normalize(profile):
    """把旧存档/缺字段的 dict 补齐成完整结构（不丢已有数据）。"""
    base = default_profile()
    if not isinstance(profile, dict):
        return base
    for key, val in base.items():
        if key not in profile:
            profile[key] = val
        elif isinstance(val, dict) and not isinstance(profile.get(key), dict):
            profile[key] = val
        elif isinstance(val, list) and not isinstance(profile.get(key), list):
            profile[key] = val
        elif isinstance(val, int) and not isinstance(profile.get(key), int):
            try:
                profile[key] = int(profile[key])
            except (TypeError, ValueError):
                profile[key] = val
    return profile


def level_for_xp(xp):
    level = 1
    for i in range(2, len(LEVEL_XP)):
        if xp >= LEVEL_XP[i]:
            level = i
    return min(MAX_LEVEL, level)


def xp_progress(xp):
    """返回 (当前等级, 本级已得, 本级所需, 到下一级百分比)。"""
    level = level_for_xp(xp)
    if level >= MAX_LEVEL:
        return level, 1, 1, 100
    start = LEVEL_XP[level]
    need = LEVEL_XP[level + 1] - start
    got = max(0, xp - start)
    return level, got, need, int(100 * got / max(1, need))


def unlocked_crosshairs(profile):
    out = ['cross']
    for lv, items in UNLOCKS.items():
        if profile.get('level', 1) >= lv:
            out += [s for s in items.get('crosshair', []) if s not in out]
    return out


def unlocked_skins(profile):
    out = ['default']
    for lv, items in UNLOCKS.items():
        if profile.get('level', 1) >= lv:
            out += [s for s in items.get('skin', []) if s not in out]
    return out


def unlocked_armbands(profile):
    out = ['default']
    for lv, items in UNLOCKS.items():
        if profile.get('level', 1) >= lv:
            out += [s for s in items.get('armband', []) if s not in out]
    return out


def level_unlock_text(level):
    """该等级解锁内容的可读文本（结算页展示）。"""
    items = UNLOCKS.get(level) or {}
    parts = []
    for key, table in (('crosshair', CROSSHAIR_CN), ('skin', SKIN_CN),
                       ('armband', ARMBAND_CN)):
        for val in items.get(key, []):
            parts.append(table.get(val, val))
    return '、'.join(parts)


def xp_for(match):
    """一局 XP：基础 + 击杀/助攻 + 胜负 + MVP + 分数少许。"""
    kills = int(match.get('kills', 0))
    assists = int(match.get('assists', 0))
    score = int(match.get('score', 0))
    xp = 40 + kills * 12 + assists * 6 + min(60, score // 5)
    if match.get('win') == 'win':
        xp += 60
    elif match.get('win') == 'draw':
        xp += 20
    if match.get('mvp'):
        xp += 40
    return xp


def _ach_conditions(profile, match):
    """返回 {id: bool}（累计条件读 profile，单局条件读 match）。"""
    modes = set(profile.get('modes_played') or [])
    return {
        'first_blood': profile['kills'] >= 1,
        'triple_kill': int(match.get('kills', 0)) >= 3,
        'penta_kill': int(match.get('max_streak', 0)) >= 5,
        'headhunter': profile['headshots'] >= 20,
        'sharp_eye': int(match.get('headshots', 0)) >= 5,
        'veteran_10': profile['matches'] >= 10,
        'veteran_100': profile['matches'] >= 100,
        'winner_10': profile['wins'] >= 10,
        'mvp_first': profile['mvps'] >= 1,
        'mvp_5': profile['mvps'] >= 5,
        'century': profile['kills'] >= 100,
        'explorer': len(modes) >= 3,
        'level_5': profile['level'] >= 5,
        'level_10': profile['level'] >= 10,
    }


def apply_match(profile, match):
    """把一局结果写入成长档案，返回本次结算摘要（不负责写盘）。

    match 字段：mode/win(win|loss|draw)/score/kills/deaths/assists/
                headshots/max_streak/mvp/duration
    """
    profile = normalize(profile)
    hits = int(match.get('headshots', 0))
    kills = int(match.get('kills', 0))
    deaths = int(match.get('deaths', 0))
    assists = int(match.get('assists', 0))
    score = int(match.get('score', 0))
    outcome = match.get('win') or 'draw'
    mode = str(match.get('mode') or 'training')

    profile['matches'] += 1
    profile['kills'] += kills
    profile['deaths'] += deaths
    profile['assists'] += assists
    profile['headshots'] += hits
    if outcome == 'win':
        profile['wins'] += 1
    elif outcome == 'loss':
        profile['losses'] += 1
    else:
        profile['draws'] += 1
    if match.get('mvp'):
        profile['mvps'] += 1
    profile['best_streak'] = max(profile['best_streak'], int(match.get('max_streak', 0)))
    if mode not in profile['modes_played']:
        profile['modes_played'].append(mode)
    best = profile['best_by_mode']
    best[mode] = max(int(best.get(mode, 0)), score)

    gained = xp_for(match)
    old_level = level_for_xp(profile['xp'])
    profile['xp'] += gained
    new_level = level_for_xp(profile['xp'])
    profile['level'] = new_level

    # 历史（最近 20 局，新的在前）
    profile['history'].insert(0, {
        'ts': time.strftime('%Y-%m-%d %H:%M'),
        'mode': mode, 'win': outcome, 'score': score,
        'kills': kills, 'deaths': deaths, 'assists': assists,
        'headshots': hits, 'mvp': bool(match.get('mvp')),
        'xp': gained, 'duration': int(match.get('duration', 0)),
    })
    del profile['history'][20:]

    # 成就判定
    newly = []
    conds = _ach_conditions(profile, match)
    stamp = time.strftime('%Y-%m-%d %H:%M')
    for aid, _name, _desc in ACHIEVEMENTS:
        if aid in profile['achievements']:
            continue
        if conds.get(aid):
            profile['achievements'][aid] = stamp
            newly.append({'id': aid, 'name': ACH_BY_ID[aid][1],
                          'desc': ACH_BY_ID[aid][2]})

    # 等级解锁外观（自动装备最新解锁的涂装/臂章）
    unlocked_now = []
    for lv in range(old_level + 1, new_level + 1):
        items = UNLOCKS.get(lv) or {}
        if items:
            text = level_unlock_text(lv)
            if text:
                unlocked_now.append({'level': lv, 'text': text})
        for skin in items.get('skin', []):
            profile['skin'] = skin
        for band in items.get('armband', []):
            profile['armband'] = band

    profile['updated'] = stamp
    level, cur, need, pct = xp_progress(profile['xp'])
    return {
        'xp': gained, 'total_xp': profile['xp'],
        'level': new_level, 'old_level': old_level,
        'level_up': new_level > old_level,
        'level_text': f'Lv.{new_level}',
        'xp_text': f'{cur}/{need}',
        'progress': pct,
        'achievements': newly,
        'unlocks': unlocked_now,
        'matches': profile['matches'],
        'win_rate': round(100.0 * profile['wins'] / max(1, profile['matches']), 1),
        'avg_kda': round((profile['kills'] + profile['assists'] * 0.5)
                         / max(1, profile['deaths']), 2),
        'skin': profile['skin'], 'armband': profile['armband'],
    }


def summary(profile):
    """给启动器“我的”页/控制台用的摘要。"""
    p = normalize(profile)
    level, cur, need, pct = xp_progress(p['xp'])
    return {
        'level': level, 'xp': p['xp'], 'xp_text': f'{cur}/{need}', 'progress': pct,
        'matches': p['matches'], 'wins': p['wins'], 'losses': p['losses'],
        'draws': p['draws'],
        'win_rate': round(100.0 * p['wins'] / max(1, p['matches']), 1),
        'kills': p['kills'], 'deaths': p['deaths'],
        'avg_kda': round((p['kills'] + p['assists'] * 0.5)
                         / max(1, p['deaths']), 2),
        'headshots': p['headshots'], 'mvps': p['mvps'],
        'best_streak': p['best_streak'],
        'best_by_mode': dict(p['best_by_mode']),
        'achievements': sorted(p['achievements'].keys()),
        'achievement_total': len(ACHIEVEMENTS),
        'history': list(p['history']),
        'skin': p['skin'], 'armband': p['armband'],
    }
