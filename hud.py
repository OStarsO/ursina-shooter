"""CS:GO 风格 HUD：血量护甲、弹药、雷达、比分、击杀提示、准星、命中反馈。

对外接口
--------
    hud = HUD(player, weapon, mode_name='训练场')
    hud.update(dt, targets=targets, elapsed=t)
    hud.on_fire()               # 开火：准星扩散 + 弹药变化
    hud.on_hit(kill=False, ...)  # 命中/击杀：命中标记 + 击杀提示
    hud.on_damage(angle)         # 受伤：方向指示
    hud.set_room_info(text)      # 联机信息（顶部雷达下方）
    hud.relayout()               # 窗口宽高比变化时重排

所有尺寸都写成 "900p 下的像素值"，用 ui_theme.px() 换算，
所以 1600×900 与 2560×1440、21:9 带鱼屏下观感一致。
"""
from __future__ import annotations

import math

from ursina import Entity, Text, camera, color, time, window

import ui_theme as T
from ui_theme import BT, Panel, KeyCap, TEX, label, mix, px, rgba, ui_half_w

# 布局常量（900p 像素）
PAD = 16
LEFT_W, LEFT_H = 336, 106
AMMO_W, AMMO_H = 296, 106
SCORE_W, SCORE_H = 452, 74
RADAR = 202


class Crosshair:
    """四线准星：暗描边 + 亮线，开火时向四周扩散后回收。"""

    def __init__(self, parent, col=(120, 232, 132), length=None, thickness=None,
                 gap=None, dot=True):
        self.root = Entity(parent=parent)
        self.length = length if length is not None else px(10)
        self.thickness = thickness if thickness is not None else px(2.4)
        self.base_gap = gap if gap is not None else px(7)
        self.spread = 0.0
        self.col = col

        self.h = []
        self.v = []
        for sign in (1, -1):
            outline = Entity(parent=self.root, model='quad', color=rgba((0, 0, 0), 165), z=-0.008)
            line = Entity(parent=self.root, model='quad', color=rgba(col, 245), z=-0.01)
            self.h.append((outline, line, sign))
            outline = Entity(parent=self.root, model='quad', color=rgba((0, 0, 0), 165), z=-0.008)
            line = Entity(parent=self.root, model='quad', color=rgba(col, 245), z=-0.01)
            self.v.append((outline, line, sign))

        self.dot = None
        if dot:
            Entity(parent=self.root, model='quad', scale=(self.thickness * 1.6, self.thickness * 1.6),
                   color=rgba((0, 0, 0), 180), z=-0.009)
            self.dot = Entity(parent=self.root, model='quad',
                              scale=(self.thickness, self.thickness),
                              color=rgba(col, 255), z=-0.011)

        # 命中标记
        self.marks = []
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            Entity(parent=self.root, model='quad', scale=(px(11), px(1.8)),
                   position=(sx * px(9), sy * px(9), -0.012), rotation_z=-45 * sx * sy,
                   color=rgba((0, 0, 0), 120))
            e = Entity(parent=self.root, model='quad', scale=(px(10), px(1.4)),
                       position=(sx * px(9), sy * px(9), -0.013), rotation_z=-45 * sx * sy,
                       color=rgba((255, 255, 255), 0))
            self.marks.append(e)
        self.mark_t = 0.0
        self.mark_kill = False

        # 受伤方向
        self.dmg_dir = Entity(parent=self.root, model='quad', texture=TEX['wedge'],
                              scale=(px(210), px(105)), y=px(118), z=-0.006,
                              color=rgba((255, 255, 255), 0))
        self.dmg_t = 0.0

        self._apply()

    def _apply(self):
        gap = self.base_gap + self.spread
        ln, th = self.length, self.thickness
        for tuples, vertical in ((self.h, False), (self.v, True)):
            for outline, line, sign in tuples:
                if vertical:
                    for e, extra in ((outline, px(2)), (line, 0.0)):
                        e.scale = (th + extra, ln + extra)
                        e.x = 0
                        e.y = sign * (gap + ln / 2)
                else:
                    for e, extra in ((outline, px(2)), (line, 0.0)):
                        e.scale = (ln + extra, th + extra)
                        e.y = 0
                        e.x = sign * (gap + ln / 2)

    def fire(self):
        self.spread = min(px(16), self.spread + px(5.5))

    def hit(self, kill=False):
        self.mark_t = 0.32 if kill else 0.16
        self.mark_kill = kill
        for m in self.marks:
            m.scale = (px(15) if kill else px(10), px(2.0) if kill else px(1.4))
            m.color = rgba((255, 92, 72) if kill else (255, 255, 255), 255)

    def damage(self, angle_deg):
        self.dmg_t = 1.1
        self.dmg_dir.rotation_z = angle_deg

    def update(self, dt):
        self.spread = max(0.0, self.spread - dt * px(26))
        self._apply()

        if self.mark_t > 0:
            self.mark_t = max(0.0, self.mark_t - dt)
            k = min(1.0, self.mark_t / (0.16 if not self.mark_kill else 0.32))
            for m in self.marks:
                m.color = rgba((255, 92, 72) if self.mark_kill else (255, 255, 255), 255 * k)
        else:
            for m in self.marks:
                m.color = rgba((255, 255, 255), 0)

        if self.dmg_t > 0:
            self.dmg_t = max(0.0, self.dmg_t - dt)
            self.dmg_dir.color = rgba((255, 255, 255), 210 * min(1.0, self.dmg_t / 0.55))
        else:
            self.dmg_dir.color = rgba((255, 255, 255), 0)


