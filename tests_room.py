# -*- coding: utf-8 -*-
"""room_net 协议层自测（本地回环，无需第二台机器）"""
import queue
import sys
import time

sys.path.insert(0, ".")

import room_net as rn

PASS, FAIL = [], []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
        print(f"[PASS] {name} {extra}")
    else:
        FAIL.append(name)
        print(f"[FAIL] {name} {extra}")


def drain(q, seconds=1.0):
    """收集队列里一段时间内的事件"""
    out = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            out.append(q.get(timeout=0.05))
        except queue.Empty:
            continue
    return out


def test_world_sync():
    """权威世界联调：快照下行、cmd_apply 送达、lobby 送达。"""
    from game_net import GameNet

    svc = rn.RoomService("房主", "duel")
    svc.start()
    time.sleep(0.3)
    svc.add_bots("blue", 1, "normal")
    bot = next(m for m in svc.member_list() if m["is_bot"])
    # 直接起世界（start_game 要求 2 名真人，测试里跳过人数校验）
    with svc._lock:
        svc.room["state"] = "playing"
    svc._start_world({"mode": "duel", "score_target": 50, "time_limit": 300})
    time.sleep(0.2)

    gn = GameNet("127.0.0.1", rn.ROOM_PORT, svc.host_member["token"])
    check("游戏通道接入权威世界", gn.start())
    time.sleep(0.6)

    msgs = gn.drain()
    snaps = [m for m in msgs if m.get("t") == "snapshot"]
    check("收到服务端快照", len(snaps) >= 1, f"{len(snaps)} 帧")
    if snaps:
        ents = snaps[-1].get("entities") or []
        ids = {e["id"] for e in ents}
        check("快照含玩家与机器人", svc.host_member["id"] in ids and bot["id"] in ids)
        check("快照含比分/计时",
              "score" in snaps[-1] and "time_left" in snaps[-1])

    # 上行状态 → 快照反映位置
    host_id = svc.host_member["id"]
    base_pos = list(svc.world.entities[host_id]["pos"])
    # 小幅移动（0.6m < 单帧速度上限），验证状态确实进入权威世界
    gn.send_state((base_pos[0] + 0.6, base_pos[1], base_pos[2]), 90, 0, "ak", True)
    time.sleep(0.5)
    snaps = [m for m in gn.drain() if m.get("t") == "snapshot"]
    if snaps:
        me = next((e for e in snaps[-1]["entities"] if e["id"] == host_id), None)
        check("客户端状态进入权威世界",
              me is not None and me["pos"][0] > base_pos[0] + 0.2,
              str(me and me["pos"]))

    # cmd_apply：god all 必须同时到达游戏进程与服务端世界
    svc.execute_command("god all")
    time.sleep(0.4)
    cmds = [m for m in gn.drain() if m.get("t") == "cmd_apply"]
    check("cmd_apply 送达游戏进程", any(m.get("cmd", {}).get("name") == "god" for m in cmds),
          str(cmds[-1:] if cmds else []))
    check("god 同步到服务端世界",
          svc.world is not None and svc.world.entities[host_id]["god"] is True)

    # lobby：结束对局必须送达游戏进程
    svc.end_game("测试结束")
    time.sleep(0.3)
    lobbies = [m for m in gn.drain() if m.get("t") == "lobby"]
    check("lobby 送达游戏进程", bool(lobbies), str(lobbies[-1:] if lobbies else []))
    gn.stop()
    svc.stop()


