"""战斗数值系统：血量 / 护甲 / 弹药 / 换弹 / 摔落伤害 / 训练场回血。

设计为纯逻辑模块（不碰 UI，也不直接读 ursina 的全局状态），
下一版接入联机同步时只需要把 take_damage / score 的写入方换成网络事件。
"""
from __future__ import annotations


class Weapon:
    """一把枪的弹药与射击节奏。"""

    def __init__(self, name='GLOCK-18', mag_size=20, reserve=120, rpm=430,
                 reload_time=2.1, auto=True):
        self.name = name
        self.mag_size = mag_size
        self.mag = mag_size
        self.reserve = reserve
        self.interval = 60.0 / max(1, rpm)
        self.reload_time = reload_time
        self.auto = auto

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
        if self.reloading or self.mag >= self.mag_size or self.reserve <= 0:
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
                need = self.mag_size - self.mag
                take = min(need, self.reserve)
                self.mag += take
                self.reserve -= take
                self.reloading = False
                self.reload_left = 0.0

    def refill(self):
        self.mag = self.mag_size
        self.reserve = 120
        self.reloading = False
        self.reload_left = 0.0
        self.cooldown = 0.0

    # -- 显示 ------------------------------------------------------
    @property
    def reserve_text(self) -> str:
        return '∞' if self.reserve <= 0 and self.mag > 0 and self.reserve == -1 else str(self.reserve)


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
