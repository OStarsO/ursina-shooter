# -*- coding: utf-8 -*-
"""游戏进程 ↔ 房间服务器的轻量实时通道。

对局期间游戏进程通过 game_hello(token) 接入房主的 25250 服务：
  上行：
    {"t":"hit_claim","attacker","target","weapon","zone"}
        —— 玩家击倒人机 / 人机击中玩家的命中声明（服务器按 anticheat
           规则验证后才计入权威比分；本地模式无服务器时不发送）
    {"t":"respawn_done"}   本机重生完成
  下行：
    {"t":"score_update", ...}   权威战绩（写回 score_queue 供主线程消费）
    {"t":"claim_reject","reason"}  被拒绝的声明（显示给玩家）

线程模型：socket 收发在后台线程，主线程通过 score_queue 轮询取事件，
不阻塞 ursina 渲染循环。断线自动静默（本地练习不受影响）。
"""

import json
import queue
import socket
import threading

import room_net as RN


class GameNet:
    """对局内与房间服务器的连接（每次对局一个实例）。"""

    def __init__(self, host, port, token):
        self.host = host
        self.port = port
        self.token = token
        self.score_queue = queue.Queue()
        self._sock = None
        self._run = False

    def start(self):
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=4.0)
        except OSError as exc:
            print('[联机] 游戏通道连接失败（本地继续）:', exc)
            return False
        self._run = True
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def stop(self):
        self._run = False
        try:
            self._sock.close()
        except (OSError, AttributeError):
            pass

    # ---------------- 上行 ----------------

    def _send(self, obj):
        if not self._run or self._sock is None:
            return
        try:
            RN.send_msg(self._sock, obj)
        except OSError:
            self._run = False

    def hit_claim(self, attacker_id, target_id, weapon, zone):
        """上报一条命中声明（服务器验证后才计分）。"""
        self._send({"t": "hit_claim", "attacker": int(attacker_id),
                    "target": int(target_id), "weapon": weapon, "zone": zone})

    def respawn_done(self):
        self._send({"t": "respawn_done"})

    # ---------------- 下行 ----------------

    def _loop(self):
        try:
            self._sock.settimeout(None)
            RN.send_msg(self._sock, {"t": "game_hello", "token": self.token})
            reader = self._sock.makefile("r", encoding="utf-8", errors="replace")
            first = reader.readline()
            if not first or json.loads(first).get("t") != "game_welcome":
                self._run = False
                return
            for raw in reader:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("t")
                if kind in ("score_update", "claim_reject", "lobby", "closed"):
                    self.score_queue.put(msg)
                if kind in ("lobby", "closed"):
                    break
        except (OSError, ValueError):
            pass
        self._run = False
