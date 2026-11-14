# -*- coding: utf-8 -*-
"""射击 · 局域网房间服务（纯标准库，无 Qt 依赖）

角色模型：
  房主：启动器进程内运行 RoomService，监听 TCP 25250；
        本机游戏进程（127.0.0.1:25250）与各加入方游戏进程都连接该服务。
  加入方：RoomClient 主动连接 房主IP:25250，自身不监听任何端口。

协议：UTF-8 编码、按行分隔的 JSON 消息（每条消息一行，以 \\n 结尾）。

消息类型：
  客户端 → 服务端
    {"t":"query"}                       扫描探测，返回房间公开信息后断开
    {"t":"hello","nickname","password"} 加入房间
    {"t":"leave"}                       主动离开
    {"t":"game_hello","token"}          游戏进程接入（下一轮联机逻辑使用）
    {"t":"hit_claim","attacker","target","weapon","zone"}
                                        命中声明（游戏内上报，服务器按
                                        anticheat 规则验证后才计入比分）
    {"t":"respawn_done"}                本机玩家/人机重生完成
  服务端 → 客户端
    {"t":"info","room":{...}}           房间公开信息（响应 query）
    {"t":"welcome","room","you","members"} / {"t":"reject","reason"}
    {"t":"members","members":[...]}     成员列表变更
    {"t":"room_update","room":{...}}    房间设置变更（密码/锁定/时长等）
    {"t":"console","text"}              控制台广播（含作弊命令提示，始终全员可见）
    {"t":"cmd_apply","cmd":{...}}       命令下发（游戏进程下一轮接入后生效）
    {"t":"score_update","stats":{...}}  权威比分（服务器验证后的战绩）
    {"t":"claim_reject","reason"}       被拒绝的命中声明（回执给上报方）
    {"t":"start","game":{...}}          开始对局
    {"t":"lobby","reason"}              对局结束回到大厅
    {"t":"kicked","reason"} / {"t":"closed","reason"}
"""

import ipaddress
import itertools
import json
import queue
import secrets
import shlex
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anticheat as AC

ROOM_PORT = 25250
PROTO_VERSION = 1
HANDSHAKE_TIMEOUT = 10.0

MODES = {
    "duel": {"label": "单挑 1v1", "max_players": 2, "team_size": 1},
    "team5": {"label": "团队竞技 5v5", "max_players": 10, "team_size": 5},
    "team10": {"label": "团队竞技 10v10", "max_players": 20, "team_size": 10},
}

MODE_ORDER = ["duel", "team5", "team10"]


class RoomError(Exception):
    """房间操作失败（reason 面向用户展示）"""


def send_msg(sock, obj):
    sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def local_ips():
    """取本机所有 IPv4 地址（不实际发包）"""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 1))  # 路由表探测，标准做法，不会发包
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def local_ip():
    ips = [ip for ip in local_ips() if not ip.startswith("169.254.")]
    return ips[0] if ips else "127.0.0.1"


def subnet_prefixes():
    """本机所在网段（/24）的网络地址列表"""
    out = set()
    for ip in local_ips():
        try:
            net = ipaddress.ip_network(ip + "/24", strict=False)
            out.add(str(net.network_address))
        except ValueError:
            continue
    return sorted(out)


def query_room(ip, timeout=0.8):
    """探测某个 IP 的 25250 端口是否为射击房间，返回公开信息或 None"""
    try:
        s = socket.create_connection((ip, ROOM_PORT), timeout=timeout)
        s.settimeout(timeout)
        send_msg(s, {"t": "query"})
        reader = s.makefile("r", encoding="utf-8", errors="replace")
        line = reader.readline()
        s.close()
        if line:
            msg = json.loads(line)
            if msg.get("t") == "info":
                info = msg.get("room", {})
                info["ip"] = ip
                return info
    except (OSError, ValueError):
        pass
    return None


def scan_lan(timeout=0.5, progress=None):
    """扫描本网段所有 IP 的 25250 端口，返回房间公开信息列表

    先探测本机地址（同机开房时最可靠），再并发扫描各网段；
    并发度控制在 48，避免瞬间大量连接打满对端监听队列。
    """
    own_ips = [ip for ip in local_ips() if not ip.startswith("169.254.")]
    results = []
    seen = set()
    for ip in own_ips:
        info = query_room(ip, timeout=max(timeout, 0.8))
        if info and ip not in seen:
            seen.add(ip)
            results.append(info)
        if progress:
            progress(ip)

    targets = []
    for prefix in subnet_prefixes():
        for i in range(1, 255):
            ip = f"{prefix}.{i}"
            if ip in own_ips:
                continue
            targets.append(ip)
    if not targets:
        return results
    lock = threading.Lock()

    def probe(ip):
        info = query_room(ip, timeout=timeout)
        if info:
            with lock:
                if ip not in seen:
                    seen.add(ip)
                    results.append(info)
        if progress:
            progress(ip)

    with ThreadPoolExecutor(max_workers=48) as ex:
        list(ex.map(probe, targets))
    return results


