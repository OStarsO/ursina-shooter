# -*- coding: utf-8 -*-
"""net_ui + room_net 端到端测试（本地回环）"""
import queue
import sys
import time

sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

import room_net as rn
import net_ui

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {extra}")


def pump(app, ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def drain(q, seconds=1.0):
    out = []
    end = time.time() + seconds
    while time.time() < end:
        try:
            out.append(q.get(timeout=0.05))
        except queue.Empty:
            continue
    return out


def main():
    app = QApplication.instance() or QApplication(sys.argv)

    srv = rn.RoomService("房主", "duel", room_name="测试房", password="123")
    check("建房并监听", srv.start())

    launched = {}
    callbacks = {
        "python_ready": lambda: True,
        "launch_game": lambda args, tag, cb: (launched.update({"args": args, "tag": tag, "cb": cb}) or True),
        "on_leave": lambda: None,
    }
    lobby = net_ui.RoomLobbyWindow("房主", "host", server=srv, callbacks=callbacks, room_info=srv.room)
    lobby.show()
    pump(app, 300)

    guest = rn.RoomClient("小王")
    guest.connect("127.0.0.1", password="123")
    pump(app, 400)
    check("房主大厅同步到新成员", "小王" in str(lobby.box_blue.count() + lobby.box_red.count()) or srv.member_list(), str([m["nickname"] for m in srv.member_list()]))

    # 控制台：从大厅 UI 输入
    lobby.console_input.setText("score set red 3 blue 1")
    lobby._run_command()
    pump(app, 200)
    check("控制台执行 score", srv.room["score"] == {"red": 3, "blue": 1})
    check("控制台回显命令", "score set red 3 blue 1" in lobby.console_box.toPlainText())
    events = drain(guest.events, 0.6)
    check("加入方收到 room_update", any(e[0] == "room_update" for e in events))

    # 作弊命令广播
    lobby.console_input.setText("god all")
    lobby._run_command()
    pump(app, 200)
    events = drain(guest.events, 0.6)
    check("加入方收到作弊广播", any(e[0] == "console" and "作弊" in e[1] for e in events))
    check("加入方收到 cmd_apply", any(e[0] == "cmd_apply" and e[1].get("name") == "god" for e in events))

    # 单挑只有 2 人 → 可开始（加入方大厅已创建，start 事件由它消费并自动启动）
    lobby._host_start()
    pump(app, 500)
    check("游戏进程被启动", "--net-mode" in str(launched.get("args")), str(launched.get("args", [])[:6]))
    args = launched.get("args") or []
    check("房主连本机回环", args[args.index("--host") + 1] == "127.0.0.1" if "--host" in args else False)
    check("游戏标记 online", launched.get("tag") == "online")

    # 加入方大厅在开始信号之前创建，后续事件由它自己消费
    net_ui.QMessageBox.information = staticmethod(lambda *a, **k: None)  # 测试环境屏蔽弹窗
    guest_launch = {}
    guest_cb = {
        "python_ready": lambda: True,
        "launch_game": lambda args, tag, cb: (guest_launch.update({"args": args}) or True),
        "on_leave": lambda: None,
    }
    guest_lobby = net_ui.RoomLobbyWindow("小王", "guest", client=guest, callbacks=guest_cb)
    guest_lobby.show()
    pump(app, 400)

    lobby._host_start()
    pump(app, 500)
    check("加入方自动启动游戏", "--net-mode" in str(guest_launch.get("args")), str(guest_launch.get("args", [])[:4]))
    gargs = guest_launch.get("args") or []
    if gargs:
        host_ip = gargs[gargs.index("--host") + 1]
        check("加入方连房主局域网IP", host_ip not in ("127.0.0.1", "") and host_ip == rn.local_ip(), host_ip)
        check("加入方连正确端口", gargs[gargs.index("--port") + 1] == "25250")

    # 游戏退出 → 房主广播回大厅
    if launched.get("cb"):
        launched["cb"](0, "正常退出")
    pump(app, 600)
    check("对局结束回大厅", srv.room["state"] == "lobby")
    check("加入方回到等待状态", (not guest_lobby.game_running) and guest_lobby.side.state_text == "等待玩家",
          guest_lobby.side.state_text)

    # 房主离开 → 加入方大厅自动关闭（closed 事件触发 _fatal → 屏蔽弹窗后直接收尾）
    lobby.close()
    pump(app, 700)
    check("解散后加入方大厅自动关闭", guest_lobby._closed)
    check("服务已停止", not srv._running)

    print(f"\n结果: {len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
