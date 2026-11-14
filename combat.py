"""战斗数值系统：血量 / 护甲 / 弹药 / 换弹 / 摔落伤害 / 训练场回血。

设计为纯逻辑模块（不碰 UI，也不直接读 ursina 的全局状态），
下一版接入联机同步时只需要把 take_damage / score 的写入方换成网络事件。
"""
from __future__ import annotations

# ============================ 分部位伤害判定 ============================
# 三区简化制（用户选定）：头部最高、胸+躯干统一 1.25、肢体（手臂/腿）0.75。
# 木偶人与玩家角色使用同一套倍率与同一套结算入口。
ZONE_MULTIPLIERS = {
    'head': 4.0,     # 头部：一击致命区
    'body': 1.25,    # 胸 + 躯干（腰腹）：火力集中区
    'limb': 0.75,    # 手臂 / 腿：打肢体亏伤害
}

ZONE_CN = {'head': '头部', 'body': '躯干', 'limb': '肢体'}


def zone_damage(base: float, zone: str) -> float:
    """按部位换算最终伤害（未知部位按躯干算）。"""
    return base * ZONE_MULTIPLIERS.get(zone, ZONE_MULTIPLIERS['body'])


def classify_zone_by_height(height: float, player_height: float = 1.8) -> str:
    """按命中点离地高度划分部位（玩家 / 人机通用，无实体分件时用）。

    站姿 1.8 米：头部 ≈ 顶部 14%（≥1.55 米），躯干中段，肢体为下肢。
    """
    if height >= player_height * 0.86:      # ≥1.55
        return 'head'
    if height >= player_height * 0.42:      # ≥0.75
        return 'body'
    return 'limb'


class Weapon:
    """一把枪的弹药、伤害与射击节奏。"""

    def __init__(self, name='GLOCK-18', mag_size=20, reserve=120, rpm=430,
                 reload_time=2.1, auto=True, damage=25):
        self.name = name
        self.mag_size = mag_size
        self.mag = mag_size
        self.reserve = reserve
        self.reserve_max = reserve
        # 备弹无限（训练/对战都不需要补给，弹匣打完换弹即可）
        self.infinite_reserve = False
        self.interval = 60.0 / max(1, rpm)
        self.reload_time = reload_time
        self.auto = auto
        self.damage = damage

        self.cooldown = 0.0
        self.reloading = False
        self.reload_left = 0.0

    # -- 状态查询 --------------------------------------------------
    @property
    def empty(self) -> bool:
        return self.mag <= 0

    @property
    def reload_progress(self) -> float:
        if not self.reloading:
            return 1.0
        return 1.0 - max(0.0, self.reload_left) / self.reload_time

    # -- 动作 ------------------------------------------------------
    def can_fire(self) -> bool:
        return (not self.reloading) and self.cooldown <= 0.0 and self.mag > 0

    def fire(self) -> bool:
        """扣一发子弹；返回是否成功击发。"""
        if not self.can_fire():
            return False
        self.mag -= 1
        self.cooldown = self.interval
        return True

    def start_reload(self) -> bool:
        if self.reloading or self.mag >= self.mag_size:
            return False
        if not self.infinite_reserve and self.reserve <= 0:
            return False
        self.reloading = True
        self.reload_left = self.reload_time
        return True

    def cancel_reload(self):
        self.reloading = False
        self.reload_left = 0.0

    def update(self, dt: float):
        self.cooldown = max(0.0, self.cooldown - dt)
        if self.reloading:
            self.reload_left -= dt
            if self.reload_left <= 0.0:
                if self.infinite_reserve:
                    self.mag = self.mag_size       # 备弹无限：直接补满
                else:
                    need = self.mag_size - self.mag
                    take = min(need, self.reserve)
                    self.mag += take
                    self.reserve -= take
                self.reloading = False
                self.reload_left = 0.0

    def refill(self):
        self.mag = self.mag_size
        self.reserve = self.reserve_max
        self.reloading = False
        self.reload_left = 0.0
        self.cooldown = 0.0

    # -- 显示 ------------------------------------------------------
    @property
    def reserve_text(self) -> str:
        if self.infinite_reserve:
            return '∞'
        return str(self.reserve)


