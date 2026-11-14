# -*- coding: utf-8 -*-
"""第一人称视图模型（viewmodel）：装备、切枪、检视、后坐力、换弹、挥砍。

分工
    WeaponModel  单个武器：GLB 模型 + 静态姿态（pivot）+ 枪口闪光
    Viewmodel    管理器：挂在摄像机下，逐帧算出"姿态偏移"叠加给当前武器

所有动作都是程序化的（没有骨骼动画资源），靠关键帧轨道 + 指数缓动实现：
    F 键检视   Track（config.INSPECT_*）      抬枪/翻转/回正
    开火       recoil 标量衰减                后坐 + 枪口闪光
    换弹       跟随 combat.Weapon.reload_progress 的 sin 曲线下压
    挥砍       Track（config.SWING_KNIFE）    起手 → 划过 → 收回
    走路/甩枪  bob + sway 时间积分            武器跟随移动轻微摇晃
"""
import math

from panda3d.core import TransparencyAttrib, Vec3
from ursina import (AmbientLight, DirectionalLight, Entity, Vec2, clamp, color,
                    mouse)

from .anim import Track, clamp as _clamp
from .config import CATALOG, ORDER
from .loader import load_glb

# 切枪动画时长（秒）
SWITCH_DOWN = 0.16
SWITCH_UP = 0.24


class WeaponModel(Entity):
    """一把武器的视图模型。

    层级（关键：动画旋转要绕**武器自身**转，而不是绕摄像机光轴转）
        WeaponModel（容器）  位置 = 基础位置 + 动画位移，旋转 = 动画角度
          └ pivot            静态朝向 + 尺寸（模型已归一化成最长边 1）
              └ node         GLB 网格，几何中心在 pivot 原点
    """

    def __init__(self, parent, spec):
        super().__init__(parent=parent, name=f"weapon_{spec['key']}")
        self.spec = spec
        self.kind = spec['kind']
        self.base_pos = Vec3(*spec['pos'])

        # 静态姿态：朝向 / 尺寸
        self.pivot = Entity(parent=self, rotation=Vec3(*spec['rot']), scale=spec['length'])
        self.node = load_glb(spec['model'], palette=spec.get('palette'))
        self.node.reparentTo(self.pivot)

        self.position = self.base_pos

        # 枪口：位置用归一化模型坐标，挂在 pivot 下继承姿态
        self.muzzle = Entity(parent=self.pivot, position=Vec3(*spec['muzzle']),
                             name='muzzle')
        self.flash_parts = []
        self._build_flash()
        self.flash_t = 0.0

    def _build_flash(self):
        """枪口火光：一个亮球 + 两片交叉的星星面片，只在开火瞬间出现两帧。"""
        core = Entity(parent=self.muzzle, model='sphere', scale=0.17,
                      color=color.rgba(255, 246, 214, 255))
        core.setLightOff()
        star_a = Entity(parent=self.muzzle, model='quad', scale=(0.52, 0.52),
                        color=color.rgba(255, 206, 128, 235))
        star_b = Entity(parent=self.muzzle, model='quad', scale=(0.40, 0.40),
                        rotation_z=45, color=color.rgba(255, 232, 176, 210))
        for e in (star_a, star_b):
            e.setLightOff()
            e.setBillboardPointEye()
            e.setTransparency(TransparencyAttrib.M_alpha)
        self.flash_parts = [core, star_a, star_b]
        for e in self.flash_parts:
            e.enabled = False

    # -- 动作 ------------------------------------------------------
    def flash_on(self, seconds=0.055):
        self.flash_t = seconds
        for e in self.flash_parts:
            e.enabled = True

    def update_flash(self, dt):
        if self.flash_t <= 0:
            return
        self.flash_t -= dt
        if self.flash_t <= 0:
            self.flash_t = 0.0
            for e in self.flash_parts:
                e.enabled = False

    @property
    def muzzle_world(self):
        return self.muzzle.world_position


