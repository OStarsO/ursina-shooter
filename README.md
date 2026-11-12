# 射击 · ursina-shooter

一个基于 [ursina](https://www.ursinaengine.org/) 的极简 3D 射击练习场，外加一个用 PySide6 写的**战术风格客户端启动器**：游客登录、模式选择、局域网联机房间（TCP 25250）、房主控制台与作弊指令。

> **许可证：PolyForm Noncommercial License 1.0.0 —— 仅限非商业用途。**
> 个人学习、研究、娱乐、教学与非营利组织使用均被允许；任何商业用途（含商用产品集成、付费分发、商业服务）需另行获得作者授权。详见 [LICENSE](LICENSE)。

---

## 功能一览

### 游戏（`射击.py`）
- **CS:GO 风格 HUD**：左下血量/护甲、右下弹药与武器名、顶部比分与计时、左上雷达、右上击杀提示、底部按键提示条
- **可调准星**：四线准星 + 开火扩散 + 命中/击杀标记 + 受伤方向指示 + 低血暗角
- **真实数值系统**：血量 / 护甲（按 CS:GO 规则吸收一半伤害）/ 弹匣与备弹 / 换弹进度 / 摔落伤害 / 死亡与重生
- **暂停菜单**：左侧导航 + 右侧内容（本局数据 / 设置 / 退出），设置项即时生效并写回 `settings.json`
- **Tab 计分板**：阵营分栏、本机行高亮、空槽位提示
- 第一人称移动（WASD / 空格跳跃 / 左键射击 / R 换弹 / Tab 计分板 / ESC 暂停）
- 打靶计分、目标方块随机刷新、枪口闪光与后坐力动效
- 读取启动器写入的 `settings.json`（分辨率 / 全屏 / 灵敏度 / 音量）与 `scores.json`（最高分）
- 兼容 ursina 7.x / 8.x（颜色 API、中文字体加载、暂停时光标状态均已适配）

### 启动器（`launcher.py` + `net_ui.py` + `room_net.py`）
- **游客登录**：输入昵称即进入，昵称持久化并可随时切换；邮箱登录页签已预留
- **环境自检**：探测可用 Python、ursina / panda3d 版本、中文字体与音效文件，异常时给出修复入口
- **模式选择**：训练场（本地单机）/ 单挑 1v1 / 团队竞技 5v5、10v10
- **局域网联机**：创建房间（监听 TCP 25250、可设密码、预配置目标比分与时长）或加入房间（扫描本网段所有 IP 的 25250 端口，也可手输房主 IP）
- **房间大厅**：红蓝分队、成员同步、房主开始/锁定/改密码，加入方等待开始信号自动进入游戏
- **房主控制台**：比赛控制、玩家作弊、机器人补位、房间管理四组命令，作弊指令始终向全员广播
- **工程化**：配置持久化、game 进程托管与日志、崩溃提示、单实例锁、一键打包 exe

---

## 运行要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 / 3.12 | 游戏端依赖 panda3d，目前**不支持 3.13+** |
| PySide6 | ≥ 6.5 | 启动器界面 |
| ursina | 7.x / 8.x | 游戏引擎（8.x 需 Python ≥ 3.12） |

```bash
pip install -r requirements.txt
python launcher.py          # 推荐：通过启动器进入
python 射击.py              # 也可直接运行游戏
```

启动器会自动在候选路径中寻找可用的 Python（已配置路径 → 游戏目录 `.venv` → 上级 `.venv` → 系统 Python 安装目录），无需手动指定。

---

## 游戏内界面（CS:GO 风格）

界面拆成三层，都是为了后续接联机时能单独替换：

| 模块 | 职责 |
|---|---|
| `ui_theme.py` | 配色、字体解析、程序化贴图（噪点/受光/辉光/暗角/雷达环/图标）、面板与按钮控件、锚点换算 |
| `hud.py` | 血量护甲、弹药、雷达、比分、击杀提示、准星与命中反馈 |
| `menu.py` | 暂停菜单（本局数据 / 设置 / 退出）与 Tab 计分板 |
| `combat.py` | 纯逻辑数值系统（血量/护甲/弹药/换弹/摔落伤害/回血） |

**设计要点**

- **尺寸统一用 900p 像素表达**：`ui_theme.px(n)` 把像素换算成 UI 单位（屏高 = 1），
  因此 1600×900、2560×1440、21:9 带鱼屏下观感一致；左右贴边靠 `ui_half_w()`（±aspect/2）锚定，窗口改比例会自动重排。
- **字体**：数字与英文用 Rajdhani / Barlow Condensed（窄体大写，最接近 CS:GO 观感），中文回退系统微软雅黑 / 黑体。
  Panda3D 对含中文的绝对路径加载失败，所以字体统一用 `fonts/xxx.ttf` 相对路径。
- **质感**：面板 = 深色底 + 顶部柔光 + 细噪点贴图 + 1px 描边 + 角标；噪点贴图在运行时用 Pillow 生成到 `ui_cache/`，不占仓库体积。
- 素材都是程序化生成的矩形/圆环/渐变，无任何受版权保护的商业素材。

**操作**

| 按键 | 作用 |
|---|---|
| WASD / 空格 | 移动 / 跳跃 |
| 左键 | 射击（连续射击会扩大准星扩散） |
| R | 换弹（弹匣空时开火会自动换弹） |
| Tab（按住） | 计分板 |
| ESC | 暂停菜单 |
| F1 / F2 | 自测：扣 22 血 / 补满血甲 |

**自检**

```bash
python 射击.py --selftest                          # 开火/换弹/暂停/计分板/死亡重生全链路
python 射击.py --shot hud.png --view hud           # 离屏出图（hud / pause / settings / score / quit）
python 射击.py --shot wide.png --view hud --size 2560x1080   # 验证超宽屏锚点
```


---

## 联机说明

```
房主：启动器内运行房间服务，监听 0.0.0.0:25250
      本机游戏进程连接 127.0.0.1:25250
加入方：扫描本网段所有 IP 的 25250（或手输房主 IP），
        成功后游戏进程直连 房主IP:25250
```

| | 房主（创建房间） | 加入方（加入房间） |
|---|---|---|
| 网络角色 | 服务端 + 玩家（权威端） | 纯客户端，不监听端口 |
| 25250 | 本机监听 | 主动连接房主 |
| 谁能开始 | 唯一，开始时向全员广播 | 只能等待开始信号 |
| 防火墙 | 需放行入站 TCP 25250 | 通常无需放行 |
| 退出影响 | 房间解散，全员回联机界面 | 仅自己离队 |

**连不上怎么办**
1. 确认双方在同一局域网（同一路由器 / 同一热点）。
2. 把房主机器的网络配置文件设为 **专用网络**（Windows 设置 → 网络和 Internet → 属性）；公用网络默认拦截入站。
3. 手动放行端口（管理员 PowerShell）：
   ```powershell
   New-NetFirewallRule -DisplayName "Shooting Room 25250" -Direction Inbound -Protocol TCP -LocalPort 25250 -Action Allow
   ```
4. 加入方仍连不上时，用 `ipconfig` 确认真实 IPv4，手动输入房主 IP（端口固定 25250，无需填写）。

---

## 控制台命令（仅房主）

在大厅点「打开控制台」即可输入，支持玩家名前缀匹配与 `all`。

**比赛控制**

| 命令 | 说明 |
|---|---|
| `score set red 5 blue 3` | 直接设置两队比分 |
| `score add blue 2` / `score reset` | 加分 / 清零 |
| `time 600` | 比赛时长（秒，0 = 无限时） |
| `end` / `restart` | 结束结算 / 重开一局 |

**玩家作弊**（始终全员广播）

| 命令 | 说明 |
|---|---|
| `god <玩家\|all>` / `god off` | 无敌开关 |
| `speed <玩家\|all> <倍数>` | 移动速度（0.5–5） |
| `damage <倍数>` | 全场伤害倍数（0.1–10） |
| `ammo inf on\|off` | 无限弹药 |
| `kill <玩家>` | 秒杀 |
| `tp <玩家> <x> <z>` | 传送 |
| `respawn <秒>` | 重生时间 |
| `bot add <红\|蓝> <n>` / `bot clear` | 机器人补位 / 清空 |

**房间管理**

| 命令 | 说明 |
|---|---|
| `kick <玩家>` / `ban <玩家>` | 踢出 / 踢出并禁止再进 |
| `lock on\|off` | 锁定房间 |
| `pwd <新密码\|off>` | 修改 / 取消密码 |
| `say <消息>` | 全员广播 |
| `status` / `help` | 房间状态 / 命令帮助 |

---

## 项目结构

```
├── 射击.py                 # ursina 游戏本体（含联机参数接收、--selftest / --shot 自检）
├── ui_theme.py             # CS:GO 风格主题层：配色 / 字体 / 程序化贴图 / 面板与按钮控件
├── hud.py                  # HUD：血量护甲、弹药、雷达、比分、击杀提示、准星与命中反馈
├── menu.py                 # 暂停菜单与 Tab 计分板
├── combat.py               # 数值系统：血量 / 护甲 / 弹药 / 换弹 / 摔落伤害
├── fonts/                  # Rajdhani + Barlow Condensed（OFL 1.1，含许可证文本）
├── launcher.py             # 启动器主程序：登录流程、环境自检、设置、进程托管
├── net_ui.py               # 登录 / 模式选择 / 建房 / 加入 / 房间大厅 / 控制台 UI
├── room_net.py             # 房间服务与客户端（纯标准库 TCP 实现）
├── app_style.py            # 启动器共享配色与控件样式
├── tests_room.py           # 协议层测试：47 项
├── tests_ui.py             # 大厅端到端测试：17 项
├── tests_combat.py         # 数值系统测试：29 项
├── assets/icon.(ico|png)   # 应用图标
└── dist/                   # 打包产物（未纳入版本库）
```

运行时生成的 `ui_cache/`（程序化 UI 贴图）与 `settings.json` / `scores.json` 均不入版本库。

协议：UTF-8、按行分隔的 JSON，端口固定 25250；消息类型详见 `room_net.py` 顶部注释。

## 测试

```bash
python tests_room.py    # 建房/密码/满员/扫描/全部命令/开始/踢人/解散
python tests_ui.py      # 大厅成员同步、控制台下发、双方自动启动、回大厅
python tests_combat.py  # 伤害与护甲公式、弹匣/换弹、回血、死亡与重生
python 射击.py --selftest   # 游戏内 UI 与状态链路
```

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "射击启动器" ^
  --icon "assets/icon.ico" --distpath dist --workpath build --specpath build ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick --exclude-module tkinter launcher.py
```

推 tag（`v*`）时 GitHub Actions 会自动构建 exe 并附到 Release（见 `.github/workflows/release.yml`）。

---

## 已知限制

- 游戏内的**联机对战同步**（位置/射击/命中/比分、作弊指令生效）尚未接入：当前联机只完成房间层，进入游戏后仍为本地练习，网络参数已传递到游戏侧。
- 单挑需 2 人；团队竞技允许房主在人数不足时开始（机器人可补位）。
- 引擎对 Python 3.13+ 暂无 panda3d 轮子，请使用 3.11 / 3.12。

## 第三方组件

- [ursina](https://github.com/pokepetter/ursina) — MIT
- [Panda3D](https://www.panda3d.org/) — BSD-3-Clause
- [PySide6 / Qt for Python](https://www.qt.io/qt-for-python) — LGPL-3.0
- [Rajdhani](https://fonts.google.com/specimen/Rajdhani) / [Barlow Condensed](https://fonts.google.com/specimen/Barlow+Condensed) — SIL Open Font License 1.1（许可证文本见 `fonts/OFL-*.txt`）

界面风格参考 CS:GO，但**未使用任何 Valve 的素材或字体**：配色与版式是重新设计的，
图标、噪点、圆环、暗角等贴图全部由代码在运行时绘制；CS:GO 原字体 Stratum2 为商业字体，未包含在本项目中。

本项目仅使用上述组件，未修改其源码；分发衍生作品时请一并遵守其许可证。

## 免责声明

本项目为个人学习作品，与任何商业游戏无关；不含任何受版权保护的商业素材。游戏音效 `hit.wav` 由启动器的「补齐音效」功能合成生成。

---

**License:** PolyForm Noncommercial 1.0.0 © 2026 OStarsO — 非商业使用免费，商业授权请联系作者。
