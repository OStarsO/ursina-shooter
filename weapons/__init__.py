# -*- coding: utf-8 -*-
"""武器模块：CC0 模型 + 第一人称视图模型 + 程序化检视动画。

    config    武器目录（模型路径、姿态、检视关键帧）—— 纯数据，可单测
    anim      关键帧采样 / 一次性轨道 / 指数缓动 —— 纯数学，可单测
    loader    GLB 加载、材质重映射、居中归一化
    viewmodel 装备、切枪、检视、后坐力、换弹、挥砍

模型授权见 weapons/LICENSES.md（全部 CC0 公共领域，可商用）。
"""
from .anim import Spring, Track, sample
from .config import CATALOG, ORDER, by_index, find

__all__ = ['CATALOG', 'ORDER', 'find', 'by_index', 'Track', 'Spring', 'sample']