class Melee:
    """近战武器：没有弹药，只关心挥砍节奏、伤害与攻击距离。

    属性与 Weapon 保持兼容（mag / reserve / reloading …），
    这样 HUD 的生命周期不用为近战写第二套分支。
    """

    def __init__(self, name='刺刀', damage=55, rpm=110, reach=2.6):
        self.name = name
        self.damage = damage
        self.reach = reach
        self.interval = 60.0 / max(1, rpm)
        self.cooldown = 0.0

        # 兼容 HUD / 掉落逻辑
        self.mag_size = 0
        self.mag = 0
        self.reserve = 0
        self.reserve_max = 0
        self.reload_time = 0.0
        self.reloading = False
        self.reload_left = 0.0
        self.auto = False

    @property
    def empty(self) -> bool:
        return False                     # 刀永远不会"没子弹"

    @property
    def reload_progress(self) -> float:
        return 1.0

    @property
    def reserve_text(self) -> str:
        return '—'                       # 近战无备弹概念（HUD 显示占位符）

    def can_fire(self) -> bool:
        return self.cooldown <= 0.0

    def fire(self) -> bool:
        """挥砍一次；返回是否成功（冷却中挥不出第二刀）。"""
        if self.cooldown > 0.0:
            return False
        self.cooldown = self.interval
        return True

    def start_reload(self) -> bool:
        return False

    def cancel_reload(self):
        pass

    def update(self, dt: float):
        self.cooldown = max(0.0, self.cooldown - dt)

    def refill(self):
        self.cooldown = 0.0


class Player:
    """玩家状态。护甲按 CS:GO 的规则吸收一半伤害。"""

    def __init__(self, max_health=100, max_armor=100, start_armor=100):
        self.max_health = max_health
        self.max_armor = max_armor
        self.health = max_health
        self.armor = start_armor
        self.alive = True

        self.kills = 0
        self.deaths = 0
        self.assists = 0
        self.score = 0

        self.since_damage = 999.0
        self.regen_delay = 5.0        # 训练场：5 秒未受伤开始回血
        self.regen_rate = 9.0         # 每秒回血量
        self.regen_enabled = True

        self.death_time = 0.0
        self.respawn_delay = 3.0

        # 给 HUD 做数字滚动/闪烁用
        self.last_damage = 0
        self.damage_flash = 0.0

    # -- 伤害 ------------------------------------------------------
    def take_damage(self, amount: float, ignore_armor=False) -> int:
        if not self.alive or amount <= 0:
            return 0
        amount = float(amount)
        if not ignore_armor and self.armor > 0:
            absorbed = amount * 0.5
            self.armor = max(0.0, self.armor - absorbed * 0.5)
            amount *= 0.5
        amount = int(round(amount))
        self.health = max(0.0, self.health - amount)
        self.since_damage = 0.0
        self.last_damage = amount
        self.damage_flash = 1.0
        if self.health <= 0:
            self.die()
        return amount

    def heal(self, amount: float) -> int:
        if not self.alive:
            return 0
        before = self.health
        self.health = min(self.max_health, self.health + amount)
        return int(round(self.health - before))

    def add_armor(self, amount: float):
        self.armor = min(self.max_armor, self.armor + amount)

    def die(self):
        if not self.alive:
            return
        self.alive = False
        self.health = 0.0
        self.deaths += 1
        self.death_time = self.respawn_delay

    def respawn(self, full_armor=True):
        self.alive = True
        self.health = self.max_health
        if full_armor:
            self.armor = self.max_armor
        self.since_damage = 999.0
        self.damage_flash = 0.0
        self.death_time = 0.0

    # -- 每帧 ------------------------------------------------------
    def update(self, dt: float):
        self.since_damage += dt
        self.damage_flash = max(0.0, self.damage_flash - dt * 2.2)
        if not self.alive:
            self.death_time = max(0.0, self.death_time - dt)
            return
        if (self.regen_enabled and self.health < self.max_health
                and self.since_damage >= self.regen_delay):
            self.health = min(self.max_health, self.health + self.regen_rate * dt)

    # -- 显示 ------------------------------------------------------
    @property
    def health_text(self) -> str:
        return str(int(round(self.health)))

    @property
    def armor_text(self) -> str:
        return str(int(round(self.armor)))

    @property
    def low_health(self) -> bool:
        return self.alive and self.health <= 30
