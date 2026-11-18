# -*- coding: utf-8 -*-
"""游戏进程 ↔ 房间服务器（权威世界）的实时通道。

上行（客户端 → 服务端）
    {"t":"state","pos":[x,y,z],"yaw":..,"pitch":..,"weapon":"ak","alive":true}
        20Hz 节流（send_state 内部保证最小间隔 50ms）
    {"t":"fire","origin":[x,y,z],"dir":[x,y,z]}
        每次开火一条；命中/伤害/死亡全部由服务端弹道计算
    {"t":"respawn_done"}  本机重生完成（兼容旧协议）

下行（服务端 → 客户端）
    {"t":"snapshot", ...}   15Hz 权威快照：实体、血量、比分、事件、结算
    {"t":"result", ...}     回合结算
    {"t":"cmd_apply", ...}  房主作弊指令（god/speed/damage/ammo_inf/kill/tp/respawn）
    {"t":"start"/"lobby"/"closed"}

线程模型：socket 收在后台线程 → inbox 队列；主线程每帧 drain，不阻塞渲染。
断线静默降级（本地练习继续），不影响单机。
"""

import json
import queue
import socket
import threading
import time

import room_net as RN

STATE_INTERVAL = 0.05      # 20Hz


class GameNet:
    def __init__(self, host, port, token):
        self.host = host
        self.port = port
        self.token = token
        self.inbox = queue.Queue()
        self.score_queue = self.inbox          # 兼容旧调用名
        self._sock = None
        self._run = False
        self._last_state = 0.0

    # ---------------- 连接 ----------------
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

    def send_state(self, pos, yaw, pitch, weapon, alive, firing=False):
        """20Hz 节流上送自身状态（内部限流，调用方可以每帧调）。"""
        now = time.time()
        if now - self._last_state < STATE_INTERVAL:
            return
        self._last_state = now
        self._send({
            "t": "state",
            "pos": [round(float(pos[0]), 2), round(float(pos[1]), 2),
                    round(float(pos[2]), 2)],
            "yaw": round(float(yaw), 1), "pitch": round(float(pitch), 1),
            "weapon": weapon, "alive": bool(alive), "firing": bool(firing),
        })

    def send_fire(self, origin, direction):
        self._send({"t": "fire",
                    "origin": [round(float(v), 2) for v in origin],
                    "dir": [round(float(v), 4) for v in direction]})

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
                self.inbox.put(msg)
                if kind in ("lobby", "closed"):
                    break
        except (OSError, ValueError):
            pass
        self._run = False

    # ---------------- 便捷读取 ----------------
    def drain(self, limit=200):
        out = []
        for _ in range(limit):
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                break
        return out
