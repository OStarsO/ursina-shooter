"""射击 —— ursina 3D 靶场射击（CS:GO 风格界面）。

界面分三层：
    ui_theme  配色 / 字体 / 程序化贴图 / 面板与按钮控件
    hud       血量护甲、弹药、雷达、比分、击杀提示、准星与命中反馈
    menu      暂停菜单与 Tab 计分板
数值系统（血量 / 护甲 / 弹药 / 换弹 / 摔落伤害）在 combat 里，
下一版接联机时把写入方换成网络事件即可。

命令行（启动器会传）：
    --net-mode/--host/--port/--nickname/--team/--token/--room-name/--mode/--players-json
    --shot <png> [--view hud|pause|score]   离屏出图，用于自检
"""
import json
import math
import os
import random
import sys as _sys

from panda3d.core import ClockObject, Filename
from ursina import *
from ursina.prefabs.first_person_controller import FirstPersonController

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 字体与贴图都用相对路径加载（Panda3D 对含中文的绝对路径不友好），
# 启动器已经把工作目录设成游戏目录，这里再兜底一次。
try:
    os.chdir(BASE_DIR)
except OSError:
    pass

import ui_theme as T
from ui_theme import px
import hud as HUD_MODULE
import menu as MENU
import arena as ARENA
import dummies as DUMMY_MODULE
import bots as BOTS_MODULE
import winfix
import shop as SHOP_MODULE
from combat import (Player, Weapon, Melee, ZONE_MULTIPLIERS, zone_damage,
                    classify_zone_by_height, ZONE_CN)
from weapons.config import (CATALOG as WEAPON_CATALOG, ORDER as WEAPON_ORDER,
                            by_index, spread_at, DEFAULT_LOADOUT, SLOTS)
from weapons.viewmodel import Viewmodel

# ===================== 联机参数（启动器传入） =====================
def parse_net_args(argv=None):
    """解析启动器传入的联机命令行参数（本版本只做展示）。"""
    argv = list(_sys.argv[1:] if argv is None else argv)
    keys = ('--net-mode', '--host', '--port', '--nickname', '--team',
            '--token', '--room-name', '--mode', '--players-json')
    info = {}
    i = 0
    while i < len(argv):
        key = argv[i]
        if key in keys and i + 1 < len(argv):
            info[key.lstrip('-')] = argv[i + 1]
            i += 2
        else:
            i += 1
    if info.get('net-mode'):
        try:
            info['port'] = int(info.get('port', 25250))
        except ValueError:
            info['port'] = 25250
        try:
            info['players'] = json.loads(info.get('players-json', '[]'))
        except ValueError:
            info['players'] = []
        info.pop('players-json', None)
        print('[联机] 模式:', info.get('net-mode'), '| 房间:', info.get('room-name'),
              '| 昵称:', info.get('nickname'), '| 队伍:', info.get('team'))
        print('[联机] 服务器:', info.get('host'), info.get('port'),
              '（联机对战同步将在下一版本接入，当前仍可本地练习）')
    return info


def parse_shot_args(argv=None):
    """自检用：--shot <png> [--view hud|pause|score] [--size 1600x900]。"""
    argv = list(_sys.argv[1:] if argv is None else argv)
    out, view, size = None, 'hud', None
    for i, a in enumerate(argv):
        if a == '--shot' and i + 1 < len(argv):
            out = argv[i + 1]
        elif a == '--view' and i + 1 < len(argv):
            view = argv[i + 1]
        elif a == '--size' and i + 1 < len(argv):
            try:
                w, h = argv[i + 1].lower().split('x')
                size = (int(w), int(h))
            except ValueError:
                size = None
    return out, view, size


NET_INFO = parse_net_args()
SHOT_PATH, SHOT_VIEW, SHOT_SIZE = parse_shot_args()
SELFTEST = '--selftest' in _sys.argv[1:]


def parse_map_arg(argv=None):
    """自检/截图用：--map duel 指定加载单挑竞技场。"""
    argv = list(_sys.argv[1:] if argv is None else argv)
    for i, a in enumerate(argv):
        if a == '--map' and i + 1 < len(argv):
            return argv[i + 1].lower()
    return None


MAP_ARG = parse_map_arg()

# 出图时直接把目标分辨率交给 Ursina 建窗：窗口建好后再 resize 会和
# lens/宽高比更新产生竞态，偶发截出"放大裁切"的 HUD。
app = Ursina(title='射击 · 靶场', borderless=False, development_mode=False,
             size=SHOT_SIZE or (1600, 900))
window.title = '射击 · 靶场'
window.borderless = False
window.exit_button.visible = False

# 首帧 dt 会把 Ursina() → app.run() 之间的全部加载耗时（GLB / 地图 / 字体 /
# 贴图生成）都算进去，低帧率下还会放大卡顿——序列(invoke)与动画会"一帧跳完"。
# 钳制单帧 dt 上限，加载再慢也只是慢放，不会跳变。
ClockObject.getGlobalClock().setMaxDt(1.0 / 30.0)

# ===================== 设置 / 战绩 =====================
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
SCORES_FILE = os.path.join(BASE_DIR, 'scores.json')

DEFAULT_SETTINGS = {
    'window_width': 1600,
    'window_height': 900,
    'fullscreen': False,
    'sensitivity': 40.0,
    'volume': 1.0,
}


