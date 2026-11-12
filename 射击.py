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

from panda3d.core import Filename
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
import hud as HUD_MODULE
import menu as MENU
from combat import Player, Weapon

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

app = Ursina(title='射击 · 靶场', borderless=False, development_mode=False)
window.title = '射击 · 靶场'
window.borderless = False
window.exit_button.visible = False

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
window.fullscreen = bool(SETTINGS['fullscreen'])
if not SETTINGS['fullscreen']:
    window.size = (SETTINGS['window_width'], SETTINGS['window_height'])
if SHOT_PATH and SHOT_SIZE:
    window.size = SHOT_SIZE

# ===================== 主题 / 字体 =====================
CJK_FONT = T.init_theme()
print('中文字体:', CJK_FONT, '| 英文字体:', T.FONT_NUM)

# ===================== 音效 =====================
SOUND_AVAILABLE = False
shoot_sound = None
if os.path.exists('hit.ogg') or os.path.exists('hit.wav'):
    try:
        shoot_sound = Audio('hit', autoplay=False)
        if getattr(shoot_sound, 'clip', None) is not None:
            SOUND_AVAILABLE = True
            print('音效已加载: hit')
    except Exception as e:
        print('音效加载失败:', e)
else:
    print('未找到 hit.ogg / hit.wav，射击将无声')

if SOUND_AVAILABLE and shoot_sound:
    try:
        shoot_sound.volume = SETTINGS['volume']
    except Exception:
        pass

# ===================== 场景 =====================
Sky()
ground = Entity(model='plane', scale=100, color=color.rgb32(52, 58, 64),
                texture='white_cube', texture_scale=(100, 100), collider='box')

MODE_CN = {'training': '训练场', 'duel': '单挑', 'team5': '团队竞技 5v5',
           'team10': '团队竞技 10v10'}
MODE_NAME = MODE_CN.get(NET_INFO.get('mode') or NET_INFO.get('net-mode') or '', '训练场')
NICKNAME = NET_INFO.get('nickname') or '玩家'

# ===================== 玩家 / 数值 =====================
player = FirstPersonController()
player.speed = 8
player.gravity = 0.5
player.jump_height = 2
player.mouse_sensitivity = Vec2(SETTINGS['sensitivity'], SETTINGS['sensitivity'])
player.cursor.visible = False

state = Player(max_health=100, max_armor=100, start_armor=100)
weapon = Weapon('GLOCK-18', mag_size=20, reserve=120, rpm=430, reload_time=2.1)

# ===================== 目标方块 =====================
targets = []


def spawn_target():
    """在 8~24 米外随机刷新目标，避免怼在镜头前糊住视野。"""
    x = z = 0
    for _ in range(24):
        x = random.randint(-22, 22)
        z = random.randint(-22, 22)
        d2 = (x - player.x) ** 2 + (z - player.z) ** 2
        if 64 < d2 <= 576:
            break
    y = random.randint(1, 7)
    target = Entity(model='cube', color=color.rgb32(196, 74, 58),
                    position=(x, y, z), scale=1.4, collider='box')
    targets.append(target)


for _ in range(10):
    spawn_target()

# ===================== 枪模 =====================
gun = Entity(parent=camera, position=(0.33, -0.37, 0.72), scale=0.055)
Entity(parent=gun, model='cube', color=color.rgb32(40, 40, 45), scale=(1.5, 1.2, 4.0))
Entity(parent=gun, model='cube', color=color.rgb32(25, 25, 30),
       scale=(0.7, 0.7, 2.0), position=(0, 0.2, -3.0))
Entity(parent=gun, model='cube', color=color.rgb32(60, 40, 30),
       scale=(1.3, 3.0, 1.5), position=(0, -1.8, 1.5), rotation_x=-15)
Entity(parent=gun, model='cube', color=color.black,
       scale=(0.2, 0.4, 0.2), position=(0, 1.0, -1.5))

muzzle_flash = Entity(parent=gun, model='sphere', color=color.rgb32(255, 214, 140),
                      scale=1.5, position=(0, 0.2, -4.2), enabled=False)
muzzle_flash_timer = 0.0
GUN_BASE_POS = Vec3(0.33, -0.37, 0.72)
gun_recoil = 0.0

# ===================== 界面 =====================
hud = HUD_MODULE.HUD(state, weapon, mode_name=MODE_NAME)
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
        if shoot_sound:
            try:
                shoot_sound.volume = float(value)
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