class KillFeed:
    """右上角击杀提示，逐条淡出。"""

    def __init__(self, parent, width=None, rows=5, life=5.0):
        self.root = Entity(parent=parent)
        self.rows = []
        self.life = life
        self.w = width or px(250)

    def push(self, text, tag='', accent=None):
        row = Entity(parent=self.root)
        bg = Entity(parent=row, model='quad', scale=(self.w, px(26)),
                    color=rgba((8, 12, 16), 238))
        Entity(parent=row, model='quad', scale=(px(2.5), px(26)),
               x=-self.w / 2 + px(1.2), color=rgba(accent or T.C_ACCENT, 235))
        Text(text=text, parent=row, position=(-self.w / 2 + px(12), 0, -0.01),
             origin=(-0.5, 0), scale=T.fs(15, T.has_cjk(text)),
             color=rgba(T.C_TEXT, 240), font=T.font_for(text))
        if tag:
            Text(text=tag, parent=row, position=(self.w / 2 - px(12), 0, -0.01),
                 origin=(0.5, 0), scale=T.fs(14), color=rgba(accent or T.C_ACCENT, 240),
                 font=T.FONT_NUM)
        self.rows.append({'e': row, 'bg': bg, 't': self.life})
        while len(self.rows) > 5:
            old = self.rows.pop(0)
            old['e'].enabled = False
        self._layout()

    def _layout(self):
        for i, r in enumerate(reversed(self.rows)):
            r['e'].x = 0
            r['e'].y = -i * px(30)

    def update(self, dt):
        alive = []
        for r in self.rows:
            r['t'] -= dt
            if r['t'] <= 0:
                r['e'].enabled = False
                continue
            k = min(1.0, r['t'] / 0.8)
            r['bg'].color = rgba((8, 12, 16), 238 * k)
            alive.append(r)
        self.rows = alive
        self._layout()