def main():
    srv = rn.RoomService("房主", "duel", room_name="测试房", password="123", settings={"score_target": 10, "time_limit": 300})
    ok = srv.start()
    check("服务监听 25250", ok)
    if not ok:
        return

    info = rn.query_room("127.0.0.1")
    check("端口探测返回房间信息", bool(info), str(info))
    check("探测信息含密码标记", bool(info and info.get("has_pwd")))
    check("探测信息不含明文密码", "password" not in (info or {}))

    prefixes = rn.subnet_prefixes()
    print("本机网段:", prefixes)
    if prefixes:
        rooms = rn.scan_lan(timeout=0.3)
        hit = [r for r in rooms if r.get("name") == "测试房"]
        check("网段扫描发现房间", bool(hit), f"共 {len(rooms)} 个")

    wrong = rn.RoomClient("路人")
    try:
        wrong.connect("127.0.0.1", password="999")
        check("错误密码被拒", False)
    except rn.RoomError as exc:
        check("错误密码被拒", "密码" in str(exc), str(exc))

    guest = rn.RoomClient("小王")
    resp = guest.connect("127.0.0.1", password="123")
    check("正确密码加入", resp.get("t") == "welcome")
    time.sleep(0.2)
    members = srv.member_list()
    check("房主收到成员同步", len(members) == 2, f"{[m['nickname'] for m in members]}")
    teams = {m["nickname"]: m["team"] for m in members}
    check("房主与加入方分队不同", teams.get("房主") != teams.get("小王"), str(teams))

    third = rn.RoomClient("第三人")
    try:
        third.connect("127.0.0.1", password="123")
        check("单挑满员拒绝第三人", False)
    except rn.RoomError as exc:
        check("单挑满员拒绝第三人", "满员" in str(exc), str(exc))

    ok, text = srv.execute_command("score set red 5 blue 3")
    check("score set 生效", ok and srv.room["score"] == {"red": 5, "blue": 3}, text)
    ok, text = srv.execute_command("score add blue 2")
    check("score add 生效", ok and srv.room["score"]["blue"] == 5, text)
    ok, text = srv.execute_command("score reset")
    check("score reset 生效", ok and srv.room["score"] == {"red": 0, "blue": 0}, text)
    ok, text = srv.execute_command("time 600")
    check("time 设置时长", ok and srv.room["time_limit"] == 600, text)

    ok, text = srv.execute_command("god 小王")
    check("god 指定玩家下发", ok, text)
    events = drain(guest.events, 0.7)
    check("作弊命令全员广播", any(e[0] == "console" and "作弊" in e[1] for e in events), str(events[:4]))
    check("作弊命令下发客户端", any(e[0] == "cmd_apply" and e[1].get("name") == "god" for e in events))

    ok, text = srv.execute_command("god all")
    check("god all 生效", ok, text)
    ok, text = srv.execute_command("speed 小王 2")
    check("speed 生效", ok and srv.room["state"] == "lobby", text)
    ok, text = srv.execute_command("tp 小王 1.5 2.5")
    check("tp 坐标解析", ok, text)
    ok, text = srv.execute_command("ammo inf on")
    check("ammo 生效", ok, text)
    ok, text = srv.execute_command("damage 2")
    check("damage 生效", ok, text)
    ok, text = srv.execute_command("kill 小王")
    check("kill 生效", ok, text)
    ok, text = srv.execute_command("respawn 3")
    check("respawn 生效", ok, text)
    ok, text = srv.execute_command("spawn 3")
    check("未知命令报错", (not ok) and "未知命令" in text, text)
    ok, text = srv.execute_command("god 不存在的人")
    check("目标不存在报错", (not ok) and "找不到" in text, text)
    ok, text = srv.execute_command("help")
    check("help 输出命令列表", ok and "score" in text)
    ok, text = srv.execute_command("status")
    check("status 输出成员", ok and "小王" in text)

    ok, text = srv.execute_command("say 准备开始")
    events = drain(guest.events, 0.6)
    check("say 广播到加入方", any(e[0] == "console" and "准备开始" in e[1] for e in events))

    ok, text = srv.execute_command("lock on")
    check("锁定房间", ok and srv.room["locked"])
    locked_client = rn.RoomClient("第四人")
    try:
        locked_client.connect("127.0.0.1", password="123")
        check("锁定后拒绝加入", False)
    except rn.RoomError as exc:
        check("锁定后拒绝加入", "锁定" in str(exc), str(exc))
    srv.execute_command("lock off")

    ok, text = srv.execute_command("pwd off")
    check("取消密码", ok and srv.room["password"] == "", text)

    game, err = srv.start_game()
    check("开始对局", bool(game) and not err, err)
    check("对局配置含玩家 token", bool(game and all(p.get("token") for p in game["players"])))
    events = drain(guest.events, 0.8)
    started = [e for e in events if e[0] == "start"]
    check("加入方收到开始信号", bool(started))
    args = rn.build_game_args("小王", "blue", "tok", game, False)
    check("启动参数完整", "--net-mode" in args and "--token" in args and json_ok(args))

    ok, text = srv.execute_command("end")
    check("结束对局回大厅", ok and srv.room["state"] == "lobby", text)

    ok, text = srv.execute_command("kick 小王")
    check("踢出玩家", ok, text)
    events = drain(guest.events, 0.8)
    check("被踢方收到通知", any(e[0] == "kicked" for e in events), str([e[0] for e in events]))

    guest2 = rn.RoomClient("小李")
    guest2.connect("127.0.0.1", password="")
    srv.execute_command("ban 小李")
    events = drain(guest2.events, 0.8)
    check("ban 通知被踢", any(e[0] == "kicked" for e in events))
    banned = rn.RoomClient("小李")
    try:
        banned.connect("127.0.0.1", password="")
        check("ban 后无法再进", False)
    except rn.RoomError as exc:
        check("ban 后无法再进", "ban" in str(exc), str(exc))

    guest3 = rn.RoomClient("小赵")
    guest3.connect("127.0.0.1", password="")
    srv.stop()
    events = drain(guest3.events, 1.0)
    check("房主关闭房间通知加入方", any(e[0] == "closed" for e in events), str([e[0] for e in events]))

    time.sleep(0.3)
    check("关闭后端口释放", rn.query_room("127.0.0.1", timeout=0.3) is None)

    # 团队房：机器人与人数上限
    team = rn.RoomService("团房", "team5", password="")
    team.start()
    ok, text = team.execute_command("bot add 红 2")
    check("团队房添加机器人", ok and sum(1 for m in team.member_list() if m["is_bot"]) == 2, text)
    ok, text = team.execute_command("bot add 蓝 9")
    check("机器人受人数上限约束", ok and sum(1 for m in team.member_list() if m["is_bot"]) == 9, text)
    ok, text = team.execute_command("bot add 红 5")
    check("满员后拒绝加机器人", (not ok) or sum(1 for m in team.member_list() if m["is_bot"]) == 9, text)
    team.execute_command("bot clear")
    ok, text = team.execute_command("bot add 蓝 2 困难")
    bots = [m for m in team.member_list() if m["is_bot"]]
    check("机器人带难度字段", ok and all(m.get("difficulty") == "hard" for m in bots), text)
    ok, text = team.execute_command("bot clear")
    check("清空机器人", ok and not any(m["is_bot"] for m in team.member_list()), text)
    team.stop()

    test_anticheat()
    test_world_sync()

    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print("失败项:", FAIL)
        return 1
    return 0


