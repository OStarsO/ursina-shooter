# 射击 · ursina-shooter

一个基于 [ursina](https://www.ursinaengine.org/) 的极简 3D 射击练习场，外加一个用 PySide6 写的**战术风格客户端启动器**：游客登录、模式选择、局域网联机房间（TCP 25250）、房主控制台与作弊指令。

> **许可证：PolyForm Noncommercial License 1.0.0 —— 仅限非商业用途。**
> 个人学习、研究、娱乐、教学与非营利组织使用均被允许；任何商业用途（含商用产品集成、付费分发、商业服务）需另行获得作者授权。详见 [LICENSE](LICENSE)。

---

## 功能一览

### 游戏（`射击.py`）
- **五件武器（CC0 模型）**：USP 手枪、沙漠之鹰、AK-47（全自动）、AWM 狙击枪（右键开镜）、刺刀，
  GLB 载入、材质重映射、`F` 键程序化检视
- **背包规则**：每人限带 匕首 + 副武器 + 主武器 各一件；`1`/`2`/`3` 对应 主武器 / 副武器 / 匕首，滚轮在已装备武器间循环
- **武器选择商店**：开局自动弹出、局内按 `B` 随时打开；主武器（AK/AWM）与副武器（USP/沙鹰）自由挑选，
  价格全部为 0（不启用经济系统）；训练场 / 单挑 / 团队全模式可用
- **备弹无限**：所有武器备弹显示 ∞，弹匣打完换弹即可，无需补给
- **每武器弹道手感**：后坐力（视角**向上**踢 + 按武器类型分级：手枪轻快 / 步枪连发上抬 / 狙击猛顶慢回）
  与子弹散布（基础角 + 连射热量 + 移动惩罚 + 开镜精度倍率），准星扩散实时反映精度状态
- **狙击开镜**：AWM 右键按住开镜（FOV 平滑过渡、镜内灵敏度随倍率降低、圆形镜片遮罩）
- **人物模型（CC0）**：Quaternius Soldier 士兵（24 条骨骼动画）装配在玩家实体上，
  panda3d Actor 驱动待机（持枪指向）/ 跑动（持枪跑）骨骼动画；第一人称隐藏自身模型，
  按 `V` 切第三人称可见；人机复用同一模型并按阵营着色
- **训练场木偶人靶**：木制人形靶（头 / 胸 / 躯干 / 四肢 / 底座），分部位伤害判定，
  一半固定一半巡航；被击倒后倒地翻滚并自动重生；团队模式刷蓝队染色木偶
- **分部位伤害（三区制）**：头部 ×4.0 / 胸+躯干 ×1.25 / 四肢 ×0.75，
  木偶人与玩家角色共用同一套倍率与结算入口（`combat.zone_damage`）；
  玩家被击中的部位按命中点离地高度划分（≥1.55m 头 / ≥0.75m 躯干 / 其下肢体）
- **人机（Bot）补齐**：PvP 单挑与团队竞技支持人机补齐房间——房主大厅
  「人机补齐」按钮按难度（简单 / 普通 / 困难）填满两队空位，控制台
  `bot add 红|蓝 n [难度]` 同样可用；人机会搜索玩家、按反应延迟与角度
  误差开火（高斯弹道），被击倒 3 秒重生；本地单挑/团队模式自动生成对手人机
- **服务器端反作弊验证**：对局内命中走 `hit_claim` 上报，服务器按武器配置表
  独立计算伤害与射速节流（超频 / 改伤害 / 鞭尸 / 伪造身份一律拒绝），
  权威比分 `score_update` 广播全员；被拒声明会在游戏内横幅提示
- **毛玻璃 UI**：所有面板背景为半透明磨砂玻璃（低分辨率离屏缓冲 + GLSL 采样），
  任意分辨率下采样正确、文字对比度充足；不支持时自动退化为纯色面板
- **对战地图（cube 拼装）**：启动器选「单挑」或「团队竞技」即加载代码生成的掩体地图
  （80×80 米，37 个方块：外周墙 + 12m 隐形边界、中央高台、两段错位走廊、对称箱体、
  两侧 L 形房间；红蓝各 3 个出生点）；几何数据 `cover_map.OBSTACLES` 与**服务端
  弹道共用同一份**，客户端渲染与服务端判定不会漂移
- **服务端权威联机**：游戏进程 `game_hello(token)` 长连，客户端 20Hz 上送
  位置/朝向/武器（`state`）与每次开火（`fire`）；服务端 `netsim` 以 20Hz 模拟
  玩家+机器人、按弹道与部位倍率算伤害/血量/比分，15Hz 下行快照（实体/事件/结算）；
  房主作弊指令 `cmd_apply` 与 `start`/`lobby` 同时送达游戏进程
- **服务端机器人**：房主大厅「人机补齐」的 BOT 由服务端模拟（巡逻/追击/高斯
  弹道/被击倒/3 秒复活），客户端只渲染快照；单机模式仍用本地 AI（同一套难度参数）
- **结算闭环**：比分达 `score_target` 或计时归零 → 结算页（红蓝比分 / 每位玩家
  K/D/A / MVP）→ 广播 `lobby` 回大厅；单机与联机共用同一套结算 UI 与流程
- **阵亡面板**：击杀者、武器、命中部位（头/躯干/肢体）、伤害、死因（击杀/坠落）、
  重生倒计时；可选「击杀者镜头」把镜头切到击杀者身后（设置项，默认关）
- **游戏内设置**：灵敏度、主/音效/界面音量分轨、准星四种样式（十字/圆点/T 形/粗十字）、
  画质档位（可视距离 + 毛玻璃开关）、分辨率切换即时生效、全屏、六项键位自定义；
  与启动器写同一份 `settings.json`（同源，双向生效）
- **成长系统（轻量）**：每局结算发 XP，12 级；升级解锁准星样式、武器涂装（数码迷彩/
  碳纤维）、玩家臂章；14 个成就（首杀/三杀/五连杀/爆头王/百场老兵/常胜将军/MVP/
  百人斩/全能选手/等级），达成时 HUD 横幅提示并在结算页展示；无经济/开箱/付费
- **战绩落盘**：每局结束立即原子写入 `profile.json`（胜负、最近 20 局、总场次、胜率、
  场均 KDA、各模式最佳、XP/等级/成就），并同步 legacy `scores.json`；
  训练场按平局计，避免刷胜率
- **CS:GO 风格 HUD**：左下血量/护甲、右下弹药与武器名、顶部比分与计时、左上雷达、右上击杀提示、底部按键提示条
- **命中反馈**：绿色十字准星常驻；红色命中标记仅在子弹命中物体或敌人时短暂闪现
- **音效**：每把武器使用**独立音色枪声**（USP 清脆短促 / 沙鹰厚重炮吼 / AK 连发
  脆响+拉栓 / AWM 低频轰鸣+回声尾 / 匕首挥砍扫掠），另有命中标记、换弹起始、
  装弹到位（CC0 真实录音加工）、切枪、切刀音效；全部可自由商用，
  授权明细见 `sfx/LICENSE.txt`，生成脚本 `tools/make_sfx.py` 可复现
- **输入法屏蔽**：游戏窗口创建时自动把输入法上下文摘除（`ImmAssociateContext`），
  中文输入法不再截获 R/B/F 等按键；只影响游戏窗口，其他程序不受影响，退出自动恢复
- **真实数值系统**：血量 / 护甲（按 CS:GO 规则吸收一半伤害）/ 弹匣与无限备弹 / 换弹进度 / 摔落伤害 / 死亡与重生
- **暂停菜单**：左侧导航 + 右侧内容（本局数据 / 设置 / 退出），设置项即时生效并写回 `settings.json`
- **Tab 计分板**：阵营分栏、本机行高亮、空槽位提示
- 第一人称移动（WASD / 空格跳跃 / 左键射击 / R 换弹 / F 检视 / 1~3 切枪 / B 商店 / 右键开镜 / V 第三人称 / Tab 计分板 / ESC 暂停）
- 打靶计分、目标方块随机刷新（伤害制：按武器伤害扣血、打空血才计分）、枪口闪光与后坐力动效
- 读取启动器写入的 `settings.json`（分辨率 / 全屏 / 灵敏度 / 音量）与 `scores.json`（最高分）
- 兼容 ursina 7.x / 8.x（颜色 API、中文字体加载、暂停时光标状态均已适配）

### 启动器（`launcher.py` + `net_ui.py` + `room_net.py`）
- **游客登录**：输入昵称即进入，昵称持久化并可随时切换；邮箱登录页签已预留
- **环境自检**：探测可用 Python、ursina / panda3d 版本、中文字体与音效文件，异常时给出修复入口
- **自动更新**：启动后自动查询 GitHub Releases 最新版本（也可在「我的」页手动点「检查更新」），
  发现新版本可一键下载、替换并自动重启；资产下载直连 GitHub 失败时按序切换加速镜像
- **依赖安装镜像优先**：创建 `.venv` 安装 ursina/panda3d 时依次探测清华 / 阿里云 / 腾讯云
  镜像（单源 5 秒超时），全部不可用或安装失败才回退官方 PyPI
- **模式选择**：训练场（本地单机）/ 单挑 1v1 / 团队竞技 5v5、10v10
- **局域网联机**：创建房间（监听 TCP 25250、可设密码、预配置目标比分与时长）或加入房间（扫描本网段所有 IP 的 25250 端口，也可手输房主 IP）
- **房间大厅**：红蓝分队、成员同步、人机补齐（三档难度）、房主开始/锁定/改密码，加入方等待开始信号自动进入游戏
- **房主控制台**：比赛控制、玩家作弊、机器人补位、房间管理四组命令，作弊指令始终向全员广播
- **工程化**：配置持久化、game 进程托管与日志、崩溃提示、单实例锁、一键打包 exe
  （启动器与游戏本体都可打包；游戏自带运行时，打包版无需本机 Python）
- **客户端自补齐游戏文件（v1.2.0）**：exe 只打包启动器本体；首次启动会先让你选择游戏文件保存位置，
  再从本仓库（`OStarsO/ursina-shooter`）下载补齐 `射击.py` 与 `assets/ fonts/ maps/ sfx/ characters/ weapons/`
  等运行所需文件（50 个文件、约 5.6 MB）。通道顺序 `codeload zip → api zipball → 逐文件`，
  路径无效 / 磁盘不足 / 下载失败都会给出明确提示，也可在「设置 → 选择路径 / 下载游戏文件」随时重补。
  命令行排错：`射击启动器.exe --fetch-game D:\Games\射击`（返回码 0 成功 / 2 路径无效 / 3 下载失败 / 4 缺入口文件）。

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
| 左键 | 射击（半自动按住只打一发；连续射击会扩大准星扩散；拿刀时是挥砍） |
| 右键（按住） | 狙击开镜（AWM；镜内灵敏度随倍率降低） |
| R | 换弹（弹匣空时开火会自动换弹；备弹无限；近战武器无需换弹） |
| F | 检视武器（再按一次提前收枪） |
| 1 / 2 / 3 或滚轮 | 切换 主武器 / 副武器 / 匕首（滚轮在已装备武器间循环） |
| B | 打开 / 关闭武器商店（价格全部为 0） |
| V | 第一 / 第三人称切换（第三人称可见人物模型与动画） |
| Tab（按住） | 计分板 |
| ESC | 关闭商店 / 暂停菜单（设置：准星 / 画质 / 分辨率 / 音量分轨 / 键位 / 击杀者镜头） |
| F1 / F2 | 自测：扣 22 血 / 补满血甲 |

**自检**

```bash
python 射击.py --selftest                          # 开火/半自动连发/备弹无限/配装/商店/后坐/检视/开镜/人物/暂停/计分板/死亡重生全链路
python 射击.py --selftest --map duel               # 单挑地图模式自检
python 射击.py --selftest --map team               # 团队竞技模式自检（出生点/阵营色/胜利判定）
python 射击.py --shot hud.png --view hud           # 离屏出图（hud / pause / settings / score / quit）
python 射击.py --shot ak.png --view ak             # 武器特写（usp / deagle / ak / awm / knife / scope / inspect）
python 射击.py --shot shop.png --view shop         # 武器商店界面
python 射击.py --shot third.png --view third       # 第三人称人物模型
python 射击.py --shot hit.png --view hit           # 命中标记闪现
python 射击.py --shot duel.png --view hud --map duel        # 加载 1v1 单挑地图出图
python 射击.py --shot wide.png --view hud --size 2560x1080  # 验证超宽屏锚点与毛玻璃采样
```

---

## 武器系统（模型 / 视图模型 / 检视动画）

### 引擎与渲染管线

引擎是 **ursina 8.x（底层 Panda3D）**。武器是 GLB 格式，通过
**panda3d-gltf**（`gltf.load_model`）在运行时载入——它返回的是 `ModelRoot`，
要自己包一层 `NodePath` 才能挂进场景图。

项目**没有引入 simplepbr**：HUD 是纯色 UI、场景是 unlit 方块，套一层 PBR
会把整套配色重做一遍，而 2000 面的低模上也看不出金属反射的差别。
所以 `weapons/loader.py` 走的是「材质翻译」路线：读 glTF 的
`pbrMetallicRoughness.baseColorFactor`，按材质名重映射成枪械配色
（glTF 里这些颜色接近纯黑，直接用会糊成一团），再生成 Blinn-Phong 材质，
顺手把 `alphaMode=BLEND` 带来的半透明清掉（否则枪身会透）。

灯也不打全场：一盏环境光 + 两盏方向光挂在视图模型节点下，**只照武器**，
场景和 HUD 完全不受影响。

### 目录与职责

```
weapons/
  config.py     武器目录：五件套数值、弹道（后坐/散布/开镜）、模型路径、手持姿态、检视/挥砍关键帧（纯数据）
  anim.py       关键帧采样、一次性动画轨道 Track、指数缓动 Spring（纯数学）
  loader.py     GLB 载入 + 材质重映射（keep_colors 保留原色）+ 居中归一化
  viewmodel.py  WeaponModel / Viewmodel：装备、切枪、检视、后坐、换弹、挥砍
  models/       usp / deagle / ak47 / awm / bayonet 五个 GLB（均为 CC0）
  LICENSES.md   五个模型的出处与 CC0 授权说明
```

### 层级设计（为什么动画不会「转到背后去」）

```
camera
└ viewmodel（补光灯也挂在这里）
  └ WeaponModel（容器）  位置 = 基础位置 + 动画位移，旋转 = 动画角度
    └ pivot              静态朝向 + 尺寸（模型已归一化成最长边 1）
      └ node             GLB 网格，几何中心在 pivot 原点
        └ muzzle         枪口，挂火光
```

旋转必须作用在**武器自身**的位置上（容器原点 = 枪身中心），否则绕光轴
转 90° 会让枪甩到镜头背后、直接看不见——这是调检视动作时踩过的坑，
`tests_weapons.py` 里用「动画偏航 ≤ 60°」把它钉成回归用例。

### 姿态与尺度

- 模型自身前向是 `+X`、上方 `+Y`；`rotation_y = -100°` 把它转到镜头前方，
  多出的 10° 让枪口微微向内收敛、指向准心（和 CS:GO 的手持观感一致）。
- 归一化后按 `length` 缩放到手持尺寸（手枪 0.26、匕首 0.32 世界单位），
  位置在 `pos` 里直接写「镜头右下方多少米」。
- 想换枪只要往 `CATALOG` 里加一条配置 + 一个 GLB，不需要改代码。

### 检视（F 键）与其它程序化动作

没有骨骼动画资源，全部是程序化姿态叠加：

| 动作 | 实现 |
|---|---|
| F 检视 | 关键帧轨道：抬枪 → 侧倾看左侧 → 停一拍 → 翻到右侧 → 回正（手枪 2.1s / 匕首 1.8s），再按一次 `stop()` 提前收枪 |
| 开火 | `recoil` 标量（1→0 衰减）驱动后坐位移 + 枪口上跳，枪口火光 55ms |
| 换弹 | 跟随 `combat.Weapon.reload_progress` 的 `sin` 曲线下压外翻 |
| 挥砍 | 关键帧轨道：起手外撇 → 向左下划过 → 收回（0.34s），配合 2.6 米射线判定 |
| 切枪 | 下压 0.16s → 换模型 → 上抬 0.24s，期间禁止开火 |
| 走路 / 甩枪 | 位移速度驱动 bob 相位，鼠标速度驱动 sway，都是指数缓动 |

关键帧插值用 `smoothstep`（两端速度为 0），所以起停没有线性插值的机械感。

### 资源授权

武器模型全部为 **CC0 1.0（公共领域）**，来自 Quaternius 的 *Ultimate Guns Pack*，
可商用、无需署名。出处、直链与改动说明见 [`weapons/LICENSES.md`](weapons/LICENSES.md)。

| 模型 | 出处 | 用途 |
|---|---|---|
| `usp_pistol.glb` | https://poly.pizza/m/52kQzphmeF | USP 手枪 |
| `deagle_pistol.glb` | https://poly.pizza/m/Z7aOjJu583 | 沙漠之鹰 |
| `ak47_rifle.glb` | https://poly.pizza/m/K2lXTYFSLC | AK-47 |
| `awm_sniper.glb` | https://poly.pizza/m/i65hEldsw6 | AWM 狙击枪 |
| `bayonet_knife.glb` | https://poly.pizza/m/D81P2smzCy | 刺刀 |

单挑/团队地图 `maps/duel_arena.glb`（fps/tps map，作者 theking1322）为
**CC-BY 3.0** 授权——免费且允许商用，唯一义务是保留署名；
本项目在 [`maps/LICENSES.md`](maps/LICENSES.md)、`arena.py` 注释与本页保留了署名与来源链接。

人物模型 `characters/soldier.bam`（由 `soldier.glb` 预转换，Quaternius 士兵，24 条骨骼动画）为
**CC0 1.0** 授权——可商用、无需署名；原作者 Quaternius（https://quaternius.com），
经 Cinevva CC0 角色库分发（https://app.cinevva.com/game-assets/free-3d-character-models），
许可文件与加工说明见 [`characters/LICENSE.txt`](characters/LICENSE.txt)。
BAM 由 `tools/build_char_bam.py` 生成（打包后 glTF 动画解析在冻结环境会触发帧数断言，
预转换后运行时走 panda3d 原生 BAM 加载，行为与源码模式一致）。

音效（`sfx/`，授权明细见 [`sfx/LICENSE.txt`](sfx/LICENSE.txt)）：
- 绝大多数为本项目 Python 标准库程序合成的原创音频（等同 CC0）：每把武器
  独立音色的枪声、命中标记、换弹起始、切枪、切刀
- 一条 CC0 第三方素材加工：`reload_done.wav`（OpenGameArt *Gun Reload Sound
  Effects*，Brian MacIntosh，峰值归一化 + 边缘淡入淡出）

![手枪视图模型](docs/weapon_pistol.png)
![匕首视图模型](docs/weapon_knife.png)
![手枪检视动作](docs/weapon_inspect.png)
![第三人称人物模型](docs/char_soldier.png)
![训练场木偶人靶](docs/dummies.png)


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

## 联机权威同步（服务端模拟）

```
客户端（游戏进程）                        服务端（房主启动器进程）
  每 20Hz  ── state 位置/朝向/武器 ──▶   netsim.World.set_state
  每次开火 ── fire 起点/方向 ────────▶   弹道：AABB 遮挡 + 胶囊命中
                                          射速节流（60/rpm×0.9）+ 部位倍率
  ◀── 15Hz snapshot 实体/血量/比分/事件 ─ 机器人 AI / 复活 / 计时 / 胜负
  ◀── cmd_apply（god/speed/damage/…） ─  房主控制台（同时同步到服务端世界）
  ◀── start / result / lobby ──────────  开局、结算与回大厅
```

- **判定权**：命中、伤害、血量、死亡、比分全部在服务端算；客户端只上报
  「我在哪、朝哪看、往哪打」，改伤害/超射速/穿墙在服务端弹道下不成立。
- **机器人**：服务端模拟（三档难度：反应/角度误差/射速/移速/伤害倍率），
  巡逻→发现→点射→被击倒→3 秒复活；客户端通过快照渲染（插值 + 队伍色环 + 昵称血条）。
- **结算**：`score_target` 达标或计时归零 → 服务端下发 `result`（红蓝比分 / KDA / MVP），
  客户端弹出结算页；8 秒后广播 `lobby` 回大厅（单机走同一套 `end_match()` 流程）。
- **命令**：`god/speed/damage/ammo_inf/kill/tp/respawn` 通过 `cmd_apply` 同时
  送达游戏进程与服务端世界（例如 `god` 既让客户端免疫也服务端免伤）。

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
| `bot add <红\|蓝> <n> [简单\|普通\|困难]` / `bot clear` | 机器人补位（可指定难度）/ 清空 |

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
├── ui_theme.py             # CS:GO 风格主题层：配色 / 字体 / 程序化贴图 / 毛玻璃面板控件
├── glass.py                # 毛玻璃背景层：低分辨率离屏缓冲 + GLSL 采样（失败退化为纯色）
├── hud.py                  # HUD：血量护甲、弹药、雷达、比分、击杀提示、准星、狙击镜遮罩
├── menu.py                 # 暂停菜单与 Tab 计分板
├── combat.py               # 数值系统：血量 / 护甲 / 弹药 / 换弹 / 近战 / 摔落伤害 / 分部位伤害倍率
├── arena.py                # （旧）duel_arena.glb 地图加载；现由 cover_map 取代，保留参考与 CC-BY 署名
├── dummies.py              # 木偶人训练靶：头/胸/躯干/四肢分部位判定、巡航与倒地重生
├── cover_map.py            # cube 拼装掩体地图：AABB 几何 + 出生点 + 场景构建（服务端共用）
├── netsim.py               # 服务端权威世界：机器人 AI / 弹道命中 / 血量 / 胜负 / 快照
├── remote_actors.py        # 远端实体渲染：快照插值 + 100ms 外推、队伍色环、昵称血条、死亡动画
├── growth.py               # 成长：XP/等级/解锁/14 个成就（纯逻辑，可单测）
├── docs/notices.json       # 远程公告数据（改这里即可热更新，无需重新打包）
├── bots.py                 # 人机：三档难度 AI（搜索/瞄准/高斯弹道）、阵营着色、击倒重生
├── maps/                   # duel_arena.glb + LICENSES.md（CC-BY 3.0 署名说明）
├── shop.py                 # 武器选择商店：开局弹出 + B 键呼出，主/副武器两栏，价格全部 0
├── characters/             # Quaternius Soldier 人物模型（CC0）：soldier.bam（运行时）/ soldier.glb（源）
├── tools/                  # 维护脚本：fix_glb / make_sfx / build_char_bam（GLB→BAM 预转换）/ upload_github
├── sfx/                    # 音效：自制合成 + CC0 第三方素材（明细见 LICENSE.txt）
├── weapons/                # 武器：配置（槽位/后坐力分级）/ 动画数学 / GLB 载入 / 视图模型 + models/ + LICENSES.md
├── fonts/                  # Rajdhani + Barlow Condensed（OFL 1.1，含许可证文本）
├── launcher.py             # 启动器主程序：登录流程、环境自检、设置、进程托管
├── net_ui.py               # 登录 / 模式选择 / 建房 / 加入 / 房间大厅 / 控制台 UI（含人机补齐）
├── room_net.py             # 房间服务与客户端（纯标准库 TCP 实现，含命中声明验证入口）
├── anticheat.py            # 服务器端反作弊：射速节流 / 伤害权威计算 / 重生窗口 / 身份约束
├── game_net.py             # 游戏进程实时通道：hit_claim 上报与权威比分接收
├── app_style.py            # 启动器共享配色与控件样式
├── updater.py              # GitHub Releases 自动更新：版本比较 / 资产镜像回退下载 / 自替换脚本
├── winfix.py               # 窗口状态保持补丁 + 输入法屏蔽（ImmAssociateContext）
├── tests_room.py           # 协议层测试：71 项（含反作弊 16 项 + 权威同步联调 8 项）
├── tests_update.py         # 自动更新测试：24 项（版本比较 / 资产选择 / 镜像回退 / 自替换脚本）
├── tests_netsim.py         # 服务端权威世界测试：34 项（弹道/部位/射速/机器人/胜负/快照/限速）
├── tests_growth.py         # 成长系统测试：39 项（XP/等级/成就/解锁/历史截断）
├── tests_ui.py             # 大厅端到端测试：17 项
├── tests_combat.py         # 数值系统测试：44 项（含分部位伤害倍率）
├── tests_weapons.py        # 武器配置 / 动画数学 / GLB 资源测试：55 项
├── tests_window.py         # 窗口位置/尺寸保持 + 输入法屏蔽测试：15 项（含 bug 复现对照组）
├── assets/icon.(ico|png)   # 应用图标
├── 射击.spec               # 游戏本体 PyInstaller 打包配置（onedir + 资源/data 收集）
└── dist/ dist_game/        # 打包产物（未纳入版本库）
```

运行时生成的 `ui_cache/`（程序化 UI 贴图）与 `settings.json` / `scores.json` 均不入版本库。

协议：UTF-8、按行分隔的 JSON，端口固定 25250；消息类型详见 `room_net.py` 顶部注释。

## 测试

```bash
python tests_room.py    # 建房/密码/满员/扫描/全部命令/开始/踢人/解散
python tests_ui.py      # 大厅成员同步、控制台下发、双方自动启动、回大厅
python tests_combat.py  # 伤害与护甲公式、弹匣/换弹、回血、死亡与重生
python tests_weapons.py # 武器配置/关键帧合法性/动画插值/GLB 结构/近战数值
python tests_window.py  # 窗口拖动/缩放后鼠标锁定切换不再还原（含 bug 复现对照）
python tests_update.py  # 自动更新：版本比较/资产筛选/镜像回退/替换脚本（无需联网）
python tests_netsim.py  # 服务端权威世界：弹道/部位倍率/射速/机器人/胜负/快照/限速（无需联网）
python tests_growth.py  # 成长：XP/等级/成就/解锁/历史 20 局上限（无需联网）
python 射击.py --selftest   # 游戏内 UI 与状态链路
```

## 客户端自动更新与发布

```
启动器启动 6 秒后自动检查（也可在「我的」页手动点「检查更新」）
  → GET https://api.github.com/repos/OStarsO/ursina-shooter/releases/latest
  → 解析 tag（v1.4.0）与资产列表，按语义化版本比较本地 APP_VERSION
  → 无更新：状态栏显示"已是最新版本"
  → 有更新：弹窗展示版本与更新说明
       打包运行：确认后下载 exe → 生成 _apply_update.bat → 退出 → 批处理
                 等待文件锁释放 → 覆盖 exe → 重启新版本 → 删除自身
       源码运行：只提示新版本与发布页（不替换开发目录）
```

- **资产下载镜像回退**：直连 `github.com/.../releases/download/...` 失败（超时 / 4xx / 连接重置）
  时，按 `ASSET_MIRRORS` 顺序尝试加速前缀（gh-proxy / ghfast），全部失败才报错；
  下载完整性用资产 `size` 校验，不完整一律判失败并清理 `.part`。
- **API 请求**：直连 GitHub API（镜像不代理 api 域名），带 `User-Agent`；
  404（仓库/Release 不存在）、403（限流）都会转成中文提示。
- **发布**：推 `v*` 标签 → GitHub Actions 构建启动器 exe 与游戏本体 zip；
  在 Release 上传 `ursina-shooter-launcher-vX.Y.Z.exe` 即被自动更新识别（资产名含
  `launcher`）。游戏本体（打包版）资源的大版本更新走 Release 里的 game zip，
  启动器的自动更新只替换启动器自身。

## 打包为 exe（启动器 + 游戏本体）

```bash
pip install pyinstaller

# 启动器（单文件，不含游戏资源，首次运行从 GitHub 补齐游戏文件）
# 注意：--specpath 会让生成的 spec 落在 build/，图标必须写绝对路径
pyinstaller --noconfirm --onefile --windowed --name "射击启动器" ^
  --icon "%CD%\assets\icon.ico" --distpath dist --workpath build --specpath build ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick --exclude-module tkinter launcher.py

# 游戏本体（onedir：exe + _internal 资源，内置 panda3d/ursina 运行时）
pyinstaller --noconfirm --distpath dist_game --workpath build_game 射击.spec
```

**资源白模 / 加载失败的修法**（本仓库已内置）：

1. **资源必须进包**：`射击.spec` 把 `characters/ sfx/ maps/ fonts/ weapons/models/ assets/`
   与 `panda3d / ursina / direct / gltf` 的包内数据（prc 配置、shader、内置模型/字体）
   全部 `collect_data_files` 收集——缺 panda3d 的 shader 会 GLSL 报错，缺 ursina 内置
   模型/字体会白模或字体丢失。
2. **运行时工作目录切到资源根**：`射击.py` 启动时把 cwd 切到 `sys._MEIPASS`
   （onedir 下为 `_internal/`），所有相对路径（`characters/soldier.glb` 等）才能命中。
3. **存档与资源分离**：`settings.json / scores.json` 写在 exe 同级目录（持久化），
   不写进 `_internal`（升级/清理不会丢档）。
4. **窗口程序无控制台**：打包后 `sys.stdout` 为 None，游戏内已兜底到空设备；
   自检结果用 `--selftest-log 结果.txt` 落盘，便于 CI / 无控制台环境验证资源加载。
5. **onefile vs onedir**：游戏本体用 onedir——onefile 每次启动解压几十 MB 且临时目录
   路径不稳定，正是白模/贴图丢失的高发场景。

验证打包结果（无需人工点界面）：

```bash
dist_game\射击\射击.exe --selftest --selftest-log dist_game\selftest.txt
dist_game\射击\射击.exe --shot dist_game\shot.png --view third
```

推 tag（`v*`）时 GitHub Actions 会自动构建 exe 并附到 Release（见 `.github/workflows/release.yml`）。

---

## 本轮改造清单（P0 / P1）

| 项 | 估量（新增/改动行） | 依赖 | 实现顺序 |
|---|---|---|---|
| P1-1 掩体地图 | ~260（`cover_map.py`） | 无 | 1 |
| P1-2 边界墙 | ~30（并入 cover_map：外周实体墙 + 12m 隐形墙 + 越界夹取/回出生点） | P1-1 | 1（同批） |
| P0-2 服务端机器人 | ~210（`netsim` 机器人 AI + 复活 + 难度表） | P1-1 几何 | 2 |
| P0-1 权威同步 | ~500（`netsim` 弹道/世界 400 + `game_net` 130 + `room_net` tick/广播 + 客户端接入） | P1-1 / P0-2 | 3 |
| P0-3 结算闭环 | ~190（`menu.ResultsPage` + `end_match` / 服务端 `_finish` / `lobby`） | 比分来源（P0-1、单机计时） | 4 |
| P1-3 死亡面板 | ~150（`menu.DeathPanel` + 死因记录 + 击杀者镜头） | 击杀来源（本地 bot / 服务端 kill 事件） | 4（与 P0-3 同批） |
| P1-4 设置增强 | ~280（菜单设置/键位页 + HUD 准星样式 + 画质/分辨率/音量总线） | HUD、窗口 | 5（可并行） |

依赖关系：P0-1 依赖地图几何（P1-1）与服务端实体（P0-2）；P0-3/P1-3 依赖击杀来源
（本地 AI 或 P0-1 的 kill 事件）；P1-4 相对独立，放最后避免与协议联调互相干扰。

## 本轮改造清单（A-1 ~ A-6，v1.4.0）

| 项 | 内容 | 主要落点 |
|---|---|---|
| A-1 结算立即落盘 | `end_match → _settle_match`：本局统计 → growth 结算 → 原子写 `profile.json`，不再依赖击杀时写盘；训练场按平局计（防刷胜率） | `射击.py`、`growth.py` |
| A-2 战绩结构扩展 | 场次/胜负/胜率/场均 KDA/爆头/MVP/最高连杀/各模式最佳/最近 20 局/XP/等级/成就；legacy `scores.json` 同步 | `growth.py`、`launcher.py`「我的」页 |
| A-3 控制台真实命令 | `help status version update launch open scores reset-settings repair sound join clear`，替换原三个占位 | `launcher.py` |
| A-4 设置同源 | 启动器新增准星/画质/涂装/击杀者镜头/音效/界面音量；与游戏共用 `settings.json`（含 keymap 等非数值字段），切页重读 | `launcher.py`、`射击.py` |
| A-5 公告热更新 | 拉 `docs/notices.json`（raw → jsDelivr → 镜像回退），缓存到 `%APPDATA%/ShootingLauncher/notices_cache.json`，离线回退缓存/内置 | `launcher.py`、`docs/notices.json` |
| A-6 登录页收敛 | 移除无服务端支撑的邮箱登录占位入口，登录页仅游客 + 本地存档说明 | `launcher.py` |

配套的成长与网络改动：`growth.py`（XP 12 级曲线、准星/涂装/臂章解锁、14 成就、HUD 横幅）；
`remote_actors` 100ms 速度外推（EMA + 限速 + 大跳变对齐）；`netsim` 服务端限速（超限夹取 +
`speed_warn` 下发 + 传送豁免）；`game_net` 发送队列 + 独立发送线程。

## 成长与战绩存档

```
每局结束 end_match() → _settle_match()
  ├─ 统计本局：击杀/死亡/爆头/最高连杀/MVP/时长（训练场按平局计）
  ├─ growth.apply_match()：XP、等级、解锁、成就判定
  ├─ save_profile()：profile.json 原子写入（退出/断电不丢本局）
  └─ 结算页展示：比分/KDA/MVP + XP/等级/本局成就
```

`profile.json` 字段：`xp level matches wins losses draws kills deaths assists
headshots mvps best_streak best_by_mode modes_played history[≤20] achievements skin
armband updated`。启动器「我的」页、控制台 `scores` 命令与结算页读同一份数据。

## 启动器控制台命令

`help` `status` `version` `update` `launch [training|duel|team5|team10]`
`open game|logs|config|dir` `scores` `reset-settings` `repair` `sound` `join` `clear`

## 公告热更新

公告默认从仓库 `docs/notices.json` 拉取（raw → jsDelivr → 镜像前缀依次回退），
成功后缓存到 `%APPDATA%/ShootingLauncher/notices_cache.json`；离线时显示缓存，
无缓存显示内置公告。改 `docs/notices.json` 并推送即可更新所有客户端，无需重新打包。
`config.json` 的 `notice_url` 可覆盖默认地址（自建公告源）。

## 网络稳健性

- **远端外推**：`remote_actors` 用相邻快照估计速度（EMA 平滑），按 100ms 外推
  渲染目标，限速 12m/s；大跳变（传送/复活）直接对齐，避免瞬移拖影。
- **服务端限速**：客户端状态水平位移/时间超过 `8×speed_mult×1.6+2` 时夹取回上一位置，
  记 `speed_hits` 并向该客户端下发 `speed_warn`（HUD 横幅提示），`tp` 后首帧豁免。
- **非阻塞发送**：`game_net._send()` 改为入队（容量 512），独立发送线程执行 sendall；
  队列满时丢弃旧 `state`、保 `fire`，主线程不再被网络阻塞。

## 已知限制

- **自动更新只替换启动器自身**：打包版游戏本体（`射击.exe` + `_internal`）体积大且
  升级时文件占用，需用 Release 里的 game zip 覆盖；源码运行时只提示新版本、不自动替换。
- 依赖安装镜像优先但**不强制**：镜像装失败会自动回退官方 PyPI，两者都不通才报错。
- **联机为「服务端权威判定 + 客户端权威移动」**：位置由各客户端上报、服务端只做
  边界夹取，未做移动速度校验与延迟补偿（回滚/插值）；因此瞬移类作弊仍靠
  `tp` 指令白名单外的行为难以检测，属下一阶段（服务器导航网格 + 速度上限校验）。
- 机器人跑在房主服务端（`netsim`），单机模式跑本地 AI；两者难度参数一致、
  但单机机器人不参与服务端比分。
- 键位自定义覆盖 换弹/商店/检视/第三人称/计分板/暂停 六项；移动仍固定 WASD
  （FPC 内部控制）。
- **邮箱登录入口已移除**：当前没有账号服务端，保留空页签会误导；账号/云存档接入后
  再以完整注册-登录-找回流程恢复（`net_ui.LoginDialog` 已留注释说明）。
- 训练场按平局计入战绩（无对手阵营），胜利/胜率只在单挑与团队模式累计。
- 服务端速度校验只夹取水平位置，不覆盖瞄准精度/瞬狙等行为；外推仅用于表现，
  命中判定始终以服务端弹道为准。
- 游戏窗口内输入法已被摘除（无法输入中文）——游戏本身没有任何文本输入框，无实际影响。
- 引擎对 Python 3.13+ 暂无 panda3d 轮子，请使用 3.11 / 3.12。

## 第三方组件

- [ursina](https://github.com/pokepetter/ursina) — MIT
- [Panda3D](https://www.panda3d.org/) — BSD-3-Clause
- [PySide6 / Qt for Python](https://www.qt.io/qt-for-python) — LGPL-3.0
- [Rajdhani](https://fonts.google.com/specimen/Rajdhani) / [Barlow Condensed](https://fonts.google.com/specimen/Barlow+Condensed) — SIL Open Font License 1.1（许可证文本见 `fonts/OFL-*.txt`）
- [panda3d-gltf](https://github.com/Moguri/panda3d-gltf) — MIT（GLB 载入）
- 武器模型：Quaternius *Ultimate Guns Pack*（USP / 沙漠之鹰 / AK-47 / AWM / 刺刀）— **CC0 1.0 公共领域**，出处见 [`weapons/LICENSES.md`](weapons/LICENSES.md)
- 人物模型：Quaternius 士兵 — **CC0 1.0 公共领域**（经 Cinevva CC0 角色库分发），见 [`characters/LICENSE.txt`](characters/LICENSE.txt)
- 单挑地图：theking1322 *fps/tps map* — **CC-BY 3.0**（署名见 [`maps/LICENSES.md`](maps/LICENSES.md)）
- 装弹音效：*Gun Reload Sound Effects*（Brian MacIntosh，OpenGameArt）— **CC0 1.0**（加工后使用）

> 本项目未使用任何 Valve / CS:GO 的模型、贴图、音效或字体；界面是照着 CS:GO 的视觉语言自行绘制的。

界面风格参考 CS:GO，但**未使用任何 Valve 的素材或字体**：配色与版式是重新设计的，
图标、噪点、圆环、暗角等贴图全部由代码在运行时绘制；CS:GO 原字体 Stratum2 为商业字体，未包含在本项目中。

本项目仅使用上述组件，未修改其源码；分发衍生作品时请一并遵守其许可证。

## 免责声明

本项目为个人学习作品，与任何商业游戏无关；除声明的 CC0 / CC-BY 素材外不含任何受版权保护的商业素材。游戏音效全部由 `tools/make_sfx.py` 程序合成（其中装弹到位音基于 CC0 录音素材加工），启动器另有「补齐音效」功能生成早期版本的 `hit.wav`（现已不再被游戏引用）。

---

**License:** PolyForm Noncommercial 1.0.0 © 2026 OStarsO — 非商业使用免费，商业授权请联系作者。