class Radar:
    """左上角雷达：圆形刻度 + 扫描线 + 目标点。"""

    def __init__(self, parent, size=None, unit_px=0.0, world_range=42.0):
        self.size = size or px(RADAR)
        self.root = Panel(parent, self.size, self.size, brackets=False, shadow=False,
                          fill=(8, 12, 17), alpha=246)
        self.root.name = 'radar'
        inner = self.size * 0.94
        self.ring = Entity(parent=self.root, model='quad', texture=TEX['ring'],
                           scale=(inner, inner), color=rgba((96, 122, 146), 190), z=-0.004)
        self.sweep = Entity(parent=self.root, model='quad', texture=TEX['sweep'],
                            scale=(inner, inner), color=rgba((120, 200, 255), 46), z=-0.005)
        self.dots = Entity(parent=self.root)
        self.dot_pool = []
        Entity(parent=self.root, model='quad', scale=(px(9), px(9)),
               position=(0, 0, -0.012), color=rgba(T.C_TEXT, 240), texture=TEX['ic_arrow'])
        # 视野方向提示（雷达旋转时箭头恒朝上，这里加一条细线表示正前）
        Entity(parent=self.root, model='quad', scale=(BT, inner * 0.42),
               position=(0, inner * 0.21, -0.006), color=rgba(T.C_TEXT, 40))
        self.world_range = world_range

    def update(self, dt, player, targets):
        self.sweep.rotation_z = (self.sweep.rotation_z + dt * 42) % 360
        limit = self.size * 0.44
        scale = limit / max(1.0, self.world_range)

        pts = []
        base = getattr(player, 'world_position', None)
        if base is not None:
            ry = math.radians(getattr(player, 'rotation_y', 0.0))
            fx, fz = math.sin(ry), math.cos(ry)
            rx, rz = math.cos(ry), -math.sin(ry)
            for t in targets:
                if not getattr(t, 'enabled', True):
                    continue
                dx = t.world_position.x - base.x
                dz = t.world_position.z - base.z
                u = dx * rx + dz * rz
                v = dx * fx + dz * fz
                d = math.hypot(u, v)
                if d > self.world_range:
                    continue
                pts.append((u * scale, v * scale))

        while len(self.dot_pool) < len(pts):
            glow = Entity(parent=self.dots, model='quad', texture=TEX['glow'],
                          scale=(px(16), px(16)), color=rgba(T.C_DANGER, 70), z=-0.006)
            dot = Entity(parent=self.dots, model='quad', scale=(px(5), px(5)),
                         color=rgba(T.C_DANGER, 245), z=-0.008)
            self.dot_pool.append({'glow': glow, 'dot': dot})

        for i, item in enumerate(self.dot_pool):
            if i < len(pts):
                u, v = pts[i]
                item['glow'].position = (u, v, -0.006)
                item['dot'].position = (u, v, -0.008)
                item['glow'].enabled = item['dot'].enabled = True
            else:
                item['glow'].enabled = item['dot'].enabled = False