# ============================ 房间服务（房主端） ============================

class RoomService:
    """房主启动器内运行的房间服务：监听 25250，管理成员/对局/控制台命令。

    与 UI 的交互通过 events 队列（UI 用 QTimer 轮询取走）：
      ("started", None) / ("error", text)
      ("member_joined", member) / ("member_left", nickname)
      ("console", text)          控制台广播（本机也要显示）
      ("game_started", game)     房主自己也收到开始信号
      ("game_ended", reason) / ("closed", reason)
    """

    def __init__(self, nickname, mode, room_name=None, password="", settings=None):
        spec = MODES.get(mode, MODES["duel"])
        settings = settings or {}
        self.room = {
            "name": room_name or f"{nickname}的房间",
            "mode": mode,
            "mode_label": spec["label"],
            "max_players": spec["max_players"],
            "team_size": spec["team_size"],
            "password": password or "",
            "locked": False,
            "state": "lobby",
            "score": {"red": 0, "blue": 0},
            "score_target": max(0, int(settings.get("score_target", 0) or 0)),
            "time_limit": max(0, int(settings.get("time_limit", 0) or 0)),
            "proto": PROTO_VERSION,
        }
        self.host_nick = nickname
        self.members = {}
        self.events = queue.Queue()
        self._conns = {}        # member_id -> socket（大厅连接）
        self._game_conns = {}   # member_id -> socket（游戏进程连接，下一轮使用）
        self._banned = set()
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self._sock = None
        self._running = False
        self._listen_thread = None
        self.host_member = self._add_member(nickname, "red", host=True, addr="127.0.0.1")
        self.anticheat = AC.AntiCheat()      # 服务器端命中验证（对局期使用）

    # ---------- 生命周期 ----------

    def start(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("", ROOM_PORT))
            self._sock.listen(64)
        except OSError as exc:
            self.events.put(("error", f"监听端口 {ROOM_PORT} 失败：{exc}"))
            return False
        self._running = True
        self._listen_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._listen_thread.start()
        self.events.put(("started", None))
        return True

    def stop(self, reason="房主关闭了房间"):
        if not self._running:
            return
        self._running = False
        with self._lock:
            conns = list(self._conns.values()) + list(self._game_conns.values())
            self._conns.clear()
            self._game_conns.clear()
        for conn in conns:
            try:
                send_msg(conn, {"t": "closed", "reason": reason})
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        try:
            self._sock.close()
        except OSError:
            pass
        self.events.put(("closed", reason))

    # ---------- 连接处理 ----------

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn, addr), daemon=True).start()

    def _handle_conn(self, conn, addr):
        conn.settimeout(HANDSHAKE_TIMEOUT)
        try:
            reader = conn.makefile("r", encoding="utf-8", errors="replace")
            line = reader.readline()
            if not line:
                conn.close()
                return
            try:
                msg = json.loads(line)
            except ValueError:
                conn.close()
                return
            kind = msg.get("t")
            if kind == "query":
                send_msg(conn, {"t": "info", "room": self.public_room()})
                conn.close()
            elif kind == "hello":
                self._join(conn, reader, msg, addr)
            elif kind == "game_hello":
                self._attach_game(conn, reader, msg, addr)
            else:
                conn.close()
        except (OSError, ValueError):
            try:
                conn.close()
            except OSError:
                pass

    def _join(self, conn, reader, msg, addr):
        nickname = str(msg.get("nickname", "")).strip()[:16] or "玩家"
        password = str(msg.get("password", ""))
        with self._lock:
            if nickname in self._banned:
                reason = "你已被本房间 ban"
            elif self.room["locked"]:
                reason = "房间已锁定"
            elif self._human_count() >= self.room["max_players"]:
                reason = "房间已满员"
            elif self.room["password"] and password != self.room["password"]:
                reason = "密码错误"
            else:
                reason = ""
            if reason:
                try:
                    send_msg(conn, {"t": "reject", "reason": reason})
                    conn.close()
                except OSError:
                    pass
                return
            team = self._balanced_team()
            member = self._add_member(nickname, team, addr=addr[0])
            self._conns[member["id"]] = conn
        conn.settimeout(None)
        try:
            send_msg(conn, {
                "t": "welcome",
                "room": self.public_room(),
                "you": self._member_public(member),
                "members": self.member_list(),
            })
        except OSError:
            self._drop_member(member["id"], "连接失败")
            return
        self.broadcast({"t": "members", "members": self.member_list()})
        self.events.put(("member_joined", self._member_public(member)))

        # 大厅消息循环：目前只有 leave / 轻量控制
        try:
            for raw in reader:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                if data.get("t") == "leave":
                    break
        except (OSError, ValueError):
            pass
        self._drop_member(member["id"], "离开")

    def _attach_game(self, conn, reader, msg, addr):
        token = str(msg.get("token", ""))
        with self._lock:
            member = None
            for m in self.members.values():
                if m["token"] == token:
                    member = m
                    break
            if member is None:
                try:
                    send_msg(conn, {"t": "reject", "reason": "无效 token"})
                    conn.close()
                except OSError:
                    pass
                return
            self._game_conns[member["id"]] = conn
            member["in_game"] = True
        conn.settimeout(None)
        try:
            send_msg(conn, {"t": "game_welcome"})
        except OSError:
            return
        self.broadcast({"t": "members", "members": self.member_list()})
        try:
            for raw in reader:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue
                kind = data.get("t")
                if kind == "hit_claim":
                    self._handle_hit_claim(member, data)
                elif kind == "respawn_done":
                    now = time.time()
                    self.anticheat.respawn_done(member["id"], now)
                elif kind == "leave":
                    break
        except (OSError, ValueError):
            pass
        with self._lock:
            if member["id"] in self._game_conns:
                del self._game_conns[member["id"]]
            member["in_game"] = False
        try:
            conn.close()
        except OSError:
            pass

    def _drop_member(self, member_id, why):
        with self._lock:
            member = self.members.pop(member_id, None)
            conn = self._conns.pop(member_id, None)
            self._game_conns.pop(member_id, None)
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if member is not None:
            self.broadcast({"t": "members", "members": self.member_list()})
            self.events.put(("member_left", member["nickname"]))

    # ---------- 成员管理 ----------

    def _add_member(self, nickname, team, host=False, bot=False, addr=""):
        member = {
            "id": next(self._ids),
            "nickname": nickname,
            "team": team,
            "is_host": host,
            "is_bot": bot,
            "in_game": False,
            "addr": addr,
            "token": secrets.token_hex(16),
        }
        self.members[member["id"]] = member
        return member

    def _human_count(self):
        return sum(1 for m in self.members.values() if not m["is_bot"])

    def _balanced_team(self):
        red = sum(1 for m in self.members.values() if not m["is_bot"] and m["team"] == "red")
        blue = sum(1 for m in self.members.values() if not m["is_bot"] and m["team"] == "blue")
        return "blue" if red > blue else "red"

    @staticmethod
    def _member_public(member):
        pub = {k: member[k] for k in ("id", "nickname", "team", "is_host", "is_bot", "in_game")}
        if member.get("is_bot") and member.get("difficulty"):
            pub["difficulty"] = member["difficulty"]
        return pub

    def member_list(self):
        with self._lock:
            return [self._member_public(m) for m in self.members.values()]

    def public_room(self):
        with self._lock:
            room = {k: v for k, v in self.room.items() if k != "password"}
            room["has_pwd"] = bool(self.room["password"])
            room["players"] = self._human_count()
            return room

    # ---------- 广播 ----------

    def broadcast(self, obj, to_game=False):
        with self._lock:
            conns = list(self._conns.values())
            if to_game:
                conns += list(self._game_conns.values())
        for conn in conns:
            try:
                send_msg(conn, obj)
            except OSError:
                pass

    def _console_broadcast(self, text):
        self.broadcast({"t": "console", "text": text})
        self.events.put(("console", text))

    # ---------- 对局控制 ----------

    def start_game(self):
        """房主点击开始：广播 start，返回 (game 配置, 错误信息)"""
        with self._lock:
            if self.room["state"] != "lobby":
                return None, "对局已在进行中"
            humans = [m for m in self.members.values() if not m["is_bot"]]
            if len(humans) < 2:
                return None, f"至少需要 2 名玩家（当前 {len(humans)} 人）"
            self.room["state"] = "playing"
            # 服务器端验证器：以全体成员（含人机）初始化血量与战绩
            self.anticheat.begin_round(list(self.members.keys()))
            game = {
                "mode": self.room["mode"],
                "mode_label": self.room["mode_label"],
                "team_size": self.room["team_size"],
                "score": dict(self.room["score"]),
                "score_target": self.room["score_target"],
                "time_limit": self.room["time_limit"],
                "room_name": self.room["name"],
                "host_ip": local_ip(),
                "port": ROOM_PORT,
                "players": [dict(self._member_public(m), token=m["token"]) for m in self.members.values()],
                "started_at": time.time(),
            }
        self.broadcast({"t": "start", "game": game}, to_game=False)
        self.events.put(("game_started", game))
        return game, ""

    def end_game(self, reason="对局结束"):
        with self._lock:
            if self.room["state"] == "lobby":
                return False
            self.room["state"] = "lobby"
            for m in self.members.values():
                m["in_game"] = False
        self.broadcast({"t": "lobby", "reason": reason})
        self.events.put(("game_ended", reason))
        return True

    # ============================ 命中声明验证 ============================

    def _handle_hit_claim(self, reporter, data):
        """游戏进程上报一条命中 → 服务器按 anticheat 规则验证 → 广播权威比分。

        reporter:       发消息连接对应的成员（玩家本人，或房主代报人机）
        data.attacker:  实际造成伤害的成员 id（人机由房主连接代报）
        data.target / data.weapon / data.zone
        """
        now = time.time()
        try:
            attacker = int(data.get("attacker", reporter["id"]))
            target = int(data.get("target", 0))
            weapon = str(data.get("weapon", ""))
            zone = str(data.get("zone", ""))
        except (TypeError, ValueError):
            return
        # 身份约束：
        #   - 玩家只能以自己的身份上报（attacker == reporter）；
        #   - 人机（bot 无连接）的声明由房主连接代报，或由"被打的那个人"
        #     上报自己受到的人机伤害（target == reporter）。
        if attacker != reporter["id"]:
            bot = self.members.get(attacker)
            if bot is None or not bot.get("is_bot"):
                self._send_claim_reject(reporter["id"], AC.RejectReason.IDENTITY)
                return
            if not (reporter.get("is_host") or target == reporter["id"]):
                self._send_claim_reject(reporter["id"], AC.RejectReason.IDENTITY)
                return

        accepted, reason, damage, kill = self.anticheat.claim(
            attacker, target, weapon, zone, now, reporter_id=reporter["id"])
        if not accepted:
            self._send_claim_reject(reporter["id"], reason)
            return
        # 权威比分广播给所有游戏进程 + 大厅
        self.broadcast({
            "t": "score_update",
            "stats": self.anticheat.stats_public(),
            "kill": kill,
            "attacker": attacker,
            "target": target,
            "damage": round(damage, 1),
        }, to_game=True)

    def _send_claim_reject(self, member_id, reason):
        conn = self._game_conns.get(member_id) or self._conns.get(member_id)
        if conn is not None:
            try:
                send_msg(conn, {"t": "claim_reject", "reason": reason})
            except OSError:
                pass

    # ---------- 房间设置（供 UI 直接调用） ----------

    def set_locked(self, value):
        with self._lock:
            self.room["locked"] = bool(value)
        self.broadcast({"t": "room_update", "room": self.public_room()})

    def set_password(self, password):
        with self._lock:
            self.room["password"] = password or ""
        self.broadcast({"t": "room_update", "room": self.public_room()})

    # ============================ 控制台命令 ============================

    def execute_command(self, line):
        """解析并执行控制台命令，返回 (ok, 回显文本)。作弊命令始终全员广播。"""
        line = (line or "").strip()
        if not line:
            return True, ""
        try:
            parts = shlex.split(line)
        except ValueError:
            return False, "命令解析失败：引号不匹配"
        cmd = parts[0].lower()
        args = parts[1:]
        table = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "score": self._cmd_score,
            "time": self._cmd_time,
            "end": self._cmd_end,
            "restart": self._cmd_restart,
            "god": self._cmd_cheat,
            "speed": self._cmd_cheat,
            "damage": self._cmd_cheat,
            "ammo": self._cmd_cheat,
            "kill": self._cmd_cheat,
            "tp": self._cmd_cheat,
            "respawn": self._cmd_cheat,
            "bot": self._cmd_bot,
            "kick": self._cmd_kick,
            "ban": self._cmd_ban,
            "lock": self._cmd_lock,
            "pwd": self._cmd_pwd,
            "say": self._cmd_say,
        }
        handler = table.get(cmd)
        if handler is None:
            return False, f"未知命令：{cmd}（输入 help 查看命令列表）"
        try:
            return handler(cmd, args)
        except Exception as exc:  # noqa: BLE001
            return False, f"命令执行出错：{exc}"

    # ---- 帮助/状态 ----

    def _cmd_help(self, cmd, args):
        if args:
            return True, f"帮助：{args[0]} —— 详见启动器文档（help 查看全部命令）"
        return True, (
            "命令列表：score set/add/reset · time <秒> · end · restart · "
            "god/speed/damage/ammo/kill/tp/respawn <玩家|all> [参数] · "
            "bot add <红|蓝> <n> [简单/普通/困难] / bot clear · kick/ban <玩家> · "
            "lock on|off · pwd <新密码|off> · say <消息> · status"
        )

    def _cmd_status(self, cmd, args):
        room = self.public_room()
        lines = [
            f"房间：{room['name']}（{room['mode_label']}）",
            f"人数：{room['players']}/{room['max_players']}  状态：{'对战中' if room['state'] == 'playing' else '大厅'}",
            f"比分：红 {room['score']['red']} : {room['score']['blue']} 蓝"
            + (f"（目标 {room['score_target']}）" if room['score_target'] else ""),
            f"时长：{room['time_limit'] // 60} 分钟" if room["time_limit"] else "时长：无限时",
            "玩家：",
        ]
        for m in self.member_list():
            tag = []
            if m["is_host"]:
                tag.append("房主")
            if m["is_bot"]:
                tag.append("机器人")
            if m["in_game"]:
                tag.append("对战中")
            extra = "（" + "·".join(tag) + "）" if tag else ""
            lines.append(f"  [{m['team']}] {m['nickname']}{extra}")
        return True, "\n".join(lines)

    # ---- 比赛控制 ----

    def _cmd_score(self, cmd, args):
        if not args:
            return False, "用法：score set red <n> blue <n> | score add <red|blue> <n> | score reset"
        sub = args[0].lower()
        with self._lock:
            if sub == "reset":
                self.room["score"] = {"red": 0, "blue": 0}
                self.broadcast({"t": "room_update", "room": self.public_room()})
                return True, "比分已清零"
            if sub == "add" and len(args) >= 3 and args[1].lower() in ("red", "blue", "红", "蓝"):
                team = "red" if args[1].lower() in ("red", "红") else "blue"
                try:
                    delta = int(args[2])
                except ValueError:
                    return False, "分数必须是整数"
                self.room["score"][team] = max(0, self.room["score"][team] + delta)
                self.broadcast({"t": "room_update", "room": self.public_room()})
                return True, f"{team} +{delta}，当前比分 红 {self.room['score']['red']} : {self.room['score']['blue']} 蓝"
            if sub == "set":
                pairs = {}
                i = 1
                while i < len(args):
                    key = args[i].lower()
                    if key in ("red", "红", "blue", "蓝"):
                        if i + 1 >= len(args):
                            return False, "用法：score set red <n> blue <n>"
                        try:
                            val = max(0, int(args[i + 1]))
                        except ValueError:
                            return False, f"分数必须是整数：{args[i + 1]}"
                        pairs["red" if key in ("red", "红") else "blue"] = val
                        i += 2
                    else:
                        return False, "用法：score set red <n> blue <n>"
                if not pairs:
                    return False, "用法：score set red <n> blue <n>"
                self.room["score"].update(pairs)
                self.broadcast({"t": "room_update", "room": self.public_room()})
                return True, f"比分已设置：红 {self.room['score']['red']} : {self.room['score']['blue']} 蓝"
        return False, "无法识别的 score 子命令"

    def _cmd_time(self, cmd, args):
        if not args:
            return False, "用法：time <秒>（0 = 无限时）"
        try:
            seconds = max(0, int(args[0]))
        except ValueError:
            return False, "时长必须是整数秒"
        with self._lock:
            self.room["time_limit"] = seconds
            self.broadcast({"t": "room_update", "room": self.public_room()})
        minutes = seconds // 60 if seconds else 0
        if seconds:
            return True, f"比赛时长已设为 {minutes} 分钟"
        return True, "已设为无限时"

    def _cmd_end(self, cmd, args):
        ok = self.end_game("房主结束了对局")
        return (True, "对局已结束，全员回到大厅") if ok else (False, "当前没有进行中的对局")

    def _cmd_restart(self, cmd, args):
        if self.room["state"] != "lobby":
            self.end_game("重开一局")
        with self._lock:
            self.room["score"] = {"red": 0, "blue": 0}
            self.broadcast({"t": "room_update", "room": self.public_room()})
        self._console_broadcast("[系统] 房主重开了这一局，比分已清零")
        return True, "已重开（全员比分清零）"

    # ---- 玩家作弊（始终全员广播） ----

    def _resolve_targets(self, spec):
        """玩家名前缀匹配，返回 (昵称列表, 错误)"""
        if not spec:
            return None, "缺少目标玩家"
        if spec.lower() in ("all", "全员", "所有人"):
            return [m["nickname"] for m in self.member_list()], ""
        matches = [m["nickname"] for m in self.member_list()
                   if m["nickname"].lower().startswith(spec.lower())]
        if not matches:
            return None, f"找不到玩家：{spec}"
        if len(matches) > 1:
            return None, f"匹配到多个玩家（{'、'.join(matches)}），请输入更长前缀"
        return matches, ""

    def _cmd_cheat(self, cmd, args):
        # 无目标类：ammo / damage / respawn
        if cmd == "ammo":
            if len(args) < 2 or args[0].lower() != "inf" or args[1].lower() not in ("on", "off"):
                return False, "用法：ammo inf on|off"
            enabled = args[1].lower() == "on"
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "ammo_inf", "value": enabled}})
            self._console_broadcast(f"[系统] 房主使用了作弊：无限弹药 {'开' if enabled else '关'}（全员）")
            return True, f"无限弹药已{'开启' if enabled else '关闭'}"

        if cmd == "damage":
            if not args:
                return False, "用法：damage <倍数>（影响所有人）"
            try:
                mult = float(args[0])
            except ValueError:
                return False, "倍数必须是数字"
            if not 0.1 <= mult <= 10:
                return False, "倍数范围 0.1 – 10"
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "damage", "value": mult}})
            self._console_broadcast(f"[系统] 房主使用了作弊：全场伤害倍数 → ×{mult:g}")
            return True, f"全场伤害倍数 ×{mult:g}"

        if cmd == "respawn":
            if not args:
                return False, "用法：respawn <秒>"
            try:
                sec = max(0, int(args[0]))
            except ValueError:
                return False, "秒数必须是整数"
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "respawn", "value": sec}})
            self._console_broadcast(f"[系统] 房主使用了作弊：重生时间 → {sec} 秒")
            return True, f"重生时间 {sec} 秒"

        # 目标类：god / speed / kill / tp
        if not args:
            usage = {"god": "god <玩家|all> | god off",
                     "speed": "speed <玩家|all> <倍数 0.5-5>",
                     "kill": "kill <玩家>",
                     "tp": "tp <玩家> <x> <z>"}.get(cmd, f"{cmd} <玩家|all>")
            return False, f"用法：{usage}"

        if cmd == "god" and args[0].lower() in ("off", "关"):
            names = [m["nickname"] for m in self.member_list()]
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "god", "target": names, "value": False}})
            self._console_broadcast("[系统] 房主关闭了无敌（全员）")
            return True, "已关闭无敌"

        names, err = self._resolve_targets(args[0])
        if err:
            return False, err
        who = "、".join(names)

        if cmd == "speed":
            if len(args) < 2:
                return False, "用法：speed <玩家|all> <倍数 0.5-5>"
            try:
                mult = float(args[1])
            except ValueError:
                return False, "倍数必须是数字"
            if not 0.5 <= mult <= 5:
                return False, "倍数范围 0.5 – 5"
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "speed", "target": names, "value": mult}})
            self._console_broadcast(f"[系统] 房主使用了作弊：speed ×{mult:g}（对象：{who}）")
            return True, f"已下发 speed ×{mult:g} → {who}"

        if cmd == "tp":
            if len(args) < 3:
                return False, "用法：tp <玩家> <x> <z>"
            try:
                x, z = float(args[1]), float(args[2])
            except ValueError:
                return False, "坐标必须是数字"
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "tp", "target": names, "x": x, "z": z}})
            self._console_broadcast(f"[系统] 房主传送了 {who} 到 ({x:g}, {z:g})")
            return True, f"已传送 {who}"

        if cmd == "kill":
            self.broadcast({"t": "cmd_apply", "cmd": {"name": "kill", "target": names}})
            self._console_broadcast(f"[系统] 房主秒杀了 {who}")
            return True, f"已秒杀 {who}"

        # god on
        self.broadcast({"t": "cmd_apply", "cmd": {"name": "god", "target": names, "value": True}})
        self._console_broadcast(f"[系统] 房主使用了作弊：无敌（对象：{who}）")
        return True, f"已下发无敌 → {who}"

    # ---- 机器人 ----

    def add_bots(self, team, count, difficulty="normal"):
        """UI 直接调用：为指定队伍添加 n 个指定难度的人机。"""
        if difficulty not in ("easy", "normal", "hard"):
            difficulty = "normal"
        with self._lock:
            used = sum(1 for m in self.members.values() if m["is_bot"])
            capacity = self.room["max_players"] - self._human_count() - used
            count = min(max(0, count), max(0, capacity))
            for i in range(count):
                bot_id = 900000 + len(self.members)
                self.members[bot_id] = {
                    "id": bot_id,
                    "nickname": f"BOT-{team.upper()[:1]}{i + 1 + used}",
                    "team": team,
                    "is_host": False,
                    "is_bot": True,
                    "in_game": False,
                    "addr": "",
                    "token": "",
                    "difficulty": difficulty,
                }
        self.broadcast({"t": "members", "members": self.member_list()})
        return count

    def clear_bots(self):
        with self._lock:
            for mid in [i for i, m in self.members.items() if m["is_bot"]]:
                del self.members[mid]
        self.broadcast({"t": "members", "members": self.member_list()})

    def _cmd_bot(self, cmd, args):
        if not args:
            return False, "用法：bot add <红|蓝> <n> [简单|普通|困难] | bot clear"
        sub = args[0].lower()
        if sub == "clear":
            self.clear_bots()
            return True, "机器人已清空"
        if sub == "add" and len(args) >= 3:
            team = "red" if args[1] in ("红", "red") else "blue" if args[1] in ("蓝", "blue") else None
            if team is None:
                return False, "队伍请用 红/蓝（red/blue）"
            try:
                count = max(1, min(20, int(args[2])))
            except ValueError:
                return False, "数量必须是整数"
            difficulty = "normal"
            if len(args) >= 4:
                diff_map = {"简单": "easy", "普通": "normal", "困难": "hard",
                            "easy": "easy", "normal": "normal", "hard": "hard"}
                difficulty = diff_map.get(args[3].lower(), "normal")
            added = self.add_bots(team, count, difficulty)
            if added <= 0:
                return False, "房间已满，无法再添加机器人"
            label = {"easy": "简单", "normal": "普通", "hard": "困难"}[difficulty]
            return True, f"已为 {'红' if team == 'red' else '蓝'}队 添加 {added} 个机器人（难度：{label}）"
        return False, "用法：bot add <红|蓝> <n> [简单|普通|困难] | bot clear"

    # ---- 房间管理 ----

    def _kick_or_ban(self, nickname, ban):
        names, err = self._resolve_targets(nickname)
        if err:
            return False, err
        target = None
        with self._lock:
            for m in self.members.values():
                if m["nickname"] == names[0] and not m["is_host"]:
                    target = m
                    break
        if target is None:
            if names[0] == self.host_nick:
                return False, "不能踢房主（自己）"
            return False, "目标无法被踢出"
        if ban:
            self._banned.add(target["nickname"])
        conn = self._conns.get(target["id"])
        if conn is not None:
            try:
                send_msg(conn, {"t": "kicked", "reason": "已被房主 ban" if ban else "已被房主踢出"})
            except OSError:
                pass
        self._drop_member(target["id"], "kicked")
        return True, f"已{' ban' if ban else '踢出'} {target['nickname']}"

    def _cmd_kick(self, cmd, args):
        if not args:
            return False, "用法：kick <玩家>"
        return self._kick_or_ban(args[0], ban=False)

    def _cmd_ban(self, cmd, args):
        if not args:
            return False, "用法：ban <玩家>"
        return self._kick_or_ban(args[0], ban=True)

    def _cmd_lock(self, cmd, args):
        value = (args[0].lower() in ("on", "1", "开", "true")) if args else True
        self.set_locked(value)
        return True, "房间已锁定（禁止新玩家加入）" if value else "房间已解锁"

    def _cmd_pwd(self, cmd, args):
        if not args:
            return False, "用法：pwd <新密码> 或 pwd off（取消密码）"
        new_pwd = "" if args[0].lower() in ("off", "无", "") else args[0][:24]
        self.set_password(new_pwd)
        return True, "房间密码已取消" if not new_pwd else f"房间密码已改为：{new_pwd}"

    def _cmd_say(self, cmd, args):
        text = " ".join(args).strip()
        if not text:
            return False, "用法：say <消息>"
        self._console_broadcast(f"[房主] {text}")
        return True, "已广播"