def test_anticheat():
    """服务器端命中声明验证：射速 / 伤害 / 部位 / 存活 / 身份。"""
    import anticheat as AC

    ac = AC.AntiCheat()
    ac.begin_round([1, 2, 3])                     # 1=玩家 2/3=其他
    now = 1000.0

    # 合法命中：AK 命中头部 = 36 × 4 = 144 → 一击击倒
    ok, reason, dmg, kill = ac.claim(1, 2, "ak", "head", now)
    check("AK 爆头伤害权威计算", ok and abs(dmg - 144.0) < 1e-6 and kill, f"dmg={dmg}")
    check("击杀记入战绩", ac.stats_public()["1"]["kills"] == 1
          and ac.stats_public()["2"]["deaths"] == 1)
    check("击倒后进入重生窗口", not ac.is_alive(2, now + 0.1))

    # 鞭尸：重生窗口内的命中被拒绝
    ok, reason, dmg, kill = ac.claim(1, 2, "ak", "body", now + 0.2)
    check("重生窗口内命中被拒", not ok and reason == AC.RejectReason.ALIVE)

    # 重生后恢复
    check("重生完成恢复满血", ac.respawn_done(2, now + 3.5)
          and ac.is_alive(2, now + 3.5))

    # 射速节流：AK 600rpm → 最小间隔 0.1s×0.9；0.05s 内第二发被拒
    ok1, _, _, _ = ac.claim(1, 2, "ak", "body", now + 4.0)
    ok2, reason, _, _ = ac.claim(1, 2, "ak", "body", now + 4.05)
    check("AK 双发节流", ok1 and not ok2 and reason == AC.RejectReason.RATE)
    ok3, _, _, _ = ac.claim(1, 2, "ak", "body", now + 4.2)
    check("间隔足够后放行", ok3)

    # 部位倍率：USP 34 → 肢体 25.5 / 躯干 42.5
    _, _, dmg, _ = ac.claim(2, 1, "usp", "limb", now + 10.0)
    check("USP 肢体倍率", abs(dmg - 25.5) < 1e-6, f"dmg={dmg}")
    _, _, dmg, _ = ac.claim(2, 1, "usp", "body", now + 10.3)
    check("USP 躯干倍率", abs(dmg - 42.5) < 1e-6, f"dmg={dmg}")

    # 非法输入：未知武器 / 非法部位 / 自伤 / 伪造身份
    ok, reason, _, _ = ac.claim(1, 2, "railgun", "body", now + 20.0)
    check("未知武器被拒", not ok and reason == AC.RejectReason.WEAPON)
    ok, reason, _, _ = ac.claim(1, 2, "ak", "toe", now + 20.0)
    check("非法部位被拒", not ok and reason == AC.RejectReason.ZONE)
    ok, reason, _, _ = ac.claim(1, 1, "ak", "body", now + 20.0)
    check("自伤被拒", not ok and reason == AC.RejectReason.SELF)

    # 房主代报人机命中：attack 指向 bot 成员 id，reporter 为房主本人
    # （身份约束由 RoomService 连接层校验，anticheat 只管数值规则）
    svc = rn.RoomService("房主", "duel")
    svc.add_bots("blue", 1, "hard")
    bot = next(m for m in svc.member_list() if m["is_bot"])
    host = svc.host_member
    svc.anticheat.begin_round(list(svc.members.keys()))
    ok, reason, dmg, kill = svc.anticheat.claim(
        bot["id"], host["id"], "ak", "body", now + 30.0, reporter_id=host["id"])
    check("房主代报人机命中放行", ok and abs(dmg - 45.0) < 1e-6, f"dmg={dmg}")
    # 人机射速同样受节流（0.05s 后的第二发）
    ok, reason, _, _ = svc.anticheat.claim(
        bot["id"], host["id"], "ak", "body", now + 30.05, reporter_id=host["id"])
    check("人机射速同样受节流", not ok and reason == AC.RejectReason.RATE)
    # 伪造身份（连接层）：非房主、非本人、也非人机的 attacker 被拒
    thief = svc._add_member("贼", "red")
    stats_before = svc.anticheat.stats_public()[str(host["id"])]["score"]
    svc._handle_hit_claim(host, {"t": "hit_claim", "attacker": thief["id"],
                                 "target": bot["id"], "weapon": "ak", "zone": "body"})
    check("伪造身份被连接层拒绝",
          svc.anticheat.stats_public()[str(host["id"])]["score"] == stats_before
          and svc.anticheat.stats_public().get(str(thief["id"]), {}).get("score", 0) == 0)
    svc.stop()

    print(f"\n[anticheat] 小计: {len(PASS)} 项通过")


def json_ok(args):
    import json
    idx = args.index("--players-json")
    try:
        json.loads(args[idx + 1])
        return True
    except (ValueError, IndexError):
        return False


if __name__ == "__main__":
    sys.exit(main())