class Viewmodel(Entity):
    """武器管理器。挂在摄像机下，只影响自己子树里的模型（含补光灯）。"""

    def __init__(self, parent, order=ORDER, catalog=CATALOG, on_switch=None):
        super().__init__(parent=parent, name='viewmodel')
        self.catalog = catalog
        self.order = list(order)
        self.on_switch = on_switch

        self._build_lights()

        self.models = {}
        for key in self.order:
            spec = catalog[key]
            model = WeaponModel(self, spec)
            model.enabled = False
            self.models[key] = model

        self.active_key = self.order[0]
        self.models[self.active_key].enabled = True
        # 可切换集合（配装）：默认全部（游戏主脚本会用配装收窄）
        self.available = set(self.order)

        # 动画状态
        self.recoil = 0.0
        self.sway = Vec2(0, 0)
        self.bob_phase = 0.0
        self.bob_amt = 0.0
        self._speed = 0.0
        self._last_world = None
        self.switch_state = 'idle'
        self.switch_t = 0.0
        self.pending = None

        self.inspect = {}
        self.swing = {}
        for key in self.order:
            spec = catalog[key]
            ins = spec.get('inspect')
            self.inspect[key] = Track(ins['keys'], ins['duration'], 'inspect') if ins else None
            sw = spec.get('swing')
            self.swing[key] = Track(sw['keys'], sw['duration'], 'swing') if sw else None

    def _build_lights(self):
        """只给武器打的补光：灯挂在 viewmodel 下，不会影响场景与 HUD。"""
        try:
            AmbientLight(parent=self, color=color.rgba(0.66, 0.70, 0.78, 0.62))
            key = DirectionalLight(parent=self, y=3, z=-2, rotation=(26, -30, 0))
            key.color = color.rgba(1.0, 0.97, 0.93, 1.0)
            fill = DirectionalLight(parent=self, y=2, z=-1, rotation=(-14, 150, 0))
            fill.color = color.rgba(0.62, 0.66, 0.74, 0.45)
        except Exception as exc:            # 灯光不是必需品，失败也要能玩
            print('[武器] 补光初始化失败:', exc)

    # -- 查询 ------------------------------------------------------
    @property
    def active(self):
        return self.models[self.active_key]

    @property
    def spec(self):
        return self.catalog[self.active_key]

    @property
    def kind(self):
        return self.spec['kind']

    @property
    def busy(self):
        """切枪过程中不能开火 / 换弹。"""
        return self.switch_state != 'idle'

    @property
    def inspecting(self):
        track = self.inspect.get(self.active_key)
        return bool(track and track.active)

    # -- 切换 ------------------------------------------------------
    def switch_to(self, key):
        if key not in self.models or key not in self.available \
                or key == self.active_key or self.busy:
            return False
        self.pending = key
        self.switch_state = 'down'
        self.switch_t = 0.0
        self._stop_tracks()
        return True

    def cycle(self, step=1):
        owned = [k for k in self.order if k in self.available]
        if not owned or self.active_key not in owned:
            return False
        i = owned.index(self.active_key)
        return self.switch_to(owned[(i + step) % len(owned)])

    def set_available(self, keys):
        """配装变化：限定可切换的武器集合（匕首 + 副武器 + 主武器）。

        当前武器不在集合里时自动切到集合中的第一把（保持手上有枪）。
        返回切换后的 active_key。
        """
        self.available = set(keys)
        if self.active_key not in self.available:
            target = next((k for k in self.order if k in self.available), None)
            if target and not self.busy:
                self.switch_to(target)
            elif target and self.busy and self.pending not in self.available:
                # 切枪动画中目标被撤装：改切到合法武器
                self.pending = target
        return self.active_key

    def _stop_tracks(self):
        for track in list(self.inspect.values()) + list(self.swing.values()):
            if track:
                track.stop()

    # -- 检视 / 开火 / 挥砍 ---------------------------------------
    def start_inspect(self):
        """F 键：播放检视动画；正在检视时再按一次提前收枪。"""
        track = self.inspect.get(self.active_key)
        if track is None or self.busy:
            return False
        if track.active:
            track.stop()
            return False
        track.play()
        return True

    def fire_anim(self, vm=1.0):
        """开火后坐动画。vm = config 里 recoil['vm'] 的倍率（枪越重顶得越狠）。"""
        self.recoil = clamp(vm, 0.35, 2.6)
        self.active.flash_on()
        track = self.inspect.get(self.active_key)
        if track:
            track.stop()

    def swing_anim(self):
        track = self.swing.get(self.active_key)
        if track:
            track.play()
        ins = self.inspect.get(self.active_key)
        if ins:
            ins.stop()

    def reload_started(self):
        ins = self.inspect.get(self.active_key)
        if ins:
            ins.stop()

    # -- 每帧 ------------------------------------------------------
    def _switch_offset(self):
        """返回 0~1：武器被压到屏幕下方的程度。"""
        if self.switch_state == 'down':
            return _clamp(self.switch_t / SWITCH_DOWN)
        if self.switch_state == 'up':
            return 1.0 - _clamp(self.switch_t / SWITCH_UP)
        return 0.0

    def update_switch(self, dt):
        if self.switch_state == 'idle':
            return
        self.switch_t += dt
        if self.switch_state == 'down' and self.switch_t >= SWITCH_DOWN:
            self.models[self.active_key].enabled = False
            self.active_key = self.pending
            self.pending = None
            self.models[self.active_key].enabled = True
            self.switch_state = 'up'
            self.switch_t = 0.0
            if callable(self.on_switch):
                self.on_switch(self.active_key, self.spec)
        elif self.switch_state == 'up' and self.switch_t >= SWITCH_UP:
            self.switch_state = 'idle'
            self.switch_t = 0.0

    def tick(self, dt, weapon=None, body=None):
        dt = max(0.0, min(0.1, dt))          # 卡帧时不要跳变
        self.update_switch(dt)

        for track in self.inspect.values():
            if track and track.active:
                track.update(dt)
        active_swing = self.swing.get(self.active_key)
        if active_swing and active_swing.active:
            active_swing.update(dt)

        # 后坐力衰减（大约 0.14 秒回位）
        self.recoil = max(0.0, self.recoil - dt * 7.0)

        # 甩枪惯性：鼠标速度反向带动武器
        try:
            mv = mouse.velocity
            target = Vec2(_clamp(-mv[0] * 0.30, -0.8, 0.8),
                          _clamp(-mv[1] * 0.30, -0.8, 0.8))
        except Exception:
            target = Vec2(0, 0)
        self.sway += (target - self.sway) * min(1.0, dt * 9.0)

        # 走路晃动：用位移速度驱动相位
        if body is not None:
            try:
                wp = body.world_position
                if self._last_world is not None and dt > 0:
                    self._speed = (wp - self._last_world).length / dt
                self._last_world = wp
            except Exception:
                pass
        want = min(1.0, self._speed / 7.0)
        self.bob_amt += (want - self.bob_amt) * min(1.0, dt * 5.0)
        self.bob_phase += dt * (5.2 + min(self._speed, 12.0) * 1.5)

        pos = Vec3(0, 0, 0)
        rot = Vec3(0, 0, 0)

        # 后坐力：向后（-Z）一顶 + 枪口上跳
        k = self.recoil
        if k > 0:
            pos += Vec3(0.012 * k, 0.014 * k, -0.085 * k)
            rot += Vec3(-11.0 * k, 2.4 * k, 1.6 * k)

        # 甩枪
        pos += Vec3(self.sway[0] * 0.016, self.sway[1] * 0.016, 0)
        rot += Vec3(self.sway[1] * 18.0, -self.sway[0] * 18.0, self.sway[0] * 10.0)

        # 走路
        if self.bob_amt > 0.01:
            s = math.sin(self.bob_phase)
            c = math.cos(self.bob_phase)
            pos += Vec3(s * 0.011, abs(c) * 0.010 - 0.004, 0) * self.bob_amt
            rot += Vec3(0, 0, c * 1.8 * self.bob_amt)

        # 换弹：下压 + 向外翻（进度来自 combat.Weapon）
        if weapon is not None and getattr(weapon, 'reloading', False):
            r = math.sin(math.pi * _clamp(weapon.reload_progress)) ** 0.65
            pos += Vec3(0.012 * r, -0.150 * r, 0.020 * r)
            rot += Vec3(17.0 * r, -8.0 * r, -24.0 * r)

        # 切枪下压
        if self.switch_state != 'idle':
            s = self._switch_offset()
            pos += Vec3(0.0, -0.34 * s, 0.07 * s)
            rot += Vec3(36.0 * s, 0.0, 12.0 * s)

        # 检视 / 挥砍
        track = self.inspect.get(self.active_key)
        if track:
            p, r = track.pose()
            pos += Vec3(*p)
            rot += Vec3(*r)
        if active_swing:
            p, r = active_swing.pose()
            pos += Vec3(*p)
            rot += Vec3(*r)

        model = self.active
        model.position = model.base_pos + pos
        model.rotation = rot

        for m in self.models.values():
            m.update_flash(dt)
