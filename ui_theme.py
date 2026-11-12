"""CS:GO 风格 UI 主题层。

集中管理：配色、字体、程序化贴图（噪点/渐变/辉光/暗角/雷达环/图标）、
锚点布局换算，以及面板 / 按钮 / 按键帽等基础控件。

坐标约定
--------
ursina 的 UI 空间：y ∈ [-0.5, 0.5]，x ∈ [-aspect/2, aspect/2]。
所有尺寸都以“屏高为 1”为单位，所以界面在不同分辨率下等比缩放；
横向位置用 ``ui_half_w()`` 做锚点换算，天然适配 16:9 / 21:9。

字号约定
--------
实测（900p）：文字 cap 高度 ≈ 15px × scale。因此对外统一用“900p 下的像素值”
``px(n)`` 表达尺寸、``fs(n)`` 表达字号，内部再换算成 scale，排版才好推算。

字体约定
--------
Panda3D 的字体加载对含中文的绝对路径不友好，因此统一使用
``fonts/xxx.ttf`` 相对路径（启动器会把工作目录设为游戏目录）。
含中文的文本必须用 ``FONT_CJK``，纯数字/英文用 Rajdhani / Barlow Condensed，
HUD 数字才有 CS:GO 那种窄体科技感。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from ursina import Button, Entity, Text, camera, color, time, window

# ------------------------------------------------------------------ 配色
# 参考 CS:GO HUD：深蓝灰面板 + 冷白文字 + 琥珀强调 + 双阵营色
C_VOID = (4, 6, 9)
C_PANEL = (10, 15, 20)
C_PANEL_2 = (17, 24, 31)
C_PANEL_HI = (31, 42, 54)
C_LINE = (54, 72, 88)
C_LINE_SOFT = (27, 37, 47)
C_TEXT = (231, 238, 244)
C_TEXT_DIM = (147, 163, 177)
C_TEXT_MUTE = (92, 106, 119)
C_ACCENT = (231, 161, 60)
C_TEAM_T = (222, 158, 66)
C_TEAM_CT = (108, 160, 214)
C_HP = (226, 233, 239)
C_DANGER = (206, 62, 54)
C_OK = (108, 196, 122)
TEXT_ON_ACTIVE = (245, 249, 252)

# ------------------------------------------------------------------ 字体
FONT_NUM = 'fonts/Rajdhani-Bold.ttf'
FONT_UI = 'fonts/BarlowCondensed-SemiBold.ttf'
FONT_CJK = 'msyh.ttc'
FONT_CJK_CANDIDATES = ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf', 'simsun.ttc')

# ------------------------------------------------------------------ 尺度
REF_H = 900.0
BT = 1.0 / REF_H          # 1 像素对应的 UI 单位
TEXT_K = 15.0             # 900p 下 1 个 scale = 15px cap 高度（Rajdhani / Barlow）
TEXT_K_CJK = 21.0         # 中文字体同 scale 更大，实测 21px，需要单独折算

TEX_DIR = Path('ui_cache')


def px(n: float) -> float:
    """900p 下的像素值 → UI 单位。"""
    return n / REF_H


def fs(n: float, cjk: bool = False) -> float:
    """900p 下的字号像素 → ursina Text scale（中英字体比例不同）。"""
    return n / (TEXT_K_CJK if cjk else TEXT_K)


def ui_half_w() -> float:
    """当前宽高比下的半宽，用于左右贴边布局。"""
    return window.aspect_ratio * 0.5


# ------------------------------------------------------------------ 颜色工具
def rgb(t):
    return color.rgb32(int(t[0]), int(t[1]), int(t[2]))


def rgba(t, a=255):
    return color.rgba32(int(t[0]), int(t[1]), int(t[2]), int(max(0, min(255, a))))


def mix(a, b, k: float):
    k = max(0.0, min(1.0, k))
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


# ------------------------------------------------------------------ 程序化贴图
def _save(img: Image.Image, name: str) -> str:
    try:
        TEX_DIR.mkdir(exist_ok=True)
        img.save(TEX_DIR / name)
        return f'ui_cache/{name}'
    except OSError as e:      # 目录只读时退化成无贴图，不影响功能
        print('UI 贴图写入失败:', name, e)
        return 'white_cube'


def _tex_noise() -> str:
    size = 128
    rnd = random.Random(7)
    lum = Image.frombytes('L', (size, size), bytes(rnd.randrange(256) for _ in range(size * size)))
    lum = lum.filter(ImageFilter.GaussianBlur(0.6))
    alpha = lum.point(lambda v: int(v * 0.05))
    white = Image.new('RGB', (size, size), (255, 255, 255))
    return _save(Image.merge('RGBA', (*white.split(), alpha)), 'noise.png')


def _tex_sheen() -> str:
    w, h = 8, 256
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    for y in range(h):
        a = int(42 * (1 - y / (h - 1)) ** 2.4)
        dr.line([(0, y), (w, y)], fill=(255, 255, 255, a))
    return _save(img, 'sheen.png')


def _tex_glow() -> str:
    size = 128
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    for r in range(size // 2, 0, -1):
        a = int(160 * (1 - r / (size / 2)) ** 2)
        dr.ellipse([size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r], fill=(255, 255, 255, a))
    return _save(img.filter(ImageFilter.GaussianBlur(2)), 'glow.png')


def _tex_vignette() -> str:
    w, h = 400, 226
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    pixels = img.load()
    cx, cy = w / 2, h / 2
    maxd = math.hypot(cx, cy)
    for y in range(h):
        for x in range(w):
            d = math.hypot(x - cx, y - cy) / maxd
            k = max(0.0, (d - 0.5) / 0.5)
            if k > 0:
                pixels[x, y] = (172, 26, 22, int(220 * k ** 1.7))
    return _save(img.filter(ImageFilter.GaussianBlur(6)), 'vignette.png')


def _tex_radar_ring() -> str:
    size = 512
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    c = size / 2
    for r, a, wd in ((244, 120, 3), (166, 66, 2), (88, 48, 2)):
        dr.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, a), width=wd)
    dr.line([(c, 8), (c, size - 8)], fill=(255, 255, 255, 30), width=2)
    dr.line([(8, c), (size - 8, c)], fill=(255, 255, 255, 30), width=2)
    for ang in range(0, 360, 45):
        rad = math.radians(ang)
        dr.line([(c + math.cos(rad) * 230, c + math.sin(rad) * 230),
                 (c + math.cos(rad) * 245, c + math.sin(rad) * 245)],
                fill=(255, 255, 255, 130), width=3)
    return _save(img, 'radar_ring.png')


def _tex_sweep() -> str:
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    c = size / 2
    steps = 42
    for i in range(steps):
        ang = -90 + i * 1.5
        rad = math.radians(ang)
        a = int(110 * (i / steps) ** 2)
        dr.polygon([(c, c),
                    (c + math.cos(rad) * c, c + math.sin(rad) * c),
                    (c + math.cos(math.radians(ang + 1.5)) * c,
                     c + math.sin(math.radians(ang + 1.5)) * c)],
                   fill=(150, 210, 255, a))
    return _save(img, 'sweep.png')


def _tex_wedge() -> str:
    """受伤方向：朝上的扇形，实体整体旋转即可指向来源。"""
    w, h = 256, 128
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    c = w / 2
    for i in range(70):
        a = int(215 * (1 - i / 69) ** 2)
        r = 28 + i * 0.62
        dr.arc([c - r, 62 - r, c + r, 62 + r], 202, 338, fill=(232, 48, 40, a), width=3)
    return _save(img.filter(ImageFilter.GaussianBlur(1.4)), 'wedge.png')


def _icon_health() -> str:
    s = 128
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([52, 14, 76, 114], radius=6, fill=(255, 255, 255, 255))
    dr.rounded_rectangle([14, 52, 114, 76], radius=6, fill=(255, 255, 255, 255))
    return _save(img, 'ic_health.png')


def _icon_armor() -> str:
    s = 128
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    outer = [(64, 4), (120, 26), (112, 80), (64, 124), (16, 80), (8, 26)]
    inner = [(64, 26), (99, 42), (94, 76), (64, 102), (34, 76), (29, 42)]
    dr.polygon(outer, fill=(255, 255, 255, 255))
    dr.polygon(inner, fill=(0, 0, 0, 0))
    return _save(img, 'ic_armor.png')


def _icon_bullet() -> str:
    s = 128
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle([46, 34, 82, 116], radius=5, fill=(255, 255, 255, 230))
    dr.polygon([(46, 38), (64, 8), (82, 38)], fill=(255, 255, 255, 230))
    dr.rectangle([46, 92, 82, 99], fill=(0, 0, 0, 110))
    return _save(img, 'ic_bullet.png')


def _icon_arrow() -> str:
    s = 128
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.polygon([(64, 6), (106, 114), (64, 86), (22, 114)], fill=(255, 255, 255, 255))
    return _save(img, 'ic_arrow.png')


def _tex_corner() -> str:
    s = 64
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, s - 1, 4], fill=(255, 255, 255, 255))
    dr.rectangle([0, 0, 4, s - 1], fill=(255, 255, 255, 255))
    return _save(img, 'corner.png')


TEX = {}


def _build_textures():
    TEX.update({
        'noise': _tex_noise(),
        'sheen': _tex_sheen(),
        'glow': _tex_glow(),
        'vignette': _tex_vignette(),
        'ring': _tex_radar_ring(),
        'sweep': _tex_sweep(),
        'wedge': _tex_wedge(),
        'ic_health': _icon_health(),
        'ic_armor': _icon_armor(),
        'ic_bullet': _icon_bullet(),
        'ic_arrow': _icon_arrow(),
        'corner': _tex_corner(),
    })


# ------------------------------------------------------------------ 字体探测
_FONT_READY = False


def has_cjk(text: str) -> bool:
    for ch in text:
        if '\u2e80' <= ch <= '\u9fff' or '\uff00' <= ch <= '\uffef':
            return True
    return False


def font_for(text: str, style: str = 'ui') -> str:
    if has_cjk(text):
        return FONT_CJK
    return FONT_NUM if style == 'num' else FONT_UI


def _loadable(name: str) -> bool:
    try:
        t = Text(text='测A1', font=name)
        ok = getattr(t, '_font', None) is not None
        t.enabled = False
        return bool(ok)
    except Exception:
        return False


def init_theme() -> str:
    """生成贴图、选定中文字体，返回实际使用的中文字体名。"""
    global FONT_CJK, _FONT_READY
    if _FONT_READY:
        return FONT_CJK
    _build_textures()
    for name in FONT_CJK_CANDIDATES:
        if _loadable(name):
            FONT_CJK = name
            break
    Text.default_font = FONT_CJK
    _FONT_READY = True
    return FONT_CJK


# ------------------------------------------------------------------ 基础控件
class Surface(Entity):
    """带局部坐标系的容器：子元素坐标以自身中心为原点。"""

    def __init__(self, parent, w: float = 0.0, h: float = 0.0, x: float = 0.0,
                 y: float = 0.0, z: float = 0.0, **kwargs):
        super().__init__(parent=parent, position=(x, y, z), **kwargs)
        self.w = w
        self.h = h

    def block(self, w, h, x=0.0, y=0.0, col=C_PANEL, alpha=255, z=0.0):
        return Entity(parent=self, model='quad', scale=(w, h), position=(x, y, z),
                      color=rgba(col, alpha))

    def hairline(self, w, h, x=0.0, y=0.0, col=C_LINE, alpha=210, z=-0.002):
        return Entity(parent=self, model='quad', scale=(w, h), position=(x, y, z),
                      color=rgba(col, alpha))

    def text(self, content, size_px, x=0.0, y=0.0, origin=(-0.5, 0.0), col=C_TEXT,
             style='ui', z=-0.01, alpha=255, font=None):
        font = font or font_for(content, style)
        return Text(text=content, parent=self, position=(x, y, z), origin=origin,
                    scale=fs(size_px, has_cjk(content) or font == FONT_CJK),
                    color=rgba(col, alpha), font=font)

    def image(self, tex, w, h, x=0.0, y=0.0, col=(255, 255, 255), alpha=255, z=-0.004):
        return Entity(parent=self, model='quad', texture=tex, scale=(w, h),
                      position=(x, y, z), color=rgba(col, alpha))


class Panel(Surface):
    """CS:GO 式面板：深色底 + 顶部受光 + 细噪点 + 1px 描边 + 可选角标。"""

    def __init__(self, parent, w, h, x=0.0, y=0.0, z=0.0, *,
                 fill=C_PANEL, alpha=246, border=True, border_col=C_LINE,
                 sheen=True, noise=True, accent_top=False, brackets=False,
                 shadow=True, **kwargs):
        super().__init__(parent, w, h, x, y, z, **kwargs)
        self.panel_col = fill
        self.panel_alpha = alpha

        if shadow:
            Entity(parent=self, model='quad', texture=TEX['glow'],
                   scale=(w * 1.18, h * 1.6), position=(0, -px(2), 0.004),
                   color=rgba((0, 0, 0), 110))

        self.bg = Entity(parent=self, model='quad', scale=(w, h), z=0.0,
                         color=rgba(fill, alpha))
        if sheen:
            Entity(parent=self, model='quad', texture=TEX['sheen'],
                   scale=(w, h), z=-0.001, color=rgba((255, 255, 255), 140))
        if noise:
            Entity(parent=self, model='quad', texture=TEX['noise'],
                   scale=(w, h), z=-0.0015, color=color.white,
                   texture_scale=(max(1, int(w * REF_H / 128)), max(1, int(h * REF_H / 128))))

        if border:
            t = BT * 1.2
            for bw, bh, bx, by in ((w, t, 0, h / 2 - t / 2), (w, t, 0, -h / 2 + t / 2),
                                   (t, h, -w / 2 + t / 2, 0), (t, h, w / 2 - t / 2, 0)):
                Entity(parent=self, model='quad', scale=(bw, bh), position=(bx, by, -0.002),
                       color=rgba(border_col, 225))

        if accent_top:
            Entity(parent=self, model='quad', scale=(w, BT * 2),
                   position=(0, h / 2 - BT, -0.003), color=rgba(C_ACCENT, 235))

        if brackets:
            s = px(9)
            for sx, sy, rot in ((-1, 1, 90), (1, 1, 0), (-1, -1, 180), (1, -1, 270)):
                e = Entity(parent=self, model='quad', texture=TEX['corner'], scale=(s, s),
                           position=(sx * (w / 2 - s / 2), sy * (h / 2 - s / 2), -0.003),
                           color=rgba(C_ACCENT, 190))
                e.rotation_z = rot

    def set_alpha(self, alpha):
        self.bg.color = rgba(self.panel_col, alpha)


class KeyCap(Surface):
    """按键帽：CS:GO 的按键提示是描边方框 + 大写字母。"""

    def __init__(self, parent, key, x=0.0, y=0.0, h_px=20.0, size_px=0.0):
        h = px(h_px)
        w = max(h * 1.02, px(h_px * (0.60 * len(key) + 0.46)))
        super().__init__(parent, w, h, x, y, -0.02)
        Entity(parent=self, model='quad', scale=(w, h), color=rgba((23, 31, 40), 246))
        t = BT * 1.1
        for bw, bh, bx, by in ((w, t, 0, h / 2 - t / 2), (w, t, 0, -h / 2 + t / 2),
                               (t, h - 2 * t, -w / 2 + t / 2, 0), (t, h - 2 * t, w / 2 - t / 2, 0)):
            Entity(parent=self, model='quad', scale=(bw, bh), position=(bx, by, -0.002),
                   color=rgba(C_LINE, 225))
        Entity(parent=self, model='quad', scale=(w - 3 * t, t),
               position=(0, h / 2 - 2.4 * t, -0.003), color=rgba((255, 255, 255), 26))
        self.label = Text(text=key.upper(), parent=self, position=(0, 0, -0.01),
                          origin=(0, 0), scale=fs(size_px or h_px * 0.62),
                          color=rgba(C_TEXT, 240), font=FONT_UI)


class CsButton(Entity):
    """CS:GO 风格按钮：深底 + 悬停提亮 + 左侧琥珀强调条 + 右侧按键帽。

    注意：ursina 的 Button 会把 scale 设成按钮尺寸，子元素坐标会被压缩，
    所以这里用「容器 Entity（scale=1）+ 内部 Button 热区」的结构，
    装饰与文字都是容器的子元素，可以用正常的 UI 单位。
    """

    def __init__(self, parent, w, h, x=0.0, y=0.0, *, text='', hint='', size_px=19.0,
                 align='left', accent=C_ACCENT, on_click=None, pad_px=16.0, dim=False,
                 font=None, enabled=True, **kwargs):
        super().__init__(parent=parent, position=(x, y, -0.02), **kwargs)
        self.w, self.h = w, h
        self._accent = accent
        self._dim = dim
        self._hover_t = 0.0
        self._active = False
        self._enabled = enabled
        self.action = on_click

        self.btn = Button(parent=self, model='quad', scale=(w, h),
                          color=rgba(C_PANEL_2, 236),
                          highlight_color=rgba(C_PANEL_HI, 246),
                          pressed_color=rgba(mix(C_PANEL_HI, accent, .22), 255),
                          highlight_scale=1, pressed_scale=1)
        self.btn.on_click = on_click if callable(on_click) else (lambda: None)

        pad = px(pad_px)
        self.bar = Entity(parent=self, model='quad', scale=(px(3), h * 0.58),
                          position=(-w / 2 + px(1.5), 0, -0.004), color=rgba(accent, 0))
        Entity(parent=self, model='quad', scale=(w, BT), position=(0, h / 2 - BT / 2, -0.004),
               color=rgba((255, 255, 255), 20))
        Entity(parent=self, model='quad', scale=(w, BT), position=(0, -h / 2 + BT / 2, -0.004),
               color=rgba((0, 0, 0), 120))

        origin = {'left': (-0.5, 0), 'right': (0.5, 0)}.get(align, (0, 0))
        tx = {'left': -w / 2 + pad + px(6), 'right': w / 2 - pad}.get(align, 0.0)
        lf = font or font_for(text, 'ui')
        self.label = Text(text=text, parent=self, position=(tx, 0, -0.01), origin=origin,
                          scale=fs(size_px, has_cjk(text) or lf == FONT_CJK),
                          color=rgba(C_TEXT_DIM if dim else C_TEXT, 235), font=lf)
        self._label_x = tx

        self.cap = None
        if hint:
            cap_h = min(24.0, h / px(1) * 0.52)
            self.cap = KeyCap(self, hint, x=0, y=0, h_px=cap_h, size_px=cap_h * 0.62)
            self.cap.x = w / 2 - pad - self.cap.w / 2

    def is_hovering(self):
        return getattr(self.btn, 'hovered', False)

    def set_active(self, flag: bool):
        self._active = bool(flag)
        self.label.color = rgba(TEXT_ON_ACTIVE, 245) if flag else rgba(
            C_TEXT_DIM if self._dim else C_TEXT, 235)

    def update(self):
        goal = 1.0 if (self._enabled and (self.is_hovering() or self._active)) else 0.0
        self._hover_t += (goal - self._hover_t) * min(1.0, time.dt * 16)
        k = self._hover_t
        self.bar.color = rgba(self._accent, 235 * k)
        self.bar.scale_x = px(3) * (0.5 + 0.5 * k)
        if self.label:
            base = C_TEXT_DIM if self._dim else C_TEXT
            self.label.color = rgba(mix(base, (255, 255, 255), 0.5 * k), 235)
            self.label.x = self._label_x + px(5) * k


def label(parent, text, size_px, x=0.0, y=0.0, origin=(-0.5, 0.0), col=C_TEXT,
          style='ui', alpha=255, z=-0.01, font=None) -> Text:
    font = font or font_for(text, style)
    return Text(text=text, parent=parent, position=(x, y, z), origin=origin,
                scale=fs(size_px, has_cjk(text) or font == FONT_CJK),
                color=rgba(col, alpha), font=font)


def spaced(text: str) -> str:
    """短英文标签加字距，贴近 CS:GO 排版习惯。"""
    if len(text) <= 6 and not has_cjk(text):
        return ' '.join(text)
    return text
