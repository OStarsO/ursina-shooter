# -*- coding: utf-8 -*-
"""GLB 模型加载：材质重映射 + 居中归一化。

为什么不用 simplepbr？
    simplepbr 会替换全局着色器管线，HUD 的纯色 UI、场景的 unlit 方块都要跟着改，
    收益（金属反射）在 2000 面的低模上几乎看不出来。所以这里把 glTF 的 PBR 材质
    "翻译"成引擎自带的 Blinn-Phong 材质，并套一层枪械配色。
"""
import os

from panda3d.core import (NodePath, Material, MaterialAttrib, TransparencyAttrib,
                          Vec4, Vec3, GeomNode)

from .config import MATERIAL_PALETTE, PALETTE_FALLBACK


def _linear_to_srgb(c):
    """glTF 基色是线性空间，Panda 的 legacy 管线按 sRGB 解释，直接换算一下。"""
    c = max(0.0, min(1.0, c))
    return pow(c, 1.0 / 2.2)


def _rgb(r, g, b):
    return Vec4(r / 255.0, g / 255.0, b / 255.0, 1.0)


def fix_materials(node, palette=None, shininess=42.0, specular=0.35,
                  keep_colors=False):
    """把 GLB 里的 PBR 材质换成场景统一的 Blinn-Phong 材质。

    keep_colors=True 时**不套调色板**，直接沿用 GLB 自带的基色
    （地图类资源自带真实配色，套枪械调色板会把颜色洗成灰）。
    返回被处理过的材质名列表，方便自检打印。
    """
    palette = None if keep_colors else (palette or MATERIAL_PALETTE)
    seen = []
    for gn in node.findAllMatches('**/+GeomNode'):
        gnode = gn.node()
        for i in range(gnode.getNumGeoms()):
            state = gnode.getGeomState(i)
            hidden = state.getAttrib(MaterialAttrib)
            name = hidden.getMaterial().getName() if hidden else ''

            if keep_colors:
                # 沿用 glTF baseColorFactor（panda3d-gltf 已填进 Diffuse，
                # 线性空间 → 引擎的 sRGB 解释需要换算一次）
                base = None
                if hidden:
                    d = hidden.getMaterial().getDiffuse()
                    if d is not None and (d.x + d.y + d.z) > 0.02:
                        base = Vec4(_linear_to_srgb(d.x), _linear_to_srgb(d.y),
                                    _linear_to_srgb(d.z), 1.0)
                if base is None:
                    base = _rgb(*PALETTE_FALLBACK)
            else:
                rgb = palette.get(name)
                if rgb is None:
                    rgb = PALETTE_FALLBACK
                base = _rgb(*rgb)

            mat = Material(f'mat_{name or "default"}')
            mat.setDiffuse(base)
            # 环境项压暗一点，纯环境光下也能看出体积
            mat.setAmbient(Vec4(base.x * 0.32, base.y * 0.32, base.z * 0.32, 1.0))
            mat.setSpecular(Vec4(specular, specular, specular * 1.06, 1.0))
            mat.setShininess(shininess)

            state = state.setAttrib(MaterialAttrib.make(mat))
            # glTF 里 alphaMode=BLEND 会让枪身半透明，这里强制不透明
            state = state.setAttrib(TransparencyAttrib.make(TransparencyAttrib.M_none))
            gnode.setGeomState(i, state)
            seen.append(name or 'default')
    return seen


def load_glb(path, center=True, palette=None, keep_colors=False):
    """加载 GLB 并挂到一个归一化的空节点上。

    keep_colors=True 保留 GLB 自带基色（地图用）；False 时套枪械调色板。
    返回的 NodePath：
        * 最长边 = 1（配合 config 里的 length 缩放成实际大小）——center=True 时
        * 几何中心在原点
        * 世界朝向不变（前向 +X，上方 +Y）
    """
    import gltf  # 延迟导入：没装 panda3d-gltf 时其它模块仍可 import

    node = NodePath(gltf.load_model(path))
    node.setName(os.path.basename(path))
    if keep_colors:
        fix_materials(node, keep_colors=True)
    else:
        merged = dict(MATERIAL_PALETTE)
        merged.update(palette or {})       # 单把武器可以覆盖个别材质颜色
        fix_materials(node, palette=merged)

    inner = NodePath(f'{os.path.basename(path)}_norm')
    node.reparentTo(inner)

    if center:
        mn, mx = node.getTightBounds()
        center_v = (mn + mx) * 0.5
        dims = mx - mn
        longest = max(dims.x, dims.y, dims.z) or 1.0
        node.setPos(inner, -center_v)
        inner.setScale(1.0 / longest)
    return inner
