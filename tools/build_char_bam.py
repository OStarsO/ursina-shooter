# -*- coding: utf-8 -*-
"""把人物 GLB（含骨骼动画）预转换为 panda3d 原生 BAM。

为什么需要：
    panda3d 在打包（PyInstaller）环境下解析 glTF 内嵌动画时会触发
    animChannelMatrixXfmTable 的帧数断言（mismatched number of frames），
    导致 Actor 加载失败、人物模型消失。转成 BAM 后由 panda3d 原生
    bam 加载器读取，不再经过 gltf 解析，打包前后行为一致且启动更快。

用法（改过 models 后重跑一次）：
    py -3.11 tools/build_char_bam.py
输出：
    characters/soldier.bam（含全部 24 条骨骼动画）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from direct.actor.Actor import Actor  # noqa: E402

SRC = 'characters/soldier.glb'
DST = 'characters/soldier.bam'


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if not os.path.exists(SRC):
        print(f'源文件不存在：{SRC}')
        return 1
    actor = Actor(SRC)
    names = actor.getAnimNames()
    print(f'{SRC}: {len(names)} 条动画 → {DST}')
    actor.writeBamFile(DST)
    actor.cleanup()

    check = Actor(DST)
    got = check.getAnimNames()
    check.loop(got[0]) if got else None
    print(f'验证 {DST}: {len(got)} 条动画，'
          f"大小 {os.path.getsize(DST) / 1048576:.2f} MB")
    if len(got) != len(names):
        print('动画数量不一致，请检查')
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
