# -*- coding: utf-8 -*-
"""netsim 服务端权威世界测试（纯逻辑，无需引擎/网络）。"""
import sys

sys.path.insert(0, ".")

import cover_map
import netsim

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def make_world(score_target=50, time_limit=0, bots=1):
    members = [
        {"id": 1, "nickname": "玩家", "team": "red", "is_bot": False},
        {"id": 2, "nickname": "对手", "team": "blue", "is_bot": False},
    ]
    for i in range(bots):
        members.append({"id": 100 + i, "nickname": f"BOT{i}", "team": "blue",
                        "is_bot": True, "difficulty": "normal"})
    return netsim.World(members, score_target=score_target, time_limit=time_limit)


def place(w, mid, pos, yaw=0.0):
    w.entities[mid]["pos"] = list(pos)
    w.entities[mid]["yaw"] = yaw


def ticks(w, n, dt=0.05):
    for _ in range(n):
        w.tick(dt)


def test_spawn_and_state():
    w = make_world()
    e = w.entities[1]
    check("出生点在地图内", abs(e["pos"][0]) < cover_map.ARENA_HALF)
    check("出生点不在障碍里",
          not cover_map.point_blocked(e["pos"][0], e["pos"][2], 0.5))
    w.set_state(1, {"pos": [999, 3, -999], "yaw": 123, "weapon": "ak"})
    check("越界坐标被夹取", abs(w.entities[1]["pos"][0]) <= cover_map.BOUND)
    check("武器切换生效", w.entities[1]["weapon"] == "ak")
    w.set_state(1, {"weapon": "railgun"})
    check("非法武器被忽略", w.entities[1]["weapon"] == "ak")


def test_hitscan_and_zone():
    w = make_world()
    place(w, 1, (0, 0, -24))
    place(w, 2, (0, 0, -30))
    w.entities[1]["weapon"] = "ak"
    # 躯干：眼睛高度水平射击
    res = w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("命中躯干", res is not None and res["zone"] == "body" and res["damage"] == 45.0,
          str(res))
    hp_after = w.entities[2]["hp"]
    check("血量按部位扣减", abs(hp_after - 55.0) < 0.1, f"hp={hp_after}")

    # 头部：抬高 0.6m 瞄准（距离 6m，角度约 5.7°）
    w2 = make_world()
    place(w2, 1, (0, 0, -24))
    place(w2, 2, (0, 0, -30))
    w2.entities[1]["weapon"] = "ak"
    res = w2.fire(1, (0, 1.0, -24), (0, 0.1, -1))
    check("命中头部", res is not None and res["zone"] == "head", str(res))
    check("爆头一击致死", not w2.entities[2]["alive"])

    # 掩体阻挡：墙在中间
    w3 = make_world()
    place(w3, 1, (0, 0, 30))
    place(w3, 2, (0, 0, 42))           # 北墙外
    res = w3.fire(1, (0, 1.0, 30), (0, 0, 1))
    check("实体墙挡子弹", res is None)


def test_rate_limit():
    w = make_world()
    place(w, 1, (0, 0, -24))
    place(w, 2, (0, 0, -30))
    w.entities[1]["weapon"] = "ak"
    r1 = w.fire(1, (0, 1.0, -24), (0, 0, -1))
    r2 = w.fire(1, (0, 1.0, -24), (0, 0, -1))     # 同一 tick 连发 → 超射速丢弃
    check("同 tick 连发被拒", r1 is not None and r2 is None)
    ticks(w, 3)                                  # 0.15s > 0.09s
    r3 = w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("间隔足够后放行", r3 is not None)


def test_kill_score_respawn():
    w = make_world(score_target=99, time_limit=0)
    place(w, 1, (0, 0, -24))
    place(w, 2, (0, 0, -30))
    w.entities[1]["weapon"] = "awm"
    res = w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("狙击击杀", res is not None and not w.entities[2]["alive"])
    check("击杀计分", w.score["red"] == 1 and w.entities[1]["kills"] == 1)
    check("死亡记入 K/D", w.entities[2]["deaths"] == 1)
    ticks(w, 70)                                  # 3.5s > 3s 重生
    check("3 秒后自动复活", w.entities[2]["alive"])