class HUD:
    """整套 HUD 的装配与刷新。"""

    def __init__(self, player, weapon, mode_name='训练场', room_info=''):
        self.player = player
        self.weapon = weapon
        self.mode_name = mode_name
        self.elapsed = 0.0
        self._aspect = window.aspect_ratio

        self.root = Entity(parent=camera.ui, name='hud')

        self._build_vignette()
        self._build_left()
        self._build_ammo()
        self._build_score()
        self.radar = Radar(self.root)
        self._build_killfeed()
        self._build_hints()
        self._build_death()
        self._build_room()
        self.crosshair = Crosshair(self.root)
        self._build_banner()

        self._cache = {}
        self.relayout()

    # ------------------------------------------------------------ 构建
    def _build_vignette(self):
        self.vignette = Entity(parent=self.root, model='quad', texture=TEX['vignette'],
                               scale=(1.06, 1.06), z=0.02, color=rgba((255, 255, 255), 0))

    def _build_left(self):
        p = Panel(self.root, px(LEFT_W), px(LEFT_H), brackets=False, alpha=242)
        self.left = p
        # 生命色条：随血量变色
        self.hp_bar = Entity(parent=p, model='quad', scale=(px(3), px(LEFT_H) - px(2)),
                             position=(-px(LEFT_W) / 2 + px(1.5), 0, -0.004),
                             color=rgba(T.C_HP, 235))
        p.image(TEX['ic_health'], px(22), px(22), x=-px(LEFT_W) / 2 + px(24), y=px(22),
                col=T.C_HP, alpha=225)
        self.hp_text = p.text(self.player.health_text, 46, x=-px(LEFT_W) / 2 + px(50),
                              y=px(20), style='num', col=T.C_HP)
        label(p, '生命', 12, x=px(LEFT_W) / 2 - px(14), y=px(30), origin=(0.5, 0),
              col=T.C_TEXT_MUTE)

        p.image(TEX['ic_armor'], px(19), px(19), x=-px(LEFT_W) / 2 + px(24), y=-px(24),
                col=T.C_TEXT_DIM, alpha=210)
        self.ap_text = p.text(self.player.armor_text, 27, x=-px(LEFT_W) / 2 + px(50),
                              y=-px(26), style='num', col=T.C_TEXT_DIM)
        label(p, '护甲', 12, x=px(LEFT_W) / 2 - px(14), y=-px(16), origin=(0.5, 0),
              col=T.C_TEXT_MUTE)

        # 回血提示（训练场专用）
        self.regen = label(p, '恢复中', 11, x=px(LEFT_W) / 2 - px(14), y=-px(32),
                           origin=(0.5, 0), col=T.C_OK, alpha=0)

    def _build_ammo(self):
        p = Panel(self.root, px(AMMO_W), px(AMMO_H), brackets=False, alpha=242)
        self.ammo = p
        self.weapon_name = p.text(T.spaced(self.weapon.name), 13,
                                  x=px(AMMO_W) / 2 - px(16), y=px(33), origin=(0.5, 0),
                                  col=T.C_TEXT_DIM, alpha=225)
        p.image(TEX['ic_bullet'], px(24), px(24), x=-px(AMMO_W) / 2 + px(26), y=-px(6),
                col=T.C_TEXT_DIM, alpha=215)
        self.mag_text = p.text(str(self.weapon.mag_size), 42,
                               x=px(AMMO_W) / 2 - px(108), y=-px(7), origin=(0.5, 0),
                               style='num', col=T.C_TEXT)
        self.res_text = p.text(f'/  {self.weapon.reserve}', 18,
                               x=px(AMMO_W) / 2 - px(20), y=-px(4), origin=(0.5, 0),
                               col=T.C_TEXT_MUTE, style='num')
        # 换弹进度条
        self.reload_bg = Entity(parent=p, model='quad', scale=(px(AMMO_W) - px(32), px(3)),
                                position=(0, -px(AMMO_H) / 2 + px(9), -0.004),
                                color=rgba(T.C_LINE_SOFT, 200))
        self.reload_fill = Entity(parent=p, model='quad', scale=(0.0, px(3)),
                                  position=(-px(AMMO_W) / 2 + px(16), -px(AMMO_H) / 2 + px(9), -0.005),
                                  color=rgba(T.C_ACCENT, 245))
        self.reload_bg.enabled = self.reload_fill.enabled = False

    def _build_score(self):
        p = Panel(self.root, px(SCORE_W), px(SCORE_H), accent_top=True, alpha=248)
        self.score_panel = p
        w = px(SCORE_W)
        label(p, '得分', 12, x=-w / 2 + px(18), y=px(26), col=T.C_TEXT_MUTE)
        self.score_text = p.text('0', 31, x=-w / 2 + px(18), y=-px(9), style='num',
                                 col=T.C_ACCENT)
        label(p, '击杀', 12, x=w / 2 - px(18), y=px(26), origin=(0.5, 0), col=T.C_TEXT_MUTE)
        self.kill_text = p.text('0', 31, x=w / 2 - px(18), y=-px(9), origin=(0.5, 0),
                                style='num', col=T.C_TEAM_CT)
        self.timer_text = p.text('0:00', 31, x=0, y=-px(9), origin=(0, 0), style='num',
                                 col=T.C_TEXT)
        # 中央分隔线
        for sx in (-1, 1):
            Entity(parent=p, model='quad', scale=(BT, px(34)), position=(sx * px(96), -px(2), -0.004),
                   color=rgba(T.C_LINE_SOFT, 220))
        Entity(parent=p, model='quad', scale=(px(96), px(20)),
               position=(0, -px(SCORE_H) / 2 - px(13), -0.005), color=rgba((8, 12, 16), 205))
        self.mode_label = label(p, self.mode_name, 12, x=0, y=-px(SCORE_H) / 2 - px(13),
                                origin=(0, 0), col=T.C_TEXT_DIM)

    def _build_killfeed(self):
        self.killfeed = KillFeed(self.root)

    def _build_hints(self):
        self.hints = Entity(parent=self.root)
        pairs = [('WASD', '移动'), ('SPACE', '跳跃'), ('R', '换弹'), ('TAB', '计分板'),
                 ('ESC', '菜单')]
        x = 0.0
        gap_key = px(9)
        gap_item = px(30)
        # 先测量每项宽度，再整体居中
        widths = []
        for key, txt in pairs:
            kw = max(px(20) * 1.02, px(20) * (0.60 * len(key) + 0.46))
            widths.append(kw + gap_key + px(TEXT_W(txt)) + gap_item)
        total = sum(widths) - gap_item
        x = -total / 2
        for (key, txt), wdt in zip(pairs, widths):
            kw = max(px(20) * 1.02, px(20) * (0.60 * len(key) + 0.46))
            KeyCap(self.hints, key, x=x + kw / 2, y=0, h_px=20, size_px=12)
            label(self.hints, txt, 13, x=x + kw + gap_key, y=0, col=T.C_TEXT_DIM)
            x += wdt
        self._hints_y = -0.5 + px(26)

    def _build_death(self):
        self.death_root = Entity(parent=self.root, enabled=False)
        self.death_dark = Entity(parent=self.death_root, model='quad', scale=(2.4, 1.4), z=0.01,
                                 color=rgba((6, 2, 2), 130))
        panel = Panel(self.death_root, px(360), px(132), alpha=232, accent_top=True,
                      brackets=True, border_col=T.C_DANGER[:3])
        label(panel, '阵亡', 42, x=0, y=px(26), origin=(0, 0), col=T.C_DANGER)
        self.death_tip = label(panel, '3.0 秒后重生', 15, x=0, y=-px(22), origin=(0, 0),
                               col=T.C_TEXT_DIM)

    def _build_room(self):
        self.room_label = label(self.root, '', 12, x=0, y=0, col=T.C_TEXT_MUTE, alpha=210,
                                font=T.FONT_CJK)
        self.room_label.enabled = False

    def _build_banner(self):
        self.banner_root = Entity(parent=self.root)
        self.banner_text = label(self.banner_root, '', 26, x=0, y=0, origin=(0, 0),
                                 col=T.C_ACCENT, alpha=0, font=T.FONT_CJK)
        self.banner_t = 0.0
        self._banner_col = T.C_ACCENT

    # ------------------------------------------------------------ 布局
    def relayout(self):
        half = ui_half_w()
        self._aspect = window.aspect_ratio

        self.left.x = -half + px(PAD) + px(LEFT_W) / 2
        self.left.y = -0.5 + px(PAD) + px(LEFT_H) / 2

        self.ammo.x = half - px(PAD) - px(AMMO_W) / 2
        self.ammo.y = -0.5 + px(PAD) + px(AMMO_H) / 2

        self.score_panel.x = 0
        self.score_panel.y = 0.5 - px(PAD) - px(SCORE_H) / 2

        self.radar.root.x = -half + px(PAD) + self.radar.size / 2
        self.radar.root.y = 0.5 - px(PAD) - self.radar.size / 2

        self.killfeed.root.x = half - px(PAD) - px(250) / 2 - px(4)
        self.killfeed.root.y = 0.5 - px(PAD) - px(13)

        self.hints.y = self._hints_y

        if self.room_label.enabled:
            self.room_label.x = -half + px(PAD) + px(4)
            self.room_label.y = self.radar.root.y - self.radar.size / 2 - px(12)
            self.room_label.origin = (-0.5, 0)

        self.banner_root.y = 0.5 - px(PAD) - px(SCORE_H) - px(70)
        self.death_dark.scale = (window.aspect_ratio + 0.4, 1.4)
        self.vignette.scale = (window.aspect_ratio * 1.04, 1.06)

    def set_room_info(self, text):
        self.room_label.text = text
        self.room_label.enabled = bool(text)
        self.room_label.x = -ui_half_w() + px(PAD) + px(4)
        self.room_label.y = self.radar.root.y - self.radar.size / 2 - px(12)
        self.room_label.origin = (-0.5, 0)

    def banner(self, text, seconds=1.4, col=None):
        self.banner_text.text = text
        self._banner_col = col or T.C_ACCENT
        self.banner_text.color = rgba(self._banner_col, 255)
        self.banner_t = seconds

    # ------------------------------------------------------------ 事件
    def on_fire(self, hit=False, kill=False):
        self.crosshair.fire()
        if hit:
            self.crosshair.hit(kill)

    def on_damage(self, angle_deg=0.0):
        self.crosshair.damage(angle_deg)

    def push_kill(self, victim, gain=10, weapon=''):
        txt = f'你  »  {victim}'
        self.killfeed.push(txt, tag=f'+{gain}' if gain else '', accent=T.C_ACCENT)
        self.banner(f'击杀 {victim}', seconds=0.9, col=T.C_TEXT)

    # ------------------------------------------------------------ 每帧
    def update(self, dt, body, targets=()):
        if window.aspect_ratio != self._aspect:
            self.relayout()

        self.elapsed += dt
        p, w = self.player, self.weapon
        p.update(dt)
        w.update(dt)

        # 血 / 甲
        self._set(self.hp_text, p.health_text)
        self._set(self.ap_text, p.armor_text)
        hp_col = T.C_DANGER if p.low_health else T.C_HP
        if p.low_health:
            pulse = 0.55 + 0.45 * math.sin(time.time() * 7.5)
            hp_col = mix(T.C_HP, T.C_DANGER, pulse)
        self.hp_text.color = rgba(hp_col, 250)
        self.hp_bar.color = rgba(hp_col, 235)

        # 弹药
        self._set(self.mag_text, str(w.mag))
        self._set(self.res_text, f'/  {w.reserve}')
        self.mag_text.color = rgba(T.C_DANGER if w.mag == 0 else T.C_TEXT, 250)

        if w.reloading:
            self.reload_bg.enabled = self.reload_fill.enabled = True
            k = max(0.02, w.reload_progress)
            self.reload_fill.scale_x = (px(AMMO_W) - px(32)) * k
            self.reload_fill.x = -px(AMMO_W) / 2 + px(16) + self.reload_fill.scale_x / 2
        else:
            self.reload_bg.enabled = self.reload_fill.enabled = False

        self.regen.color = rgba(T.C_OK, 210) if (
            p.alive and p.health < p.max_health and p.since_damage >= p.regen_delay) \
            else rgba(T.C_OK, 0)

        # 比分 / 时间
        self._set(self.score_text, str(p.score))
        self._set(self.kill_text, str(p.kills))
        total = int(self.elapsed)
        self._set(self.timer_text, f'{total // 60}:{total % 60:02d}')

        # 低血量暗角
        if p.alive and p.health < 45:
            k = (45 - p.health) / 45
            pulse = 0.75 + 0.25 * math.sin(time.time() * 6.0)
            self.vignette.color = rgba((255, 255, 255), 150 * k * pulse)
        else:
            self.vignette.color = rgba((255, 255, 255), 0)

        self.crosshair.update(dt)
        self.radar.update(dt, body, targets)
        self.killfeed.update(dt)

        # banner 淡出
        if self.banner_t > 0:
            self.banner_t = max(0.0, self.banner_t - dt)
            k = min(1.0, self.banner_t / 0.45)
            self.banner_text.color = rgba(self._banner_col, 255 * k)
        else:
            self.banner_text.color = rgba(self._banner_col, 0)

        # 死亡
        if not p.alive:
            self.death_root.enabled = True
            self.death_tip.text = f'{p.death_time:.1f} 秒后重生'
        else:
            self.death_root.enabled = False

    def _set(self, text_entity, value):
        if text_entity.text != value:
            text_entity.text = value


def TEXT_W(txt):
    """粗略估算一段中文标签的宽度（900p 像素）。"""
    return 13 * len(txt) + 4
