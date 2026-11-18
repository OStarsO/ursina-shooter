# -*- mode: python ; coding: utf-8 -*-
"""射击（游戏本体）打包配置 —— PyInstaller onedir。

为什么用 onedir 而不是 onefile：
    onefile 每次启动都要把几十 MB 资源解压到临时目录，且工作目录与
    资源相对路径容易错位，是"模型/贴图显示白色、贴图丢失"的常见根因。
    onedir 下资源与 exe 同批落地（_internal/），加载稳定、启动快。

资源约定（游戏内用相对路径读取，运行时工作目录切到 _MEIPASS）：
    characters/  sfx/  maps/  fonts/  weapons/models/  assets/

panda3d / ursina / direct / gltf 的包内数据（prc 配置、shader、内置模型、
字体）必须一起收集，否则打包后会出现白模、无字体、GLSL 报错。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ('characters', 'characters'),
    ('sfx', 'sfx'),
    ('maps', 'maps'),
    ('fonts', 'fonts'),
    ('weapons/models', 'weapons/models'),
    ('assets', 'assets'),
]

for _pkg in ('ursina', 'panda3d', 'direct', 'gltf'):
    datas += collect_data_files(_pkg)

hiddenimports = []
for _pkg in ('ursina', 'panda3d', 'direct', 'gltf'):
    hiddenimports += collect_submodules(_pkg)

a = Analysis(
    ['射击.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['PySide6', 'PyQt5', 'PyQt6', 'tkinter', 'matplotlib',
              'pytest', 'IPython', 'notebook'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='射击',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='射击',
)
