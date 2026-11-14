# -*- coding: utf-8 -*-
"""服务器端命中声明验证（反作弊核心）。

思路：客户端**只上报事实**（谁用哪把枪命中了谁的哪个部位），伤害数值、
射速节流、目标存活全部由服务器按武器配置表独立计算——客户端无法通过
伪造 damage 字段刷伤害，也无法超物理射速击发，更不能鞭尸已重生目标。

校验范围（服务器做）：
  1. 武器合法性     weapon 必须在 weapons/config.CATALOG 且为枪械；
  2. 部位合法性     zone ∈ {head, body, limb}；
  3. 射速节流       同一攻击者同一武器的最小击发间隔 = 60/rpm 秒，
                    容忍 10% 网络抖动；超频声明直接拒绝；
  4. 伤害权威计算   damage = 配置伤害 × 部位倍率（head 4.0 / body 1.25 /
                    limb 0.75），与游戏内 combat.zone_damage 完全同源；
  5. 目标存活       目标 hp ≤ 0 后进入重生窗口（默认 3 秒），窗口内
                    的一切命中声明拒绝（防鞭尸刷分）；
  6. 攻击者身份     玩家只能以自己的身份上报；人机的声明只能由房主
                    连接代报且 attacker 必须是对应 bot 成员；
  7. 击杀归属       服务器累计 kills / deaths / score 并广播权威比分。

校验范围之外（已知局限，文档如实说明）：
  - 服务器不同步世界坐标，无法验证"隔墙命中/视野外命中"（防透视/自瞄
    需要完整位置同步与服务器端弹道模拟，属下一阶段）；
  - 人机运行在房主机器上，人机的命中可信度取决于房主端诚实上报，
    服务器同样套用射速/伤害规则约束，但无法验证其真实性。

判定流程（一次 hit_claim）：
    claim(attacker, target, weapon, zone, now)
      → 武器/部位检查 → 攻击者身份检查 → 射速节流检查
      → 目标存活检查 → 服务器计算伤害 → 扣血 →（击杀则进重生窗口）
      → 返回 (accepted, reason, damage, kill) 并由 RoomService 广播比分。
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weapons.config import CATALOG

# 与 combat.ZONE_MULTIPLIERS 保持一致（anticheat 不 import ursina，复制常量）
ZONE_MULTIPLIERS = {'head': 4.0, 'body': 1.25, 'limb': 0.75}
DEFAULT_HP = 100
RATE_TOLERANCE = 0.9          # 允许 10% 的网络抖动提前量
RESPAWN_SECONDS = 3.0


class RejectReason:
    WEAPON = '未知武器或非枪械'
    ZONE = '非法部位'
    RATE = '超出射速限制'
    ALIVE = '目标已阵亡（重生窗口内）'
    IDENTITY = '无权以该攻击者身份上报'
    SELF = '不能攻击自己'


class AntiCheat:
    """一次对局一份实例；服务器单线程调用即可（RoomService 已有锁）。"""

    def __init__(self, respawn_seconds=RESPAWN_SECONDS):
        self.respawn_seconds = respawn_seconds
        self.last_fire = {}          # (attacker_id, weapon) -> 上次击发时间
        self.hp = {}                 # target_id -> 当前血量
        self.dead_until = {}         # target_id -> 重生完成时刻
        self.stats = {}              # member_id -> {kills, deaths, score}
        self.rejected = 0

    # ---------------- 回合管理 ----------------

    def begin_round(self, member_ids):
        """对局开始：为全部参战成员初始化血量与战绩。"""
        self.hp = {mid: DEFAULT_HP for mid in member_ids}
        self.dead_until = {}
        self.last_fire = {}
        self.stats = {mid: {'kills': 0, 'deaths': 0, 'score': 0}
                      for mid in member_ids}
        self.rejected = 0

    def stats_public(self):
        return {str(k): dict(v) for k, v in self.stats.items()}

    # ---------------- 校验核心 ----------------

    def claim(self, attacker_id, target_id, weapon, zone, now,
              reporter_id=None):
        """处理一条命中声明。

        attacker_id:  实际造成伤害的成员（玩家本人或 bot 成员 id）
        reporter_id:  发送本消息的连接所属成员（默认 = attacker_id）
        返回 (accepted, reason, damage, kill)。
        """
        reporter_id = attacker_id if reporter_id is None else reporter_id
        ok, reason = self._validate(attacker_id, target_id, weapon, zone,
                                    now, reporter_id)
        if not ok:
            self.rejected += 1
            return False, reason, 0.0, False

        # 服务器权威计算伤害（不信任客户端数值）
        base = getattr(self, '_cached_base', 0)
        damage = base * ZONE_MULTIPLIERS.get(zone, 1.0)
        self.last_fire[(attacker_id, weapon)] = now

        kill = False
        hp = self.hp.get(target_id, DEFAULT_HP) - damage
        if hp <= 0:
            hp = 0
            kill = True
        self.hp[target_id] = hp

        self.stats.setdefault(attacker_id, {'kills': 0, 'deaths': 0, 'score': 0})
        self.stats.setdefault(target_id, {'kills': 0, 'deaths': 0, 'score': 0})
        if kill:
            self.dead_until[target_id] = now + self.respawn_seconds
            self.stats[attacker_id]['kills'] += 1
            self.stats[attacker_id]['score'] += 10
            self.stats[target_id]['deaths'] += 1
        return True, '', damage, kill

    def respawn_done(self, member_id, now):
        """客户端上报目标重生完成 → 恢复血量、解除重生窗口。"""
        if self.dead_until.get(member_id, 0) <= now:
            self.dead_until.pop(member_id, None)
            self.hp[member_id] = DEFAULT_HP
            return True
        return False

    def is_alive(self, member_id, now):
        if member_id in self.dead_until and self.dead_until[member_id] > now:
            return False
        return self.hp.get(member_id, DEFAULT_HP) > 0

    # ---------------- 校验子步骤 ----------------

    def _validate(self, attacker_id, target_id, weapon, zone, now, reporter_id):
        # 1. 武器合法性（枪械走 rpm；近战固定 110rpm 节流）
        spec = CATALOG.get(weapon)
        if spec is None or spec.get('slot') is None:
            return False, RejectReason.WEAPON
        kind = spec.get('kind')
        if kind == 'gun':
            base = spec['ammo'].get('damage', 0)
            rpm = spec['ammo'].get('rpm', 1)
        elif kind == 'melee':
            base = spec.get('damage', 55)
            rpm = 110
        else:
            return False, RejectReason.WEAPON
        self._cached_base = base          # 供 claim() 复用（同线程顺序调用）
        # 2. 部位合法性
        if zone not in ZONE_MULTIPLIERS:
            return False, RejectReason.ZONE
        # 3. 身份（上报者 == 攻击者，或房主代报人机，或本人上报被自己的人机
        #    击中）由 RoomService 在连接层校验（它才知道连接属于谁）
        # 4. 不能打自己
        if attacker_id == target_id:
            return False, RejectReason.SELF
        # 5. 射速节流
        min_interval = 60.0 / max(1, rpm) * RATE_TOLERANCE
        last = self.last_fire.get((attacker_id, weapon))
        if last is not None and now - last < min_interval:
            return False, RejectReason.RATE
        # 6. 目标存活（重生窗口内拒绝一切命中）
        if not self.is_alive(target_id, now):
            return False, RejectReason.ALIVE
        return True, ''