def load_settings():
    """读取启动器写入的 settings.json，缺失或损坏时用默认值"""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in settings:
                if key in data and isinstance(data[key], (int, float, bool)):
                    settings[key] = data[key]
    except (OSError, ValueError):
        pass
    settings['window_width'] = int(max(800, min(3840, settings['window_width'])))
    settings['window_height'] = int(max(600, min(2160, settings['window_height'])))
    settings['sensitivity'] = float(max(5, min(200, settings['sensitivity'])))
    settings['volume'] = float(max(0.0, min(1.0, settings['volume'])))
    return settings


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(SETTINGS, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def save_score(current_score):
    """记录本局得分与历史最高分，供启动器展示"""
    try:
        data = {'best': 0, 'last': 0, 'updated': ''}
        if os.path.exists(SCORES_FILE):
            try:
                with open(SCORES_FILE, 'r', encoding='utf-8') as f:
                    old = json.load(f)
                if isinstance(old, dict):
                    data.update(old)
            except (OSError, ValueError):
                pass
        data['last'] = int(current_score)
        data['best'] = max(int(data.get('best', 0)), int(current_score))
        data['updated'] = time.strftime('%Y-%m-%d %H:%M')
        with open(SCORES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


SETTINGS = load_settings()
if not SHOT_PATH:                       # 出图时分辨率已固定，不要再 resize
    window.fullscreen = bool(SETTINGS['fullscreen'])
    if not SETTINGS['fullscreen']:
        window.size = (SETTINGS['window_width'], SETTINGS['window_height'])

# 修复：窗口拖动/缩放后被意外还原。上面这些 window 赋值（以及 ursina 启动时的
# center_on_screen）会把启动时刻的位置/尺寸写进 window(WindowProperties) 累加器；
# 此后每次 mouse.locked / mouse.visible 切换（点击继续、暂停、Tab 计分板、FPC
# 启停）都会 request_properties 把这些旧值重新下发给系统窗口。装上补丁后，
# 每次下发前先把系统窗口的"当前实际"状态写回累加器，用户的拖放不再被回滚。
# 详见 winfix.py 的根因分析与 tests_window.py 的复现对照。
winfix.install()

# ===================== 主题 / 字体 =====================
CJK_FONT = T.init_theme()
print('中文字体:', CJK_FONT, '| 英文字体:', T.FONT_NUM)

# ===================== 音效 =====================
# 枪声按武器独立（tools/make_sfx.py 合成，每枪音色差异显著）：
#   usp 清脆短促 / deagle 厚重炮吼 / ak 连发脆响+拉栓 / awm 低频轰鸣+回声
#   knife 挥砍扫掠；全部为项目原创音频，等同 CC0，可自由商用。
FIRE_SOUNDS = {}          # weapon key -> Audio


def _load_audio(path, name):
    """加载一条音效，失败返回 None（缺音效不影响游戏）。"""
    if not (os.path.exists(path + '.wav') or os.path.exists(path + '.ogg')):
        return None
    try:
        a = Audio(path, autoplay=False)
        return a if getattr(a, 'clip', None) is not None else None
    except Exception as e:
        print(f'音效 {name} 加载失败:', e)
        return None


for _k in ('usp', 'deagle', 'ak', 'awm', 'knife'):
    _snd = _load_audio(f'sfx/shot_{_k}', f'shot_{_k}')
    if _snd is not None:
        FIRE_SOUNDS[_k] = _snd
        try:
            _snd.volume = SETTINGS['volume'] * 0.9
        except Exception:
            pass
print(f"枪声: {', '.join(k for k in FIRE_SOUNDS) if FIRE_SOUNDS else '无'}")

# 命中标记音（sfx/hitmark.wav）与换弹起始音（sfx/reload.wav）：
# 用 Python 现场合成的短促音效，版权归本项目（等同 CC0，可自由商用）
hit_sound = _load_audio('sfx/hitmark', 'hitmark')
reload_sound = _load_audio('sfx/reload', 'reload')
# 切枪（布料+机械咔嗒）/ 切刀（金属鞘声）：Python 合成（自制等同 CC0）
switch_gun_sound = _load_audio('sfx/switch_gun', 'switch_gun')
switch_knife_sound = _load_audio('sfx/switch_knife', 'switch_knife')
# 装弹到位音：OpenGameArt「Gun Reload Sound Effects」by Brian MacIntosh（CC0）
reload_done_sound = _load_audio('sfx/reload_done', 'reload_done')
print(f'音效: hitmark={"有" if hit_sound else "无"} | reload={"有" if reload_sound else "无"}'
      f' | 切枪={"有" if switch_gun_sound else "无"} | 切刀={"有" if switch_knife_sound else "无"}'
      f' | 装弹={"有" if reload_done_sound else "无"}')

# ===================== 场景 =====================
Sky()
ground = Entity(model='plane', scale=100, color=color.rgb32(52, 58, 64),
                texture='white_cube', texture_scale=(100, 100), collider='box')

MODE_CN = {'training': '训练场', 'duel': '单挑', 'team5': '团队竞技 5v5',
           'team10': '团队竞技 10v10'}
MODE_NAME = MODE_CN.get(NET_INFO.get('mode') or NET_INFO.get('net-mode') or '', '训练场')
NICKNAME = NET_INFO.get('nickname') or '玩家'

# 地图模式：单挑（--mode duel / --map duel）或团队竞技（--mode team5/team10 /
# --map team），两者都使用 CC-BY 3.0 的 duel_arena.glb（来源见 arena.py 与
# maps/LICENSES.md）——这张图同时兼任 1v1 与团队对战地图
DUEL = bool(NET_INFO.get('mode') == 'duel' or MAP_ARG == 'duel')
TEAM = bool(NET_INFO.get('mode') in ('team5', 'team10') or MAP_ARG == 'team')
duel_arena = ARENA.load() if (DUEL or TEAM) else None
if duel_arena is None:
    DUEL = TEAM = False
if DUEL:
    MODE_NAME = '单挑竞技场'
elif TEAM:
    MODE_NAME = '团队竞技（红队）'

# 目标刷新范围：训练场开阔 / 地图收进墙内
if duel_arena is not None:
    AREA = ARENA.TARGET_AREA
    Y_MAX = ARENA.TARGET_Y_MAX
else:
    AREA = (-22, 22, -22, 22)
    Y_MAX = 7

# ===================== 玩家 / 数值 =====================
player = FirstPersonController()
player.speed = 8
player.gravity = 0.5
player.jump_height = 2
player.mouse_sensitivity = Vec2(SETTINGS['sensitivity'], SETTINGS['sensitivity'])
player.cursor.visible = False

state = Player(max_health=100, max_armor=100, start_armor=100)

# ===================== 人物模型（Quaternius Soldier · CC0） =====================
# 来源：Quaternius（https://quaternius.com），经 Cinevva CC0 角色库分发
#   https://app.cinevva.com/game-assets/free-3d-character-models
#   许可证 CC0 1.0（免费商用，无需署名；许可文件见 characters/LICENSE.txt）
# 用 panda3d Actor 加载 GLB 内嵌的骨骼动画（待机/跑动/死亡/受击），装配在
# 第一人称下隐藏自身模型，按 V 切第三人称可见，动画按移动速度切换。
third_person = False
character = None                 # panda3d Actor（失败时为 None，游戏照常可玩）
CHAR_ANIMS = {}                  # 角色动画名映射（idle / run / death …）
_char_current_anim = None

try:
    from direct.actor.Actor import Actor as PandaActor
    _char_actor = PandaActor('characters/soldier.glb')
    _char_actor.reparentTo(player)
    # 归一化身高到 1.8 米，脚底贴玩家原点（FPC 原点在脚）
    _mn, _mx = _char_actor.getTightBounds()
    _char_actor.setPos(0, 0, -_mn.z)
    _char_actor.setSz(1.8 / max(0.01, _mx.z - _mn.z))
    _char_actor.setH(180)        # 模型脸朝 +Y（glTF 前向），玩家前向是 +Z，转 180°
    _char_actor.hide()           # 第一人称看不到自己
    for _n in _char_actor.getAnimNames():
        if _n:
            CHAR_ANIMS[_n.lower()] = _n
    # 别名归一：Soldier 待机选持枪指向姿态（射击游戏观感），跑动选持枪跑
    CHAR_ANIMS['idle'] = (CHAR_ANIMS.get('idle_gun_pointing')
                          or CHAR_ANIMS.get('idle_gun')
                          or CHAR_ANIMS.get('idle', 'Idle'))
    CHAR_ANIMS['run'] = (CHAR_ANIMS.get('run_shoot') or CHAR_ANIMS.get('running')
                         or CHAR_ANIMS.get('run', 'Run'))
    CHAR_ANIMS['death'] = CHAR_ANIMS.get('death', 'Death')
    character = _char_actor
    print(f"[人物] Soldier 已装配 | 动画 {len(CHAR_ANIMS)} 条: "
          f"{', '.join(sorted(CHAR_ANIMS)[:8])}{'…' if len(CHAR_ANIMS) > 8 else ''}")
except Exception as _char_exc:
    print('[人物] Soldier 模型加载失败，继续无模型运行:', _char_exc)


def _set_char_anim(name):
    """切换角色动画（名字大小写不敏感），同名不重播。"""
    global _char_current_anim
    if character is None or name == _char_current_anim:
        return
    anim = CHAR_ANIMS.get(name)
    if anim:
        character.loop(anim)
        _char_current_anim = name


def toggle_third_person():
    """V 键：第一/第三人称切换（第三人称下人物模型可见）。"""
    global third_person
    if paused or not state.alive:
        return
    third_person = not third_person
    if character is not None:
        if third_person:
            character.show()
        else:
            character.hide()
    if scoping:                   # 第三人称没有镜片遮罩，顺带收镜
        set_scope(False)

# ===================== 目标方块 =====================
targets = []                        # 旋转方块靶（单挑模式 / 自检）
TARGET_HP = 100
TARGET_COLOR = color.rgb32(196, 74, 58)
TEAM_AREA = None
dummies = []                        # 木偶人靶（训练场 / 团队模式）
if TEAM:
    # 团队模式：目标是蓝队木偶人，刷在蓝队半场；先达到 VICTORY_SCORE 判胜
    VICTORY = ARENA.VICTORY_SCORE
    dummies.extend(DUMMY_MODULE.spawn_dummy_range(
        center=(0, 0, 24), count=6, spacing=3.4,
        tint=ARENA.TEAM_COLORS['blue']))
elif DUEL:
    # 单挑：保留红队方块靶（对方是人机/玩家的竞技场靶位），下面统一刷
    VICTORY = ARENA.VICTORY_SCORE      # 人机击倒玩家累计对方分数，先到判负
else:
    # 训练场：木偶人靶（一半固定一半巡航）取代旋转方块
    VICTORY = None                     # 训练场无胜负
    dummies.extend(DUMMY_MODULE.spawn_dummy_range(
        center=(-4, 0, -12), count=8, spacing=3.6))
match_won = False
blue_score = 0                     # 团队/单挑：对方阵营分数（人机击倒玩家累计）

# ===================== 人机（Bot） =====================
# 来源：房间成员列表里 is_bot 的成员（房主大厅里按难度添加），或本地
# 单挑/团队模式的默认对手。敌方人机会搜索玩家、按三档难度开火；
# 我方人机随队巡航（视觉补位）。人机命中玩家走同一套三区倍率。
bots = []
MY_TEAM = NET_INFO.get('team') or 'red'
ENEMY_TEAM = 'blue' if MY_TEAM == 'red' else 'red'


def _bot_hit_player(dmg, zone, bot):
    """人机命中玩家：三区倍率已在 bots 侧结算，这里扣血 + 受击方向 + 击杀提示。"""
    global blue_score, match_won
    if not state.alive:
        return
    dx = bot.root.world_position.x - player.world_position.x
    dz = bot.root.world_position.z - player.world_position.z
    ang = math.degrees(math.atan2(dx, dz)) - player.rotation_y
    state.take_damage(dmg)
    hud.on_damage(ang)
    # 联机：被人机击中的声明上报（target = 自己，允许的代报路径）
    if game_net is not None and bot.member_id and MY_MEMBER_ID is not None:
        game_net.hit_claim(bot.member_id, MY_MEMBER_ID, bot.weapon_key, zone)
    if not state.alive:
        blue_score += 10
        hud.push_kill(f'{NICKNAME}（{ZONE_CN[zone]}）', 0, killer=bot.name)
        save_score(state.score)
        if (TEAM or DUEL) and VICTORY and not match_won and blue_score >= VICTORY:
            match_won = True
            hud.banner('蓝队胜利！再接再厉', 2.6, T.C_DANGER)
            hud.push_kill('比赛结束', 0, killer='蓝队')


def _spawn_bots():
    """按房间配置 / 本地模式生成人机。"""
    positions = []
    difficulty_default = 'normal'
    if NET_INFO.get('net-mode'):
        # 联机：房间成员里 is_bot 且属于敌方阵营的成员 → 生成对应难度人机
        for p in NET_INFO.get('players') or []:
            if not isinstance(p, dict) or not p.get('is_bot'):
                continue
            if p.get('team') != ENEMY_TEAM:
                continue
            pos, yaw = (duel_arena.spawn_team(ENEMY_TEAM, len(positions))
                        if duel_arena else ((0, 2, 20 + len(positions) * 3), 0))
            _bot = BOTS_MODULE.Bot(
                name=p.get('nickname') or p.get('name') or 'BOT',
                team=ENEMY_TEAM,
                difficulty=p.get('difficulty') or difficulty_default,
                position=pos, heading=yaw,
                fire_audio=bot_fire_sound,
                on_hit_player=_bot_hit_player)
            _bot.member_id = p.get('id')
            bots.append(_bot)
    elif TEAM and duel_arena:
        # 本地团队：蓝队 3 人机（普通）占蓝队出生点
        for i in range(3):
            pos, yaw = duel_arena.spawn_team('blue', i)
            bots.append(BOTS_MODULE.Bot(
                name=f'BOT-B{i + 1}', team='blue', difficulty='normal',
                position=pos, heading=yaw,
                fire_audio=bot_fire_sound, on_hit_player=_bot_hit_player))
    elif DUEL and duel_arena:
        # 本地单挑：1 名普通人机对手
        pos, yaw = duel_arena.spawn_team('blue', 0)
        bots.append(BOTS_MODULE.Bot(
            name='BOT-DUEL', team='blue', difficulty='normal',
            position=pos, heading=yaw,
            fire_audio=bot_fire_sound, on_hit_player=_bot_hit_player))


# 人机远场枪声：独立加载 AK 音色的低音量实例（人机当前持 AK）
bot_fire_sound = _load_audio('sfx/shot_ak', 'bot_fire')
if bot_fire_sound is not None:
    try:
        bot_fire_sound.volume = SETTINGS['volume'] * 0.5
    except Exception:
        pass
_spawn_bots()

# ===================== 游戏内联机通道（命中上报 / 权威比分） =====================
# 对局中通过 game_hello(token) 接入房主 25250：击倒人机 / 被人机击中都会
# 上报 hit_claim，由服务器 anticheat 验证后广播权威比分；本地模式无此通道。
game_net = None
MY_MEMBER_ID = None
for _p in NET_INFO.get('players') or []:
    if isinstance(_p, dict) and _p.get('nickname') == NICKNAME and not _p.get('is_bot'):
        MY_MEMBER_ID = _p.get('id')
        break
if NET_INFO.get('net-mode') and NET_INFO.get('token') and MY_MEMBER_ID is not None:
    from game_net import GameNet
    game_net = GameNet(NET_INFO.get('host', '127.0.0.1'),
                       NET_INFO.get('port', 25250), NET_INFO['token'])
    game_net.start()
    print('[联机] 游戏通道已接入', NET_INFO.get('host'), NET_INFO.get('port'))


def spawn_target():
    """随机刷新目标：训练场/单挑全场刷；团队模式只刷在蓝队半场。"""
    area = TEAM_AREA if TEAM_AREA is not None else AREA
    # 团队模式目标在对方半场（10~60 米），其余模式 8~24 米
    near, far = (100, 3600) if TEAM_AREA is not None else (64, 576)
    x = z = 0
    for _ in range(24):
        x = random.randint(area[0], area[1])
        z = random.randint(area[2], area[3])
        d2 = (x - player.x) ** 2 + (z - player.z) ** 2
        if near < d2 <= far:
            break
    y = random.randint(1, Y_MAX)
    target = Entity(model='cube', color=TARGET_COLOR,
                    position=(x, y, z), scale=1.4, collider='box')
    target.hp = TARGET_HP                 # 目标有血量：按武器伤害扣，扣完才击杀
    targets.append(target)


for _ in range(10):
    if DUEL:                          # 只有单挑刷方块靶；训练场/团队用木偶人
        spawn_target()

# ===================== 武器：视图模型 + 数值 =====================
# 五件套全部从 weapons/config.py 装配（弹匣/伤害/射速/自动模式都走配置），
# ARMS 里放每把武器的数值对象，HUD 直接读它；模型与姿态在 config 里。
ARMS = {}
for _key in WEAPON_ORDER:
    _spec = WEAPON_CATALOG[_key]
    if _spec['kind'] == 'melee':
        ARMS[_key] = Melee(_spec['name'], damage=_spec.get('damage', 55), reach=2.6)
    else:
        ARMS[_key] = Weapon(_spec['name'], **_spec['ammo'])
        ARMS[_key].infinite_reserve = True   # 备弹无限：打完弹匣换弹即可，无需补给
    ARMS[_key].heat = 0.0             # 连射散布热量（度），见 spread_at()
weapon = ARMS['usp']

# ---- 背包规则：每人限带 匕首 + 副武器 + 主武器 各一件 ----
# LOADOUT 记录当前配装；只有这三把可以切换，其余武器存在但不可装备，
# 想换武器走武器商店（B 键 / 开局弹出），价格全部为 0。
LOADOUT = dict(DEFAULT_LOADOUT)

# ---- 射击状态（后坐力 / 散布 / 开镜） ----
fire_latch = False                    # 半自动：按住左键只打一发
_prev_reloading = False               # 上帧换弹状态（装弹完成音检测用）
recoil_pitch = 0.0                    # 待回落的后坐俯仰（度）
recoil_yaw = 0.0                      # 待回落的后坐偏航（度）
scoping = False                       # AWM 开镜中
BASE_FOV = camera.fov                 # 正常视野（开镜时往 zoom_fov 过渡）


def on_weapon_switch(key, spec):
    """切枪回调：换掉全局 weapon 引用，并同步 HUD 的弹药面板与准星。"""
    global weapon, scoping
    weapon = ARMS[key]
    if scoping:                        # 换枪强制收镜
        scoping = False
        hud.set_scoping(False)
        camera.fov = BASE_FOV
    # 切换音效：切刀是金属鞘声，切枪是布料+机械咔嗒
    _sfx = switch_knife_sound if spec['kind'] == 'melee' else switch_gun_sound
    if _sfx:
        _sfx.play()
    hud.set_weapon(weapon, spec['kind'])
    hud.banner(spec['name'], 0.7, T.C_TEXT_DIM)


def owned_keys():
    """当前配装里的三把武器 key（主 / 副 / 匕首）。"""
    return (LOADOUT['primary'], LOADOUT['side'], LOADOUT['melee'])


viewmodel = Viewmodel(camera, on_switch=on_weapon_switch)
viewmodel.set_available(owned_keys())     # 背包规则：只有配装里的武器可切换
weapon = ARMS[viewmodel.active_key]

# 地图模式出生点：单挑 → 1 号点；团队 → 红队底线 1 号位（面向蓝队半场）
if TEAM:
    _pos, _yaw = duel_arena.spawn_team('red', 0)
    player.position = _pos
    player.rotation_y = _yaw
elif DUEL:
    _pos, _yaw = duel_arena.spawn(1)
    player.position = _pos
    player.rotation_y = _yaw

# ===================== 界面 =====================
hud = HUD_MODULE.HUD(state, weapon, mode_name=MODE_NAME)
hud.set_weapon(weapon, viewmodel.kind)
if NET_INFO.get('net-mode'):
    team_cn = {'red': '红队', 'blue': '蓝队'}.get(NET_INFO.get('team', ''), '')
    info = (f"房间「{NET_INFO.get('room-name', '')}」 · {NICKNAME} · {team_cn} · "
            f"{NET_INFO.get('host', '')}:{NET_INFO.get('port', 25250)}")
    hud.set_room_info(info)

paused = False


def apply_setting(key, value):
    """设置项立即生效并写回 settings.json（启动器也读这个文件）。"""
    SETTINGS[key] = value
    if key == 'sensitivity':
        player.mouse_sensitivity = Vec2(float(value), float(value))
    elif key == 'volume':
        for _snd in list(FIRE_SOUNDS.values()) + [
                bot_fire_sound, hit_sound, reload_sound, reload_done_sound,
                switch_gun_sound, switch_knife_sound]:
            if _snd is not None:
                try:
                    _snd.volume = float(value) * (0.5 if _snd is bot_fire_sound else 0.9)
                except Exception:
                    pass
    elif key == 'fullscreen':
        window.fullscreen = bool(value)
    save_settings()


def _stats():
    total = int(hud.elapsed)
    return {
        'score': state.score,
        'kills': state.kills,
        'deaths': state.deaths,
        'time': f'{total // 60}:{total % 60:02d}',
    }


def _score_rows():
    total = int(hud.elapsed)
    rows = [{'name': NICKNAME, 'team': 'T', 'kills': state.kills,
             'deaths': state.deaths, 'assists': state.assists, 'ping': 0, 'self': True}]
    for p in NET_INFO.get('players') or []:
        if isinstance(p, dict) and p.get('name'):
            rows.append({'name': p.get('name'), 'team': 'CT' if p.get('team') == 'blue' else 'T',
                         'kills': p.get('kills', 0), 'deaths': p.get('deaths', 0),
                         'assists': p.get('assists', 0), 'ping': p.get('ping', 0)})
    return {'title': MODE_NAME, 'sub': 'TRAINING', 'rows': rows,
            'score': f'{state.score} 分 · {total // 60}:{total % 60:02d}'}


pause_menu = MENU.PauseMenu(settings=SETTINGS, on_resume=lambda: toggle_pause(False),
                            on_quit=lambda: application.quit(),
                            on_setting=apply_setting, stats_provider=_stats)
scoreboard = MENU.Scoreboard(provider=_score_rows)


def toggle_pause(force=None):
    global paused
    paused = not paused if force is None else bool(force)
    if paused:
        if shop.visible:               # 暂停时顺带收起商店
            shop.close()
        player.enabled = False
        mouse.locked = False
        mouse.visible = True
        pause_menu.show()
    else:
        pause_menu.hide()
        player.enabled = state.alive
        player.cursor.enabled = False
        mouse.locked = state.alive
        mouse.visible = not state.alive


# ===================== 武器商店 / 配装 =====================
def equip_from_shop(slot, key):
    """商店装备回调：写入配装、收窄可切换集合并切换到新武器。

    背包规则在这里强制：无论点多少次，每个槽位永远只有一件。
    """
    if slot not in ('primary', 'side') or key not in SLOTS.get(slot, ()):
        return
    if LOADOUT[slot] == key:
        return                          # 已经装备着
    LOADOUT[slot] = key
    viewmodel.set_available(owned_keys())
    shop.refresh()
    spec = WEAPON_CATALOG[key]
    hud.banner(f"已装备 {spec['name']}", 0.9, T.C_OK)
    if viewmodel.active_key != key:
        switch_weapon(key)


def open_shop():
    if paused or not state.alive:
        return
    shop.open()
    mouse.locked = False                # 商店里要用鼠标点
    mouse.visible = True


def close_shop():
    shop.close()
    if not paused and state.alive:
        mouse.locked = True
        mouse.visible = False


shop = SHOP_MODULE.Shop(on_pick=equip_from_shop,
                        loadout_getter=lambda: LOADOUT)


# ===================== 射击 =====================
def kill_target(entity, points=10):
    """击杀一个目标：加分、推送提示、延时补刷；团队模式达到胜利分判胜。"""
    global match_won
    if entity not in targets:
        return False
    targets.remove(entity)
    destroy(entity)
    state.score += points
    state.kills += 1
    hud.on_fire(hit=True, kill=True)
    hud.push_kill('目标', points)
    save_score(state.score)
    if hit_sound:
        hit_sound.play()
    # 团队模式胜利条件：先打到 VICTORY_SCORE 分的阵营获胜
    if TEAM and not match_won and state.score >= VICTORY:
        match_won = True
        hud.banner(f'红队胜利！目标 {VICTORY} 分达成', 2.6, T.C_OK)
        hud.push_kill('比赛结束', 0)
    invoke(spawn_target, delay=0.5)
    return True


def hit_target(entity, dmg):
    """命中目标：按武器伤害扣血，扣完才算击杀（原来是一枪一个）。"""
    if entity not in targets:
        return False
    entity.hp -= dmg
    if hit_sound:
        hit_sound.play()
    if entity.hp <= 0:
        kill_target(entity)
    else:
        hud.on_fire(hit=True)
        # 受击白闪一下，读得出"打中了但没死"
        entity.color = color.white
        invoke(lambda e=entity: setattr(e, 'color', TARGET_COLOR), delay=0.07)
    return True


def hit_dummy(dummy, part_entity, base_damage):
    """命中木偶人：按部位倍率结算（同一套 combat.zone_damage）。

    击倒计 10 分（击杀部位写入击杀提示）；团队模式计入胜利分。
    """
    global match_won
    if dummy is None or not dummy.alive:
        return False
    zone = part_entity.dummy_part
    killed, dmg = dummy.take_damage(base_damage, zone)
    if hit_sound:
        hit_sound.play()
    if killed:
        state.score += 10
        state.kills += 1
        hud.on_fire(hit=True, kill=True)
        hud.push_kill(f'木偶人 · {ZONE_CN[zone]}', 10)
        save_score(state.score)
        # 团队模式胜利条件：击倒蓝队木偶同样累计到胜利分
        if TEAM and not match_won and state.score >= VICTORY:
            match_won = True
            hud.banner(f'红队胜利！目标 {VICTORY} 分达成', 2.6, T.C_OK)
            hud.push_kill('比赛结束', 0)
    else:
        hud.on_fire(hit=True)
    return True


def hit_bot(bot, hit_point, base_damage):
    """命中人机：命中点离地高度划部位（与人机打玩家同一判定），结算并计分。"""
    global match_won
    if bot is None or not bot.alive:
        return False
    zone = classify_zone_by_height(hit_point.y - bot.root.world_position.y)
    killed, dmg = bot.take_damage(base_damage, zone)
    if hit_sound:
        hit_sound.play()
    hud.on_fire(hit=True, kill=killed)
    # 联机：命中声明交服务器验证（本地模式无服务器，跳过）
    if game_net is not None and bot.member_id and MY_MEMBER_ID is not None:
        game_net.hit_claim(MY_MEMBER_ID, bot.member_id, viewmodel.active_key, zone)
    if killed:
        state.score += 10
        state.kills += 1
        hud.push_kill(f'{bot.name}（{ZONE_CN[zone]}）', 10)
        save_score(state.score)
        # 团队/单挑胜利条件：击倒人机计入我方分数
        if VICTORY and not match_won and state.score >= VICTORY:
            match_won = True
            hud.banner(f'红队胜利！目标 {VICTORY} 分达成', 2.6, T.C_OK)
            hud.push_kill('比赛结束', 0)
    return True


def swing_knife():
    """近战：短距离射线，按刀伤害结算。"""
    if not weapon.fire():
        return
    viewmodel.swing_anim()
    _snd = FIRE_SOUNDS.get('knife')
    if _snd is not None:
        _snd.play()
    hit_info = raycast(camera.world_position, camera.forward, distance=weapon.reach)
    if hit_info.hit:
        _ent = hit_info.entity
        _dummy = getattr(_ent, 'dummy', None)
        _bot = getattr(_ent, 'bot_ref', None)
        if _bot is not None:
            hit_bot(_bot, hit_info.world_point, weapon.damage)
        elif _dummy is not None and _dummy.alive:
            hit_dummy(_dummy, _ent, weapon.damage)
        elif _dummy is None and _bot is None and _ent in targets:
            hit_target(_ent, weapon.damage)


def try_fire():
    """开火入口：半自动靠 fire_latch 锁住，弹道带每武器散布与后坐力。"""
    global fire_latch, recoil_pitch, recoil_yaw
    if paused or not state.alive or viewmodel.busy:
        return

    if viewmodel.kind == 'melee':
        if fire_latch:
            return
        fire_latch = True
        swing_knife()
        return

    if weapon.empty:
        weapon.start_reload()
        return
    if not weapon.auto and fire_latch:      # 半自动：松开左键前不再击发
        return
    if not weapon.fire():
        return
    fire_latch = True

    spec = viewmodel.spec
    viewmodel.fire_anim(spec.get('recoil', {}).get('vm', 1.0))
    _snd = FIRE_SOUNDS.get(viewmodel.active_key)      # 每把武器独立枪声
    if _snd is not None:
        _snd.play()

    # ---- 子弹散布（度）：基础 + 连射热量 + 移动惩罚，开镜乘 zoom_mult ----
    sp = spec.get('spread') or {}
    move_k = min(1.0, viewmodel._speed / max(1.0, player.speed))
    deg = spread_at(spec, heat=weapon.heat, move_k=move_k, zoomed=scoping)
    weapon.heat = min(weapon.heat + 1.0, 20.0)     # 每发积 1 点热量
    jitter = math.radians(deg)
    direction = (camera.forward
                 + camera.right * random.uniform(-jitter, jitter)
                 + camera.up * random.uniform(-jitter, jitter)).normalized()
    # 准星随散布张开（读得出精度状态）
    hud.crosshair.fire(px(1.6 + deg * 1.05), px(9.0 + sp.get('max', 5.0) * 2.2))

    hit_info = raycast(camera.world_position, direction, distance=100)
    if hit_info.hit:
        _ent = hit_info.entity
        _dummy = getattr(_ent, 'dummy', None)
        _bot = getattr(_ent, 'bot_ref', None)
        if _bot is not None:
            hit_bot(_bot, hit_info.world_point, weapon.damage)
        elif _dummy is not None:
            if _dummy.alive:
                hit_dummy(_dummy, _ent, weapon.damage)
            # 已倒地的木偶不重复结算，也不触发"打墙"反馈
        elif _ent in targets:
            hit_target(_ent, weapon.damage)
        else:
            # 打在世界物体上：同样给红色受击标记闪现 + 命中音（无伤害）
            hud.on_fire(hit=True)
            if hit_sound:
                hit_sound.play()

    # ---- 后坐力：视角向上抬（枪口上跳）+ 少量水平扰动，逐帧回落 ----
    # ursina 里 rotation_x 为正是"向下看"，所以上抬要减
    rec = spec.get('recoil') or {}
    kick = rec.get('kick', 1.0) * (0.55 if scoping else 1.0)
    yaw_kick = random.uniform(-0.35, 0.35) * kick * 0.4
    recoil_pitch += kick
    recoil_yaw += yaw_kick
    pivot = player.camera_pivot
    pivot.rotation_x = max(-89.0, pivot.rotation_x - kick)
    pivot.rotation_y += yaw_kick


def start_reload():
    if paused or not state.alive or viewmodel.busy:
        return
    if viewmodel.kind == 'melee':
        hud.banner('近战武器无需换弹', 0.8, T.C_TEXT_DIM)
        return
    if weapon.start_reload():
        viewmodel.reload_started()
        hud.banner('换弹中', 0.8, T.C_TEXT_DIM)
        if reload_sound:
            reload_sound.play()


def switch_weapon(key):
    """切到配装里的武器（数字键 1/2/3 与商店装备都走这里）。"""
    if paused or not state.alive:
        return
    viewmodel.switch_to(key)


def set_scope(on):
    """右键按住开镜（AWM：config 里有 zoom_fov 的武器才支持）。"""
    global scoping
    if paused or not state.alive:
        return
    if on and 'zoom_fov' not in viewmodel.spec:
        return
    if viewmodel.kind == 'melee':
        return
    scoping = bool(on)
    hud.set_scoping(scoping)


def respawn_player():
    if TEAM and duel_arena:
        player.position, player.rotation_y = duel_arena.spawn_team('red', 0)
    elif DUEL and duel_arena:
        player.position, player.rotation_y = duel_arena.spawn(1)
    else:
        player.position = (0, 2, 0)
    player.enabled = True
    player.cursor.enabled = False
    state.respawn(full_armor=True)
    if game_net is not None:
        game_net.respawn_done()
    for w in ARMS.values():
        w.refill()
        w.heat = 0.0
    hud.banner('重生', 1.1, T.C_OK)
    mouse.locked = True
    mouse.visible = False


peak_y = 0.0


def input(key):
    # ⚠ 这里对 fire_latch 的赋值必须有 global 声明：否则 Python 会把它当成
    # 局部变量，全局锁存永远停在 True——半自动武器打一发后永久哑火
    # （就是"手枪只能开一枪"的根因）。
    global fire_latch

    if key == 'escape':
        if shop.visible:               # 商店开着先关商店
            close_shop()
            return
        if scoreboard.visible:
            scoreboard.hide()
            mouse.locked = state.alive
            mouse.visible = not state.alive
            return
        toggle_pause()
        return

    if shop.visible:
        if key == 'b':
            close_shop()
        return

    if paused:
        return

    # 快速点击保护：down/up 可能在同一帧内发生（held_keys 在 update 里
    # 读不到），所以单击触发也走事件路径
    if key == 'left mouse down':
        try_fire()
    if key == 'left mouse up':
        fire_latch = False

    if key == 'tab':
        scoreboard.show()
        mouse.locked = False
        mouse.visible = True
        return
    if key == 'tab up':
        scoreboard.hide()
        mouse.locked = state.alive
        mouse.visible = not state.alive
        return

    if key == 'r':
        start_reload()

    # 配装切枪：1=主武器 2=副武器 3=匕首（只切已装备的，滚轮在装备内循环）
    if key.isdigit() and key in ('1', '2', '3'):
        slot = {'1': 'primary', '2': 'side', '3': 'melee'}[key]
        switch_weapon(LOADOUT[slot])
    elif key.isdigit() and key != '0':
        return                      # 4~9 没有对应槽位（背包规则限制三件）
    if key == 'scroll up':
        viewmodel.cycle(-1)
    if key == 'scroll down':
        viewmodel.cycle(1)

    # 右键按住开镜（仅 AWM 等 zoom_fov 武器）
    if key == 'right mouse down':
        set_scope(True)
    if key == 'right mouse up':
        set_scope(False)

    if key == 'b':
        open_shop()
    if key == 'v':
        toggle_third_person()

    if key == 'f':
        # 检视中再按一次 = 提前收枪（start_inspect 内部处理打断）
        viewmodel.start_inspect()
    if key == 'f1':
        state.take_damage(22)
        hud.on_damage(random.uniform(-180, 180))
    if key == 'f2':
        state.heal(100)
        state.add_armor(100)


# ===================== 主循环 =====================
def update():
    global peak_y, fire_latch, recoil_pitch, recoil_yaw, scoping
    global _prev_reloading, blue_score

    dt = time.dt
    if paused:
        return

    # ---- 后坐力回落：把开火时踢上去的视角按武器速度收回来 ----
    # 开火是 rotation_x -= kick（向上），回落就加回来
    if recoil_pitch > 0.0 or recoil_yaw != 0.0:
        recover = (viewmodel.spec.get('recoil') or {}).get('recover', 6.0) * dt
        dp = min(recoil_pitch, recover)
        dy = max(-recover, min(recoil_yaw, recover))
        pivot = player.camera_pivot
        pivot.rotation_x += dp
        pivot.rotation_y -= dy
        recoil_pitch -= dp
        recoil_yaw -= dy

    # ---- 非当前武器的冷却也要走（切枪回来不能还处于"刚打完"状态）----
    # 当前武器由 hud.update() 里的 w.update(dt) 推进，避免双倍推进
    for w in ARMS.values():
        if w is not weapon:
            w.update(dt)
        w.heat = max(0.0, w.heat - 5.0 * dt)   # 散布热量冷却

    # ---- 换弹完成：装弹到位音（弹匣咔嗒；换弹起始音在 start_reload 播）----
    if _prev_reloading and not weapon.reloading and reload_done_sound:
        reload_done_sound.play()
    _prev_reloading = weapon.reloading

    # ---- 开镜：FOV 平滑过渡 + 灵敏度随倍率降低 + 收起枪模 ----
    zoom_fov = viewmodel.spec.get('zoom_fov')
    target_fov = (zoom_fov if scoping and zoom_fov else BASE_FOV)
    if abs(camera.fov - target_fov) > 0.05:
        camera.fov += (target_fov - camera.fov) * min(1.0, dt * 12.0)
    player.mouse_sensitivity = Vec2(
        SETTINGS['sensitivity'] * (camera.fov / BASE_FOV),
        SETTINGS['sensitivity'] * (camera.fov / BASE_FOV))

    # 目标旋转 / 木偶人动画（巡航、倒地、重生）/ 人机 AI
    for target in targets:
        target.rotation_y += 0.5 * dt * 60
    for d in dummies:
        d.update(dt)
    if bots and state.alive:
        _tgt = camera.world_position
        for b in bots:
            b.update(dt, target_pos=_tgt, target_alive=state.alive)
    elif bots:
        for b in bots:                       # 玩家阵亡：人机停火巡航
            b.update(dt, target_pos=None)

    # 持续射击（半自动被 fire_latch 挡住，全自动连发）
    if held_keys['left mouse']:
        try_fire()

    # 摔落伤害
    if not player.grounded:
        peak_y = max(peak_y, player.y)
    else:
        drop = peak_y - player.y
        if drop > 5.0 and state.alive:
            dmg = (drop - 5.0) * 6
            state.take_damage(dmg, ignore_armor=True)
            hud.on_damage(180)
            hud.banner(f'坠落 -{int(dmg)}', 1.0, T.C_DANGER)
        peak_y = player.y

    # 掉出地图 → 直接判死，再走重生流程
    if player.y < -12 and state.alive:
        state.take_damage(999, ignore_armor=True)

    if not state.alive:
        player.enabled = False
        if mouse.locked:
            mouse.locked = False
            mouse.visible = True
        if state.death_time <= 0 and not paused:
            respawn_player()

    # ---- 第三人称（V）：镜头拉到人物身后，人物模型可见并按速度切动画 ----
    if third_person:
        camera.position = camera.position + (Vec3(0, 0.55, -3.2) - camera.position) * min(1.0, dt * 12)
    else:
        camera.position = Vec3(0, 0, 0)
    if character is not None and third_person:
        moving = viewmodel._speed > 1.5 and player.grounded
        _set_char_anim('run' if moving else 'idle')

    # 枪口闪光 / 后坐力 / 检视 / 换弹动画（开镜或第三人称时收起枪模）
    viewmodel.enabled = state.alive and not scoping and not third_person
    if state.alive and not scoping and not third_person:
        viewmodel.tick(dt, weapon, player)

    # ---- 联机：消费服务器权威比分 / 拒绝回执 ----
    if game_net is not None:
        while True:
            try:
                _msg = game_net.score_queue.get_nowait()
            except queue.Empty:
                break
            if _msg.get('t') == 'score_update':
                _stats = _msg.get('stats', {})
                _mine = _stats.get(str(MY_MEMBER_ID))
                if _mine:
                    state.score = int(_mine.get('score', state.score))
                _enemy_ids = [str(b.member_id) for b in bots if b.member_id]
                blue_score = sum(int(_stats.get(_e, {}).get('score', 0))
                                 for _e in _enemy_ids)
            elif _msg.get('t') == 'claim_reject':
                hud.banner(f'命中声明被服务器拒绝：{_msg.get("reason", "")}',
                           1.8, T.C_DANGER)

    hud.update(dt, player, targets)
    if scoreboard.visible:
        scoreboard.refresh()


# ===================== 自检出图 =====================
if SHOT_PATH:
    # 先注入一组能看出效果的数据（血量偏低 / 弹匣不满 / 有击杀提示），
    # 再由定时器切到目标界面并出图。
    state.health = 32
    state.armor = 68
    state.since_damage = 0.0
    state.score = 240
    state.kills = 24
    state.deaths = 3
    weapon.mag = 7
    hud.elapsed = 137
    hud.push_kill('目标', 10)
    hud.push_kill('目标', 10)
    hud.crosshair.fire()
    hud.on_fire(hit=True, kill=True)
    hud.on_damage(38)

    def _snap():
        # ursina 的 window.size 与 lens 更新有竞态：出图前强制对齐一次，
        # 否则偶发 ui_lens 还停在上一个宽高比，截出来的 HUD 会被放大裁切。
        a = base.win.getXSize() / max(1, base.win.getYSize())
        camera.ui_lens.setFilmSize(20.0 * a, 20.0)
        camera.lens.setAspectRatio(a)
        base.graphicsEngine.renderFrame()
        print('[shot] win', base.win.getXSize(), 'x', base.win.getYSize(),
              '| aspect', round(a, 3),
              '| ui_lens', [round(v, 3) for v in camera.ui_lens.getFilmSize()])
        ok = base.win.getScreenshot().write(Filename(SHOT_PATH))
        print('[shot]', SHOT_PATH, ok)
        application.quit()

    def _do_shot():
        # 武器特写：--view <武器key>（usp/deagle/ak/awm/knife）
        # 或 inspect / knifeinspect / scope（开镜）/ third（第三人称）/ shop（商店）
        if SHOT_VIEW in WEAPON_CATALOG:
            _slot = WEAPON_CATALOG[SHOT_VIEW].get('slot')
            if _slot in ('primary', 'side') and LOADOUT.get(_slot) != SHOT_VIEW:
                equip_from_shop(_slot, SHOT_VIEW)     # 不在配装里先走商店装备
            else:
                switch_weapon(SHOT_VIEW)
            invoke(_snap, delay=0.90)
            return
        if SHOT_VIEW == 'scope':
            if LOADOUT['primary'] != 'awm':
                equip_from_shop('primary', 'awm')   # 商店装备（内置切枪）
            else:
                switch_weapon('awm')
            invoke(lambda: set_scope(True), delay=0.45)
            invoke(_snap, delay=1.30)       # FOV 过渡完成 + 收起枪模后
            return
        if SHOT_VIEW == 'third':
            # 第三人称人物模型（Quaternius Soldier）：等镜头拉到身后再出图
            invoke(toggle_third_person, delay=0.30)
            invoke(_snap, delay=1.20)
            return
        if SHOT_VIEW == 'shop':
            invoke(open_shop, delay=0.30)
            invoke(_snap, delay=0.90)
            return
        if SHOT_VIEW == 'hit':
            # 命中标记闪现验证：出图时刻应正好落在红色标记的显示窗口内
            invoke(lambda: hud.on_fire(hit=True, kill=False), delay=0.30)
            invoke(_snap, delay=0.34)
            return
        if SHOT_VIEW in ('knife', 'knifeinspect', 'inspect'):
            if SHOT_VIEW == 'inspect':
                viewmodel.start_inspect()
                invoke(_snap, delay=0.80)          # 检视 34% 处：侧倾展示
                return
            switch_weapon('knife')
            if SHOT_VIEW == 'knifeinspect':
                invoke(viewmodel.start_inspect, delay=0.60)
                invoke(_snap, delay=1.35)
            else:
                invoke(_snap, delay=0.60)
            return

        if SHOT_VIEW == 'pause':
            toggle_pause(True)
        elif SHOT_VIEW == 'settings':
            toggle_pause(True)
            pause_menu.set_page(pause_menu.PAGE_SETTINGS)
        elif SHOT_VIEW == 'quit':
            toggle_pause(True)
            pause_menu.set_page(pause_menu.PAGE_QUIT)
        elif SHOT_VIEW == 'score':
            scoreboard.show()
        invoke(_snap, delay=0.35)

    invoke(_do_shot, delay=1.1)

if SELFTEST:
    def _selftest():
        global fire_latch, recoil_pitch, recoil_yaw
        ok = []
        ok.append(('hud 元素', len(hud.root.children) > 8))
        hp0 = state.health
        state.take_damage(30)
        ok.append(('受伤扣血', state.health == hp0 - 15))
        weapon.update(1.0)                 # 清掉上帧可能的冷却，避免偶发误判
        mag0 = weapon.mag
        try_fire()
        ok.append(('开火扣弹', weapon.mag == mag0 - 1 or weapon.reloading))
        # 半自动连发（原 bug：input 里锁存没加 global，打一发就哑火）
        weapon.update(1.0)
        m1 = weapon.mag
        fire_latch = False
        input('left mouse up')
        try_fire()
        ok.append(('半自动可连续击发', weapon.mag == m1 - 1))
        weapon.update(1.0)
        m2 = weapon.mag
        input('left mouse up')
        try_fire()
        ok.append(('第三次点击仍击发', weapon.mag == m2 - 1))
        res0 = weapon.reserve
        start_reload()
        ok.append(('进入换弹', weapon.reloading))
        weapon.update(3.0)
        ok.append(('换弹完成', weapon.mag == weapon.mag_size))
        ok.append(('备弹无限不消耗', weapon.reserve == res0 and weapon.infinite_reserve))
        ok.append(('备弹显示为∞', weapon.reserve_text == '∞'))
        toggle_pause(True)
        ok.append(('暂停菜单可见', pause_menu.visible))
        toggle_pause(False)
        ok.append(('恢复游戏', not pause_menu.visible))
        scoreboard.show()
        ok.append(('计分板有槽位', len(scoreboard.rows_root.children) > 5))
        scoreboard.hide()

        # 武器系统：模型加载 / 切枪 / 检视 / 近战 / HUD 同步
        ok.append(('五把武器模型就位', set(viewmodel.models) == set(WEAPON_ORDER)))
        for wk in WEAPON_ORDER:
            n = len(viewmodel.models[wk].node.findAllMatches('**/+GeomNode'))
            ok.append((f'模型有网格 {wk}', n > 0))

        # 弹道参数：散布 / 后坐 / 目录顺序
        ok.append(('目录顺序 1-5 正确', by_index(0) == 'usp' and by_index(3) == 'awm'
                    and by_index(4) == 'knife' and by_index(5) is None))
        d = spread_at(WEAPON_CATALOG['usp'], heat=0.0, move_k=0.0)
        ok.append(('基础散布角', 0.4 < d < 0.7))
        d2 = spread_at(WEAPON_CATALOG['usp'], heat=2.0, move_k=0.0)
        ok.append(('连射散布增大', d2 > d))
        d3 = spread_at(WEAPON_CATALOG['usp'], heat=2.0, move_k=1.0)
        ok.append(('移动散布惩罚', d3 > d2))
        awm_zoom = spread_at(WEAPON_CATALOG['awm'], zoomed=True)
        awm_hip = spread_at(WEAPON_CATALOG['awm'])
        ok.append(('开镜散布缩小', awm_zoom < awm_hip * 0.1))
        ok.append(('AWM 有开镜 FOV', WEAPON_CATALOG['awm'].get('zoom_fov', 0) < 30))
        ok.append(('AK 全自动', WEAPON_CATALOG['ak']['ammo']['auto'] is True))

        # 伤害制目标：打 3 发 USP（34×3=102）才击杀一个 100 血目标
        t100 = Entity(model='cube', position=camera.world_position + camera.forward * 6,
                      scale=1.0, collider='box')
        t100.hp = TARGET_HP
        targets.append(t100)
        kills0 = state.kills
        viewmodel.switch_to('usp')
        viewmodel.update_switch(0.20)
        viewmodel.update_switch(0.30)
        fire_latch = False
        for _ in range(3):
            weapon.update(1.0)
            fire_latch = False
            try_fire()
        ok.append(('伤害制目标 3 发击杀', state.kills == kills0 + 1 and t100 not in targets))
        if t100 in targets:
            targets.remove(t100)
        destroy(t100)

        # 后坐力：开火后视角应**向上**抬（rotation_x 减小），手动推进回落逻辑应清零
        recoil_pitch = 0.0                  # 清掉前面测试残留的待回落量
        pitch0 = player.camera_pivot.rotation_x
        fire_latch = False
        weapon.update(1.0)
        try_fire()
        ok.append(('后坐力向上踢起视角', player.camera_pivot.rotation_x < pitch0 - 0.5))
        recover = (viewmodel.spec.get('recoil') or {}).get('recover', 6.0)
        for _ in range(200):                # recover × 20s 一定收完
            step = min(max(recoil_pitch, 0.0), recover * 0.1)
            player.camera_pivot.rotation_x += step
            recoil_pitch -= step
        ok.append(('后坐力回落', abs(player.camera_pivot.rotation_x - pitch0) < 0.2
                    and recoil_pitch <= 0.0))
        hud_hints = len(hud.hints.children)
        ok.append(('按键提示已含检视', hud_hints >= 16))

        switch_weapon('knife')
        ok.append(('切枪开始动画', viewmodel.busy))
        viewmodel.update_switch(0.20)      # 下压结束 → 换模型
        viewmodel.update_switch(0.30)      # 上抬结束
        ok.append(('已装备匕首', viewmodel.active_key == 'knife'))
        ok.append(('HUD 切到近战', hud.melee_label.enabled and not hud.crosshair.root.enabled))
        # 近战持刀状态下主循环 HUD 刷新（曾因 Melee 无 reserve_text 崩溃）
        hud.update(0.0, player, targets)
        ok.append(('持刀 HUD 刷新不崩溃', hud.res_text.text == '/  —'))

        ok.append(('检视动画启动', viewmodel.start_inspect() and viewmodel.inspecting))
        for _ in range(30):               # tick 内部会把 dt 夹到 0.1，这里多推几帧
            viewmodel.tick(0.1)
        ok.append(('检视动画播完', not viewmodel.inspecting))

        mag_knife = ARMS['knife'].mag
        swing_knife()
        ok.append(('近战挥砍进入冷却', ARMS['knife'].cooldown > 0 and ARMS['knife'].mag == mag_knife))

        # 近战命中：镜头前 1.2 米放个目标，挥刀应该砍掉它
        near = Entity(model='cube', position=camera.world_position + camera.forward * 1.2,
                      scale=1.0, collider='box')
        near.hp = TARGET_HP
        targets.append(near)
        ARMS['knife'].cooldown = 0.0
        kills0 = state.kills
        swing_knife()
        ok.append(('近战可命中目标', state.kills == kills0 + 1 and near not in targets))
        if near in targets:
            targets.remove(near)
        destroy(near)

        switch_weapon('usp')
        viewmodel.update_switch(0.20)
        viewmodel.update_switch(0.30)
        ok.append(('切回手枪', viewmodel.active_key == 'usp' and hud.crosshair.root.enabled))

        # AWM：右键开镜 / 松开收镜（usp 没有 zoom_fov，开镜应被拒绝）
        input('right mouse down')
        ok.append(('手枪不可开镜', not scoping))
        # 背包规则 + 商店：AWM 不在默认配装里，直接切应被拒绝；
        # 走商店装备后才能切换
        ok.append(('配装外武器不可直切', not switch_weapon('awm')
                    and viewmodel.active_key == 'usp'))
        equip_from_shop('primary', 'awm')
        ok.append(('商店装备 AWM', LOADOUT['primary'] == 'awm'
                    and 'awm' in viewmodel.available))
        switch_weapon('awm')
        viewmodel.update_switch(0.20)
        viewmodel.update_switch(0.30)
        ok.append(('切到 AWM', viewmodel.active_key == 'awm'))
        input('right mouse down')
        ok.append(('AWM 右键开镜', scoping and hud.scope.root.enabled))
        input('right mouse up')
        ok.append(('松开收镜', not scoping and not hud.scope.root.enabled))
        equip_from_shop('primary', 'ak')
        ok.append(('换回 AK 后原 AWM 移出配装', LOADOUT['primary'] == 'ak'
                    and 'awm' not in viewmodel.available))
        switch_weapon('usp')
        viewmodel.update_switch(0.20)
        viewmodel.update_switch(0.30)

        # 武器商店界面：打开 / 关闭 / 已装备标记
        open_shop()
        ok.append(('商店可打开', shop.visible))
        ok.append(('商店列出全部武器', len(shop.cards) ==
                    len(SLOTS['primary']) + len(SLOTS['side'])))
        close_shop()
        ok.append(('商店可关闭', not shop.visible))

        # 人物模型：动画已加载 + 第三人称切换
        if character is not None:
            ok.append(('人物模型已装配', len(CHAR_ANIMS) > 0))
            ok.append(('人物有待机/跑动动画',
                        any(k.startswith('idle') for k in CHAR_ANIMS)
                        and any(k.startswith('run') for k in CHAR_ANIMS)))
            toggle_third_person()
            ok.append(('第三人称切换', third_person))
            toggle_third_person()
            ok.append(('切回第一人称', not third_person))

        # 音效：每把武器独立枪声 + 切枪/切刀/装弹音
        ok.append(('五把武器独立枪声', set(FIRE_SOUNDS) == set(WEAPON_ORDER)))
        ok.append(('切换音效已加载', switch_gun_sound is not None
                    and switch_knife_sound is not None))
        ok.append(('装弹到位音已加载', reload_done_sound is not None))

        # 分部位伤害（三区简化：头×4 / 身×1.25 / 肢×0.75）
        ok.append(('部位倍率配置', ZONE_MULTIPLIERS['head'] == 4.0
                    and ZONE_MULTIPLIERS['body'] == 1.25
                    and ZONE_MULTIPLIERS['limb'] == 0.75))
        ok.append(('部位伤害换算', zone_damage(34, 'head') == 136.0
                    and zone_damage(34, 'body') == 42.5
                    and zone_damage(34, 'limb') == 25.5))
        ok.append(('按高度划分部位', classify_zone_by_height(1.6) == 'head'
                    and classify_zone_by_height(1.0) == 'body'
                    and classify_zone_by_height(0.4) == 'limb'))
        if not TEAM and not DUEL:
            ok.append(('训练场木偶人已放置', len(dummies) >= 6))
            ok.append(('木偶人分部位标记', any(p.dummy_part == 'head'
                                                for p in dummies[0].parts)))

        # 人机：生成 / 难度参数 / 部位受击 / 击倒重生
        ok.append(('人机难度表完整', set(BOTS_MODULE.DIFFICULTY_ORDER)
                    == {'easy', 'normal', 'hard'}))
        if TEAM or DUEL:
            ok.append(('人机已生成', len(bots) >= 1
                        and all(b.team == ENEMY_TEAM for b in bots)))
            _b = bots[0]
            _hp0 = _b.hp
            _killed, _dmg = _b.take_damage(30, 'head')      # 30×4=120
            ok.append(('人机部位受击', _dmg == 120.0 and (_killed == (_hp0 <= 120))))
            ok.append(('人机击倒后重生计时', not _b.alive and _b.respawn_left > 0))
            _b.update(10.0)                                  # 推进重生
            ok.append(('人机重生满血', _b.alive and _b.hp == _b.max_hp))

        # 团队模式（--map team 运行时才有）
        if TEAM:
            ok.append(('团队出生点在红队半场', player.z < -35))
            ok.append(('蓝队木偶人已放置', len(dummies) >= 5
                        and all(p.dummy_part in ZONE_MULTIPLIERS
                                for d in dummies for p in d.parts)))
            ok.append(('胜利分数已配置', VICTORY > 0))
            # 部位伤害：头部一枪击倒 100 血木偶（USP 34 × 4 = 136）
            _d = dummies[0]
            _head = next(p for p in _d.parts if p.dummy_part == 'head')
            killed, dmg = _d.take_damage(34, 'head')
            ok.append(('头部命中 ×4 击倒', killed and dmg == 136 and not _d.alive))
            _d.respawn()
            _limb = next(p for p in _d.parts if p.dummy_part == 'limb')
            killed, dmg = _d.take_damage(34, 'limb')
            ok.append(('肢体命中 ×0.75 不击倒', not killed and dmg == 25.5 and _d.alive))
            _d.respawn()
            state.score = VICTORY - 5
            team_t = Entity(model='cube', position=camera.world_position + camera.forward * 5,
                            scale=1.0, collider='box')
            team_t.hp = 999
            targets.append(team_t)
            hit_target(team_t, 999)
            ok.append(('达到胜利分判胜', match_won and state.score >= VICTORY))
            if team_t in targets:
                targets.remove(team_t)
            destroy(team_t)

        # 单挑地图（--map duel 运行时才有）
        if DUEL and duel_arena:
            ok.append(('单挑地图有碰撞体', duel_arena.collider_count > 5))
            ok.append(('单挑出生点在墙内', abs(player.z) <= 45 and abs(player.x) <= 25))

        state.take_damage(999)
        ok.append(('死亡状态', not state.alive))
        respawn_player()
        ok.append(('重生满血', state.alive and state.health == 100))
        for name, cond in ok:
            print(f"[selftest] {'PASS' if cond else 'FAIL'} {name}")
        print('[selftest]', 'ALL PASS' if all(c for _, c in ok) else 'HAS FAIL')
        application.quit()

    invoke(_selftest, delay=0.9)

# 开局弹出武器商店（训练 / 单挑 / 团队全模式都支持），局中按 B 随时再开。
# 截图与自检模式下不弹，避免挡住出图和自动化流程。
if not SHOT_PATH and not SELFTEST:
    invoke(open_shop, delay=0.8)

app.run()
