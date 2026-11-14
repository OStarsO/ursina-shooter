# -*- coding: utf-8 -*-
"""程序化动画：关键帧采样 + 一次性动画轨道。

不依赖引擎，纯数学，可以直接单测。
关键帧形如 ``[(0.0, (x, y, z), (rx, ry, rz)), ...]``，时间轴归一化到 0~1。
"""


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def smoothstep(u):
    """0→1 的平滑过渡（两端速度为 0，中间快），避免线性插值的机械感。"""
    u = clamp(u)
    return u * u * (3.0 - 2.0 * u)


def lerp3(a, b, k):
    return (a[0] + (b[0] - a[0]) * k,
            a[1] + (b[1] - a[1]) * k,
            a[2] + (b[2] - a[2]) * k)


def add3(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def mul3(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def sample(keys, u):
    """在关键帧序列上采样，返回 (位置偏移, 角度偏移)。"""
    if not keys:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    u = clamp(u)
    if u <= keys[0][0]:
        return keys[0][1], keys[0][2]
    for i in range(len(keys) - 1):
        t0, p0, r0 = keys[i]
        t1, p1, r1 = keys[i + 1]
        if u <= t1:
            k = smoothstep((u - t0) / max(1e-6, t1 - t0))
            return lerp3(p0, p1, k), lerp3(r0, r1, k)
    return keys[-1][1], keys[-1][2]


class Track:
    """一次性动画轨道：play() 之后每帧 update(dt)，播完自动复位。

    pose() 在未播放时返回零位移，所以调用方可以无脑叠加：
        p, r = track.pose()   # (0,0,0), (0,0,0)
    """

    def __init__(self, keys, duration=1.0, name='track'):
        self.keys = list(keys)
        self.duration = max(0.05, float(duration))
        self.name = name
        self.t = 0.0
        self.active = False

    # -- 控制 ------------------------------------------------------
    def play(self):
        self.active = True
        self.t = 0.0

    def stop(self):
        self.active = False
        self.t = 0.0

    # -- 状态 ------------------------------------------------------
    @property
    def progress(self):
        if not self.active:
            return 0.0
        return clamp(self.t / self.duration)

    @property
    def finished(self):
        return not self.active

    def pose(self):
        """当前帧的偏移量；未播放时是零偏移。"""
        if not self.active:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return sample(self.keys, self.progress)

    def update(self, dt):
        """推进时间，返回当前 pose；播放结束时返回 None。"""
        if not self.active:
            return None
        self.t += dt
        if self.t >= self.duration:
            self.active = False
            self.t = 0.0
            return None
        return sample(self.keys, self.progress)


class Spring:
    """指数趋近（帧率无关），用来做摆臂 / 后坐力的缓动。"""

    def __init__(self, value=0.0, speed=10.0):
        self.value = float(value)
        self.target = float(value)
        self.speed = float(speed)

    def to(self, target):
        self.target = float(target)
        return self

    def update(self, dt):
        k = 1.0 - pow(2.718281828, -self.speed * max(0.0, dt))
        self.value += (self.target - self.value) * k
        return self.value
