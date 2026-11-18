# -*- coding: utf-8 -*-
"""毛玻璃背景层：低分辨率离屏缓冲 + GLSL 采样着色器。

原理（不依赖 simplepbr / 后处理管线，失败时面板自动退化为纯色）
    1. ``base.win.makeTextureBuffer`` 建一个约为窗口 1/8 的低分辨率缓冲；
    2. 一台相机挂在 ursina ``camera`` 实体下、与主镜头共享同一个
       ``camera.perspective_lens``，把 3D 场景渲进缓冲（HUD 在独立的
       ui display region，不会被渲进去，也不会自我递归）；
    3. 低分辨率纹理被显卡双线性放大回屏幕 = 天然的背景模糊；
    4. 面板底 quad 挂一个小 GLSL 着色器，按 ``gl_FragCoord / 窗口尺寸``
       采样这张纹理（**与分辨率无关**，换任何分辨率采样位置都正确），
       再做去饱和 + 深色染色 + 半透明 alpha → 毛玻璃。

对比度：场景色乘约 0.32 的暗冷色调再叠加固定暗底，最亮的天空背景下
面板仍保持低亮度，原有的亮色 UI 文字（231,238,244）对比充足。

共享 shader 输入挂在 ``camera.ui`` 上（shader input 沿父链继承），
窗口尺寸变化时由 update() 钩子刷新并重建缓冲。
"""
from __future__ import annotations

from panda3d.core import Shader, Texture, TransparencyAttrib, Vec4
from ursina import Entity, camera

# 注意：`base` 是 ShowBase 实例化后注入的 builtin（ursina 命名空间里没有），
# 只能在运行时用裸名访问；游戏外导入本模块时 layer() 会失败并退化成纯色面板。

_VERT = '''
uniform mat4 p3d_ModelViewProjectionMatrix;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * gl_Vertex;
}
'''

# 画质档位可关闭毛玻璃（低配机省一次全屏低分辨率渲染）
ENABLED = True

_FRAG = '''
uniform sampler2D k_scene;
uniform vec2 k_win_size;
uniform vec4 k_tint;
void main() {
    vec2 uv = gl_FragCoord.xy / k_win_size;
    vec3 c = texture2D(k_scene, uv).rgb;
    // 轻度去饱和：毛玻璃的"磨砂"质感
    float lum = dot(c, vec3(0.299, 0.587, 0.114));
    c = mix(vec3(lum), c, 0.78);
    // 深色冷调染色 + 固定暗底，保证文字对比度
    c = c * k_tint.rgb + vec3(0.012, 0.016, 0.024);
    gl_FragColor = vec4(c, k_tint.a);
}
'''

# 缩放比例：缓冲尺寸 = 窗口 / DIV。数值越大模糊越强，8≈毛玻璃
DIV = 8


class _GlassLayer(Entity):
    """离屏模糊缓冲 + 共享着色器；Entity.update 每帧检查窗口尺寸。"""

    def __init__(self):
        super().__init__(parent=base.render, name='glass_layer', eternal=True)
        self.shader = Shader.make(Shader.SL_GLSL, _VERT, _FRAG)
        self.buffer = None
        self.cam = None
        self.texture = None
        self._win_size = (0, 0)
        self._pending = None
        self._pending_t = 0.0
        self._rebuild()

    # ------------------------------------------------------------ 缓冲
    def _rebuild(self):
        self._teardown()
        try:
            w = max(2, base.win.getXSize() // DIV)
            h = max(2, base.win.getYSize() // DIV)
            self.buffer = base.win.makeTextureBuffer('ui_blur', w, h)
            self.buffer.set_sort(-10)          # 先渲缓冲，主画面采到的是本帧
            tex = self.buffer.getTexture()
            tex.set_minfilter(Texture.FT_linear)
            tex.set_magfilter(Texture.FT_linear)
            tex.set_wrap_u(Texture.WM_clamp)
            tex.set_wrap_v(Texture.WM_clamp)
            self.texture = tex

            self.cam = base.makeCamera(self.buffer)
            self.cam.reparentTo(camera)                      # 跟随玩家视角
            self.cam.node().set_lens(camera.perspective_lens)  # 共享主镜头 FOV
        except Exception as exc:
            print('[毛玻璃] 离屏缓冲创建失败，面板退化为纯色：', exc)
            self._teardown()
            return

        self._win_size = (base.win.getXSize(), base.win.getYSize())
        self._push_inputs()

    def _push_inputs(self):
        """共享输入挂在 camera.ui：所有 UI 面板沿父链继承。"""
        camera.ui.setShaderInput('k_scene', self.texture)
        camera.ui.setShaderInput('k_win_size', self._win_size)

    def _teardown(self):
        if self.cam is not None:
            try:
                self.cam.removeNode()
            except Exception:
                pass
            self.cam = None
        if self.buffer is not None:
            try:
                self.buffer.clearRenderTextures()
                base.graphicsEngine.removeWindow(self.buffer)
            except Exception:
                pass
            self.buffer = None
        self.texture = None

    # ------------------------------------------------------------ 每帧
    def update(self):
        size = (base.win.getXSize(), base.win.getYSize())
        if size != self._win_size:
            if self._pending != size:
                self._pending = size
                self._pending_t = 0.0
            # 尺寸稳定 0.2 秒后再重建，避免拖拽窗口边框时反复建删缓冲
            self._pending_t += 1.0 / 60.0
            if self._pending_t > 0.2:
                self._pending = None
                self._rebuild()
        elif self._pending is not None:
            self._pending = None


_LAYER = None
_INIT_FAILED = False


def layer():
    """惰性取毛玻璃层；返回 None 表示不可用（调用方退化成纯色面板）。"""
    global _LAYER, _INIT_FAILED
    if _LAYER is None and not _INIT_FAILED:
        try:
            _LAYER = _GlassLayer()
            if _LAYER.texture is None:       # 缓冲没建起来
                _LAYER = None
                _INIT_FAILED = True
        except Exception as exc:
            print('[毛玻璃] 初始化失败，面板退化为纯色：', exc)
            _INIT_FAILED = True
    return _LAYER


def glass_quad(parent, w, h, x=0.0, y=0.0, z=0.0, alpha=0.80,
               tint=(0.32, 0.35, 0.41)):
    """毛玻璃底 quad。返回 None 表示毛玻璃不可用，调用方应退化为纯色。"""
    if not ENABLED:
        return None
    lay = layer()
    if lay is None:
        return None
    e = Entity(parent=parent, model='quad', scale=(w, h), position=(x, y, z))
    e.setShader(lay.shader)
    e.setShaderInput('k_tint', Vec4(tint[0], tint[1], tint[2], alpha))
    e.setTransparency(TransparencyAttrib.M_alpha)
    return e
