# -*- coding: utf-8 -*-
"""combat.py 数值系统测试（纯逻辑，不需要图形环境）。"""
import sys

sys.path.insert(0, '.')

from combat import Player, Weapon

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def test_weapon():
    w = Weapon('GLOCK-18', mag_size=20, reserve=120, rpm=600, reload_time=2.0)
    check('初始弹匣满', w.mag == 20 and w.reserve == 120)
    check('射击节奏 600rpm', abs(w.interval - 0.1) < 1e-6, f'interval={w.interval}')

    check('第一发可以打', w.fire() is True and w.mag == 19)
    check('冷却期内不能连发', w.fire() is False and w.mag == 19)
    w.update(0.11)
    check('冷却结束后可以再打', w.fire() is True and w.mag == 18)

    # 打空弹匣
    w.update(10)
    w.mag = 1
    w.fire()
    check('打空后 empty', w.empty and w.can_fire() is False)
    check('空弹匣自动上膛请求被接受', w.start_reload() is True)
    check('换弹中不能开火', w.can_fire() is False)
    w.update(2.1)
    check('换弹完成弹匣补满', w.mag == 20, f'mag={w.mag}')
    # 换弹是从备弹里补满 20 发，不是按已打出的发数扣
    check('备弹相应减少', w.reserve == 100, f'reserve={w.reserve}')

    w.reserve = 5
    w.mag = 10
    w.start_reload()
    w.update(2.1)
    check('备弹不足时只补到备弹量', w.mag == 15 and w.reserve == 0, f'{w.mag}/{w.reserve}')

    w.refill()
    check('重生补满', w.mag == 20 and w.reserve == 120 and not w.reloading)

    w.mag = 0
    w.reserve = 0
    check('弹尽时无法换弹', w.start_reload() is False)


def test_player():
    p = Player()
    check('初始 100 血 100 甲', p.health == 100 and p.armor == 100 and p.alive)

    dealt = p.take_damage(40)
    # 有甲：护甲吸收一半伤害，护甲损耗为吸收量的一半
    check('有甲时实际掉血 20', dealt == 20 and p.health == 80, f'hp={p.health}')
    check('护甲损耗 10', p.armor == 90, f'armor={p.armor}')

    p.armor = 0
    dealt = p.take_damage(30)
    check('无甲时全额掉血', dealt == 30 and p.health == 50, f'hp={p.health}')

    p.take_damage(1000)
    check('致命伤后死亡', not p.alive and p.health == 0)
    check('死亡计数 +1', p.deaths == 1)

    p.update(3.1)
    check('死亡倒计时归零', p.death_time == 0.0)
    check('死亡状态不会自动回血', p.health == 0)

    p.respawn()
    check('重生满血满甲', p.alive and p.health == 100 and p.armor == 100)

    # 回血：5 秒未受伤后开始，每秒 9 点
    p.health = 40
    p.since_damage = 0
    p.update(4.0)
    check('未满 5 秒不回血', p.health == 40, f'hp={p.health}')
    p.update(1.5)
    check('超过 5 秒开始回血', p.health > 40, f'hp={p.health:.1f}')
    p.since_damage = 0
    p.update(2.0)
    check('再次受伤后停止回血', p.health < 60, f'hp={p.health:.1f}')

    p.regen_enabled = False
    p.health = 10
    p.since_damage = 0
    p.update(8.0)
    check('关闭回血后不回血', p.health == 10, f'hp={p.health}')

    p.take_damage(5, ignore_armor=True)
    check('ignore_armor 不打护甲', p.armor == 100 and p.health == 5, f'{p.health}/{p.armor}')

    check('低血量判定', p.low_health is True)
    p.health = 80
    p.armor = 33.7
    check('显示数值取整', p.health_text == '80' and p.armor_text == '34')


def main():
    test_weapon()
    test_player()
    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print('失败项:', FAIL)
    return 0 if not FAIL else 1


if __name__ == '__main__':
    sys.exit(main())
