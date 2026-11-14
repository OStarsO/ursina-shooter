# 武器模型授权（均为 CC0 公共领域，可商用）

本项目 `weapons/models/` 下的五个 GLB 都来自 **Quaternius** 的
*Ultimate Guns Pack*，通过 poly.pizza 下载，授权为 **CC0 1.0 Universal（公共领域贡献）**。

| 文件 | 模型 | 来源页面 | 直接下载 | 授权 |
|------|------|----------|----------|------|
| `usp_pistol.glb` | Pistol（手枪，USP） | https://poly.pizza/m/52kQzphmeF | https://static.poly.pizza/7a31b522-5632-41d9-8274-031795af5d8d.glb | CC0 1.0 |
| `deagle_pistol.glb` | Pistol（手枪，沙漠之鹰） | https://poly.pizza/m/Z7aOjJu583 | https://static.poly.pizza/b0e55406-4b7b-486b-8af7-2d71c681791b.glb | CC0 1.0 |
| `ak47_rifle.glb` | Assault Rifle（突击步枪，AK-47） | https://poly.pizza/m/K2lXTYFSLC | https://static.poly.pizza/b3e6be61-0299-4866-a227-58f5f3fe610b.glb | CC0 1.0 |
| `awm_sniper.glb` | Sniper Rifle（狙击枪，AWM） | https://poly.pizza/m/i65hEldsw6 | https://static.poly.pizza/2def4aa0-1f3a-40dd-aa92-0661ce39ae50.glb | CC0 1.0 |
| `bayonet_knife.glb` | Bayonet（刺刀） | https://poly.pizza/m/D81P2smzCy | https://static.poly.pizza/e1d818e1-c3b2-41cd-b2bb-293de2c556ae.glb | CC0 1.0 |

- 作者：**Quaternius**（https://quaternius.com/ ，poly.pizza 上的作者页 https://poly.pizza/u/Quaternius ）
- 模型包：Ultimate Guns Pack（低多边形枪械合集）
- 页面标注原文：`Licence: Public Domain (CC0)` / `"Licence":"CC0 1.0"`，
  poly.pizza 页面同时注明 "ready to use in personal and commercial projects"。

## 署名要求

**无。** CC0 1.0 的作者已放弃全部著作权及邻接权，商用、修改、再分发都不需要署名，
也不需要开源本项目。这里保留出处仅为可追溯性与对作者的致谢。

## CC0 1.0 关键条款（摘要，非法律意见）

1. 作者在著作权法允许的最大范围内放弃对作品的一切权利，作品进入公共领域。
2. 可以复制、修改、发行、表演、展示作品，**包括商业目的**，无需许可或付费。
3. 无署名、无版权声明、无 copyleft 传染要求。
4. 不含专利与商标授权；不得暗示作者为本项目背书。
5. 官方文本：https://creativecommons.org/publicdomain/zero/1.0/legalcode

## 模型改动说明

为了适配第一人称视图模型，本项目对模型做了以下**运行时**处理（源文件未改动）：

- GLB 里的 PBR 材质（baseColorFactor 接近纯黑、alphaMode 混用）在
  `weapons/loader.py` 中重映射为引擎自带的 Blinn-Phong 材质，并按材质名套用
  枪械配色（`weapons/config.py: MATERIAL_PALETTE`）。
- 模型在加载后做居中 + 归一化（最长边 = 1），再按 `length` 缩放到手持尺寸。
- 朝向统一为「前向 +X、上方 +Y」，由 `rot` 里的 `rotation_y = -100°` 转到镜头前方。

## 未使用的内容

项目**没有**使用任何 Valve / CS:GO 的模型、贴图、音效或字体；
界面配色与排版是照着 CS:GO 的视觉语言自行绘制的，字体为 OFL 授权的
Rajdhani 与 Barlow Condensed（见 `fonts/OFL-*.txt`）。