# ============================ 房间客户端（加入方） ============================

class RoomClient:
    """加入方启动器内的房间客户端：主动连接房主 25250。

    events 队列（UI 轮询）：
      ("members", list) ("room_update", dict) ("console", text)
      ("cmd_apply", dict) ("start", game) ("lobby", reason)
      ("kicked", reason) ("closed", reason) ("disconnected", None)
    """

    def __init__(self, nickname):
        self.nickname = nickname
        self.events = queue.Queue()
        self.room = None
        self.you = None
        self.members = []
        self._sock = None
        self._reader = None
        self._run = False
        self._thread = None

    def connect(self, ip, password="", timeout=5.0):
        ip = (ip or "").strip()
        try:
            self._sock = socket.create_connection((ip, ROOM_PORT), timeout=timeout)
        except OSError as exc:
            raise RoomError(f"无法连接 {ip}:{ROOM_PORT}（{type(exc).__name__}）") from None
        try:
            self._sock.settimeout(timeout + 5)
            send_msg(self._sock, {
                "t": "hello", "nickname": self.nickname,
                "password": password, "proto": PROTO_VERSION,
            })
            reader = self._sock.makefile("r", encoding="utf-8", errors="replace")
            line = reader.readline()
            if not line:
                raise RoomError("房间无响应")
            resp = json.loads(line)
            if resp.get("t") == "reject":
                raise RoomError(resp.get("reason", "加入失败"))
            if resp.get("t") != "welcome":
                raise RoomError("协议不兼容")
            self.room = resp.get("room", {})
            self.you = resp.get("you", {})
            self.members = resp.get("members", [])
            self._sock.settimeout(None)
            self._reader = reader
            self._run = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return resp
        except (OSError, ValueError) as exc:
            try:
                self._sock.close()
            except OSError:
                pass
            raise RoomError(f"加入失败：{exc}") from None

    def _loop(self):
        try:
            for raw in self._reader:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("t")
                if kind == "members":
                    self.members = msg.get("members", [])
                    self.events.put(("members", self.members))
                elif kind == "room_update":
                    room = msg.get("room", {})
                    if self.room:
                        self.room.update(room)
                    self.events.put(("room_update", self.room))
                elif kind == "console":
                    self.events.put(("console", msg.get("text", "")))
                elif kind == "cmd_apply":
                    self.events.put(("cmd_apply", msg.get("cmd", {})))
                elif kind == "start":
                    self.events.put(("start", msg.get("game", {})))
                elif kind == "lobby":
                    self.events.put(("lobby", msg.get("reason", "")))
                elif kind == "kicked":
                    self.events.put(("kicked", msg.get("reason", "")))
                    break
                elif kind == "closed":
                    self.events.put(("closed", msg.get("reason", "")))
                    break
        except (OSError, ValueError):
            pass
        self._run = False
        self.events.put(("disconnected", None))

    def connected(self):
        return self._run

    def send(self, obj):
        try:
            send_msg(self._sock, obj)
        except (OSError, AttributeError):
            pass

    def leave(self):
        self.send({"t": "leave"})
        self.close()

    def close(self):
        self._run = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        try:
            self._sock.close()
        except (OSError, AttributeError):
            pass


def build_game_args(nickname, team, token, game_cfg, is_host):
    """构造传给 射击.py 的联机命令行参数

    房主的游戏进程走本机回环 127.0.0.1:25250（与房间服务同进程）；
    加入方直连房主局域网 IP。
    """
    players_json = json.dumps(game_cfg.get("players", []), ensure_ascii=False)
    host = "127.0.0.1" if is_host else game_cfg.get("host_ip", "127.0.0.1")
    return [
        "--net-mode", "host" if is_host else "client",
        "--host", host,
        "--port", str(game_cfg.get("port", ROOM_PORT)),
        "--nickname", nickname,
        "--team", team,
        "--token", token,
        "--room-name", game_cfg.get("room_name", ""),
        "--mode", game_cfg.get("mode", "duel"),
        "--players-json", players_json,
    ]
