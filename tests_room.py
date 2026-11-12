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
    ok, text = team.execute_command("bot clear")
    check("清空机器人", ok and not any(m["is_bot"] for m in team.member_list()), text)
    team.stop()

    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    if FAIL:
        print("失败项:", FAIL)
        return 1
    return 0


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
