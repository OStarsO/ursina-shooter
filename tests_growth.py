# -*- coding: utf-8 -*-
"""growth 成长系统测试（纯逻辑）。"""
import sys

sys.path.insert(0, ".")

import growth

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def match(**kw):
    base = {'mode': 'team5', 'win': 'win', 'score': 50, 'kills': 3, 'deaths': 1,
            'assists': 1, 'headshots': 1, 'max_streak': 3, 'mvp': False,
            'duration': 180}
    base.update(kw)
    return base


def test_profile_defaults():
    p = growth.default_profile()
    check('默认档案字段齐全',
          all(k in p for k in ('xp', 'level', 'matches', 'history', 'achievements')))
    old = {'xp': 300, 'level': 2, 'kills': 7}
    n = growth.normalize(old)
    check('旧档案补齐且不丢数据', n['kills'] == 7 and 'headshots' in n)
    check('非法类型被纠正', growth.normalize({'kills': 'x'})['kills'] == 0)


def test_xp_levels():
    check('0 XP = Lv.1', growth.level_for_xp(0) == 1)
    check('120 XP = Lv.2', growth.level_for_xp(120) == 2)
    check('3179 < Lv.9', growth.level_for_xp(3179) == 8)
    check('3180 = Lv.9', growth.level_for_xp(3180) == 9)
    check('封顶 12 级', growth.level_for_xp(999999) == growth.MAX_LEVEL)
    lv, cur, need, pct = growth.xp_progress(180)
    check('进度换算', lv == 2 and cur == 60 and need == 180 and pct == 33,
          f'{lv} {cur}/{need} {pct}%')
    win_xp = growth.xp_for(match(win='win'))
    loss_xp = growth.xp_for(match(win='loss'))
    check('胜利 XP 高于失败', win_xp > loss_xp, f'{win_xp} vs {loss_xp}')


def test_apply_match():
    p = growth.default_profile()
    s = growth.apply_match(p, match())
    check('场次累加', p['matches'] == 1 and s['matches'] == 1)
    check('击杀/爆头入库', p['kills'] == 3 and p['headshots'] == 1)
    check('胜负统计', p['wins'] == 1 and p['losses'] == 0)
    check('胜率 100%', s['win_rate'] == 100.0)
    check('KDA 计算', s['avg_kda'] == 3.5, str(s['avg_kda']))
    check('历史新增一条', len(p['history']) == 1 and p['history'][0]['mode'] == 'team5')
    check('模式最佳记录', p['best_by_mode'].get('team5') == 50)
    check('模式集合记录', 'team5' in p['modes_played'])
    check('XP 发放', s['xp'] > 0 and p['xp'] == s['xp'])


def test_history_cap_and_best():
    p = growth.default_profile()
    for i in range(25):
        growth.apply_match(p, match(score=i, mode='duel' if i % 2 else 'training'))
    check('历史截断到 20 条', len(p['history']) == 20)
    check('历史最新在前', p['history'][0]['score'] == 24)
    check('各模式最佳独立',
          p['best_by_mode'].get('duel') == 23 and p['best_by_mode'].get('training') == 24)


def test_achievements():
    p = growth.default_profile()
    s = growth.apply_match(p, match(kills=5, headshots=5, max_streak=5, mvp=True))
    ids = {a['id'] for a in s['achievements']}
    check('首杀', 'first_blood' in ids)
    check('三杀', 'triple_kill' in ids)
    check('五连杀', 'penta_kill' in ids)
    check('精准射手（单局5爆头）', 'sharp_eye' in ids)
    check('首次 MVP', 'mvp_first' in ids)
    check('成就只解锁一次', not growth.apply_match(p, match())['achievements'])

    for _ in range(20):
        growth.apply_match(p, match(kills=5, headshots=5, max_streak=1))
    check('爆头王（累计20）', 'headhunter' in p['achievements'])
    check('百人斩（累计100杀）', 'century' in p['achievements'])
    for _ in range(30):
        growth.apply_match(p, match(kills=0, headshots=0))
    check('十场老兵', 'veteran_10' in p['achievements'])

    p2 = growth.default_profile()
    for mode in ('training', 'duel', 'team5'):
        growth.apply_match(p2, match(mode=mode))
    check('全能选手（三模式）', 'explorer' in p2['achievements'])


def test_unlocks():
    p = growth.default_profile()
    check('初始只有十字准星', growth.unlocked_crosshairs(p) == ['cross'])
    check('初始无涂装', growth.unlocked_skins(p) == ['default'])
    p['level'] = 5
    cross = growth.unlocked_crosshairs(p)
    skins = growth.unlocked_skins(p)
    check('Lv.5 解锁圆点/T/粗十字', {'cross', 'dot', 't', 'thick'} <= set(cross))
    check('Lv.5 解锁数码涂装', 'digital' in skins)
    p['level'] = 9
    check('Lv.9 解锁碳纤维', 'carbon' in growth.unlocked_skins(p))
    p['level'] = 10
    check('Lv.10 解锁精英臂章', 'elite' in growth.unlocked_armbands(p))
    p['level'] = 4
    p['xp'] = 560
    s = growth.apply_match(p, match(kills=20, headshots=20, max_streak=5,
                                    score=200, mvp=True))
    check('升级返回解锁提示', s['level_up'] and s['unlocks'], str(s['unlocks']))


def main():
    test_profile_defaults()
    test_xp_levels()
    test_apply_match()
    test_history_cap_and_best()
    test_achievements()
    test_unlocks()
    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print("失败项:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