def test_victory_and_time():
    w = make_world(score_target=1)
    place(w, 1, (0, 0, -24))
    place(w, 2, (0, 0, -30))
    w.entities[1]["weapon"] = "awm"
    w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("达到目标比分判胜", w.result is not None and w.result["winner"] == "red",
          str(w.result and w.result["winner"]))
    check("结算含 MVP", (w.result or {}).get("mvp") is not None)
    check("结算后拒绝继续开火", w.fire(1, (0, 1.0, -24), (0, 0, -1)) is None)

    w2 = make_world(time_limit=0.2)
    ticks(w2, 10)
    check("计时归零结算", w2.result is not None and w2.result["reason"] == "time")


def test_bots():
    w = make_world(bots=1)
    bot = w.entities[100]
    start = tuple(bot["pos"])
    ticks(w, 40)
    moved = (abs(bot["pos"][0] - start[0]) + abs(bot["pos"][2] - start[2])) > 0.3
    check("机器人会移动/转向", moved, f"{start} → {tuple(bot['pos'])}")
    # 固定到南侧开阔走廊（无遮挡），确保机器人能看到并开火
    bot = w.entities[100]
    bot["pos"] = [0.0, 0.0, -28.0]
    bot["ai"]["waypoint"] = None
    bot["yaw"] = 0.0
    place(w, 1, (0.0, 0.0, -24.0))
    w.entities[1]["god"] = True
    hp0 = w.entities[1]["hp"]
    ticks(w, 80)
    fired = {e.get("t") for e in w.events if e.get("id") == 100 or e.get("attacker") == 100}
    check("机器人会开火（射击/命中/挡伤事件）",
          bool(fired & {"bot_shot", "hit", "blocked"}), str(fired))
    check("god 期间血量不下降", w.entities[1]["hp"] == hp0)


def test_cmd_effects():
    w = make_world()
    place(w, 1, (0, 0, -24))
    place(w, 2, (0, 0, -30))
    w.set_god({2}, True)
    w.entities[1]["weapon"] = "ak"
    w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("god 目标免伤", w.entities[2]["hp"] == 100)
    w.set_god({2}, False)
    ticks(w, 3)
    w.fire(1, (0, 1.0, -24), (0, 0, -1))
    check("关闭 god 后恢复受伤", w.entities[2]["hp"] < 100)

    w.teleport(2, 12, -20)
    check("tp 生效", abs(w.entities[2]["pos"][0] - 12) < 0.01)
    w.kill_now(2)
    check("kill 指令生效", not w.entities[2]["alive"])


def test_speed_cap():
    w = make_world()
    e = w.entities[1]
    e["pos"] = [0.0, 0.0, 0.0]
    e["_state_pos"] = (0.0, 0.0)
    e["_state_t"] = w.seq_t()
    w.set_state(1, {"pos": [0.0, 0.0, 0.0]})
    ticks(w, 2)                                # 0.1 秒
    w.set_state(1, {"pos": [6.0, 0.0, 0.0]})   # 60 m/s 瞬移
    x = w.entities[1]["pos"][0]
    check("超速被夹取", x < 6.0, f"x={x:.2f}")
    check("产生 speed_warn 事件",
          any(ev.get("t") == "speed_warn" for ev in w.events))
    # 传送后首个状态不做速度校验
    w.teleport(1, 30, 0)
    ticks(w, 1)
    w.set_state(1, {"pos": [32.0, 0.0, 0.0]})
    check("传送落点不被误夹", abs(w.entities[1]["pos"][0] - 32.0) < 0.01,
          str(w.entities[1]["pos"][0]))


def test_snapshot():
    w = make_world()
    w.fire(1, (0, 1.0, -24), (0, 0, -1))
    ticks(w, 2)
    snap = w.snapshot()
    check("快照含实体", len(snap["entities"]) == 3)
    check("快照含比分与时间字段",
          "score" in snap and "time_left" in snap and "seq" in snap)
    check("快照事件一次性消费", w.snapshot()["events"] == [])
    self_ent = next(e for e in snap["entities"] if e["id"] == 1)
    check("快照字段完整",
          all(k in self_ent for k in ("pos", "yaw", "hp", "alive", "team", "bot")))


def main():
    test_spawn_and_state()
    test_hitscan_and_zone()
    test_rate_limit()
    test_kill_score_respawn()
    test_victory_and_time()
    test_bots()
    test_cmd_effects()
    test_speed_cap()
    test_snapshot()
    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print("失败项:", FAIL)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