# ===================== 射击 =====================
def try_fire():
    if paused or not state.alive:
        return
    if weapon.empty:
        weapon.start_reload()
        return
    if not weapon.fire():
        return

    global gun_recoil, muzzle_flash_timer
    gun_recoil = 1.0
    muzzle_flash.enabled = True
    muzzle_flash_timer = 0.05
    hud.crosshair.fire()

    if SOUND_AVAILABLE and shoot_sound:
        shoot_sound.play()

    # 准星扩散越大，弹道越散（连射惩罚）
    s = min(1.0, hud.crosshair.spread / T.px(16))
    jitter = 0.010 * s
    direction = (camera.forward
                 + camera.right * random.uniform(-jitter, jitter)
                 + camera.up * random.uniform(-jitter, jitter)).normalized()

    hit_info = raycast(camera.world_position, direction, distance=100)
    if hit_info.hit and hit_info.entity in targets:
        targets.remove(hit_info.entity)
        destroy(hit_info.entity)
        state.score += 10
        state.kills += 1
        hud.on_fire(hit=True, kill=True)
        hud.push_kill('目标', 10)
        save_score(state.score)
        invoke(spawn_target, delay=0.5)


def start_reload():
    if paused or not state.alive:
        return
    if weapon.start_reload():
        hud.banner('换弹中', 0.8, T.C_TEXT_DIM)


def respawn_player():
    player.position = (0, 2, 0)
    player.enabled = True
    player.cursor.enabled = False
    state.respawn(full_armor=True)
    weapon.refill()
    hud.banner('重生', 1.1, T.C_OK)
    mouse.locked = True
    mouse.visible = False


peak_y = 0.0


def input(key):
    if key == 'escape':
        if scoreboard.visible:
            scoreboard.hide()
            mouse.locked = state.alive
            mouse.visible = not state.alive
            return
        toggle_pause()
        return

    if paused:
        return

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
    if key == 'f1':
        state.take_damage(22)
        hud.on_damage(random.uniform(-180, 180))
    if key == 'f2':
        state.heal(100)
        state.add_armor(100)


# ===================== 主循环 =====================
def update():
    global gun_recoil, muzzle_flash_timer, peak_y

    dt = time.dt
    if paused:
        return

    # 目标旋转
    for target in targets:
        target.rotation_y += 0.5 * dt * 60

    # 持续射击
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

    # 枪口闪光 / 后坐力
    if muzzle_flash_timer > 0:
        muzzle_flash_timer -= dt
        if muzzle_flash_timer <= 0:
            muzzle_flash.enabled = False

    if gun_recoil > 0:
        gun_recoil = max(0, gun_recoil - dt * 8)
        gun.position = GUN_BASE_POS + Vec3(0.01 * gun_recoil, 0.05 * gun_recoil,
                                           0.08 * gun_recoil)
        gun.rotation_x = -10 * gun_recoil

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
        base.graphicsEngine.renderFrame()
        ok = base.win.getScreenshot().write(Filename(SHOT_PATH))
        print('[shot]', SHOT_PATH, ok)
        application.quit()

    def _do_shot():
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
        ok = []
        ok.append(('hud 元素', len(hud.root.children) > 8))
        hp0 = state.health
        state.take_damage(30)
        ok.append(('受伤扣血', state.health == hp0 - 15))
        mag0 = weapon.mag
        try_fire()
        ok.append(('开火扣弹', weapon.mag == mag0 - 1 or weapon.reloading))
        start_reload()
        ok.append(('进入换弹', weapon.reloading))
        weapon.update(3.0)
        ok.append(('换弹完成', weapon.mag == weapon.mag_size))
        toggle_pause(True)
        ok.append(('暂停菜单可见', pause_menu.visible))
        toggle_pause(False)
        ok.append(('恢复游戏', not pause_menu.visible))
        scoreboard.show()
        ok.append(('计分板有槽位', len(scoreboard.rows_root.children) > 5))
        scoreboard.hide()
        state.take_damage(999)
        ok.append(('死亡状态', not state.alive))
        respawn_player()
        ok.append(('重生满血', state.alive and state.health == 100))
        for name, cond in ok:
            print(f"[selftest] {'PASS' if cond else 'FAIL'} {name}")
        print('[selftest]', 'ALL PASS' if all(c for _, c in ok) else 'HAS FAIL')
        application.quit()

    invoke(_selftest, delay=0.9)

app.run()
