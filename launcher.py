# -*- coding: utf-8 -*-
"""射击 · 客户端启动器

功能：
  P0  一键启动 / 运行环境自检 / 启动日志与崩溃提示 / 单实例与进程托管
  P1  游戏设置（窗口、全屏、灵敏度、音量）/ 资源状态与补齐 / 最高分 / 版本检查 / 快捷操作

依赖：PySide6
"""

import sys
import os
import json
import math
import random
import struct
import wave
import shutil
import subprocess
import urllib.request
import platform
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QProcess, QPropertyAnimation, QEasingCurve,
    QPoint, QRectF, Property, QLockFile,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QLinearGradient, QRadialGradient,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QMessageBox, QComboBox, QSlider,
    QGridLayout, QTextEdit, QSizePolicy, QDialog,
)

from app_style import (
    C_BG, C_PANEL, C_PANEL_2, C_BORDER, C_TEXT, C_MUTED, C_ACCENT, C_ACCENT_DIM,
    C_OK, C_WARN, C_BAD, C_INFO, FONT_FAMILY, FONT_FAMILY_MONO,
)
import room_net as rn
import net_ui

# ============================ 基础常量 ============================

APP_NAME = "射击启动器"
APP_VERSION = "1.1.0"

FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ShootingLauncher"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "game_path": "",
    "python_path": "",
    "last_good_python": "",
    "update_url": "",
    "window_x": None,
    "window_y": None,
    "nickname": "",
    "last_mode": "training",
}

DEFAULT_GAME_SETTINGS = {
    "window_width": 1600,
    "window_height": 900,
    "fullscreen": False,
    "sensitivity": 40.0,
    "volume": 1.0,
}


# ============================ 配置读写 ============================

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_FILE.is_file():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in cfg:
                    if key in data:
                        cfg[key] = data[key]
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ============================ 路径发现 ============================

def locate_game(cfg: dict) -> Path:
    """按优先级查找 射击.py"""
    candidates = []
    if cfg.get("game_path"):
        candidates.append(Path(cfg["game_path"]))
    candidates += [
        BASE_DIR / "射击.py",
        BASE_DIR.parent / "射击.py",
        Path(r"D:/PyCharmMiscProject/射击/射击.py"),
    ]
    for path in candidates:
        try:
            if path and path.is_file():
                return path.resolve()
        except OSError:
            continue
    return BASE_DIR / "射击.py"


def game_dir_of(game_path: Path) -> Path:
    return game_path.parent


def candidate_pythons(game_dir: Path, cfg: dict):
    """返回可能能运行游戏的解释器（先验顺序）"""
    found, seen = [], set()

    def add(path):
        try:
            p = Path(path)
        except (TypeError, ValueError):
            return
        key = str(p).lower()
        if key in seen or not p.is_file():
            return
        seen.add(key)
        found.append(p)

    if cfg.get("last_good_python"):
        add(cfg["last_good_python"])
    if cfg.get("python_path"):
        add(cfg["python_path"])
    add(game_dir / ".venv" / "Scripts" / "python.exe")
    add(game_dir.parent / ".venv" / "Scripts" / "python.exe")

    local_programs = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
    if local_programs.is_dir():
        for sub in sorted(local_programs.glob("Python3*"), reverse=True):
            add(sub / "python.exe")
    for name in ("python.exe", "python3.exe"):
        which = shutil.which(name)
        if which:
            add(which)
    return found


PROBE_CODE = r'''
import json, sys
info = {"ok": False, "python": sys.version.split()[0],
        "bits": 64 if sys.maxsize > 2 ** 32 else 32}
try:
    import importlib.metadata as md
    import ursina
    import panda3d
    try:
        info["ursina"] = md.version("ursina")
    except Exception:
        info["ursina"] = "?"
    try:
        info["panda3d"] = md.version("panda3d")
    except Exception:
        info["panda3d"] = "?"
    info["ok"] = True
except Exception as exc:
    info["error"] = type(exc).__name__ + ": " + str(exc)[:200]
print("@@PROBE@@" + json.dumps(info))
'''


def probe_python(python: Path, timeout=30) -> dict:
    """用子进程探测某个解释器能否 import ursina"""
    result = {"ok": False, "python_path": str(python), "error": "未响应"}
    try:
        proc = subprocess.run(
            [str(python), "-c", PROBE_CODE],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in (proc.stdout or "").splitlines():
            if line.startswith("@@PROBE@@"):
                data = json.loads(line[len("@@PROBE@@"):])
                data["python_path"] = str(python)
                data.setdefault("ok", False)
                return data
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        result["error"] = tail[-1][:200] if tail else "无输出"
    except subprocess.TimeoutExpired:
        result["error"] = "启动超时"
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def check_font(game_dir: Path):
    """与游戏内的字体查找逻辑保持一致"""
    names = ["SimHei.ttf", "simhei.ttf", "msyh.ttc", "MicrosoftYaHei.ttf", "simsun.ttc"]
    for name in names:
        if (game_dir / name).is_file() or list(game_dir.glob("fonts/" + name)):
            return True, f"项目字体 {name}"
    win_fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
    if win_fonts.is_dir():
        for name in names:
            if (win_fonts / name).is_file():
                return True, f"系统字体 {name}"
    return False, "未找到中文字体"


def check_audio(game_dir: Path):
    for name in ("hit.ogg", "hit.wav", "hit.mp3"):
        if (game_dir / name).is_file():
            return True, name
    return False, "缺少音效文件"


def read_scores(game_dir: Path) -> dict:
    data = {"best": 0, "last": 0, "updated": ""}
    try:
        path = game_dir / "scores.json"
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data.update({k: raw.get(k, data[k]) for k in data})
    except (OSError, ValueError):
        pass
    return data


def read_game_settings(game_dir: Path) -> dict:
    settings = dict(DEFAULT_GAME_SETTINGS)
    try:
        path = game_dir / "settings.json"
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for key in settings:
                    if key in raw and isinstance(raw[key], (int, float, bool)):
                        settings[key] = raw[key]
    except (OSError, ValueError):
        pass
    return settings


def write_game_settings(game_dir: Path, settings: dict) -> bool:
    try:
        with open(game_dir / "settings.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def make_placeholder_sound(game_dir: Path) -> bool:
    """合成一个占位射击音效（噪声爆发 + 低频冲击），写入 hit.wav"""
    try:
        rate = 44100
        duration = 0.22
        total = int(rate * duration)
        rng = random.Random(7)
        frames = bytearray()
        for i in range(total):
            t = i / rate
            env = math.exp(-t * 26)
            noise = rng.uniform(-1, 1) * env * 0.55
            thump = math.sin(2 * math.pi * 90 * t) * math.exp(-t * 18) * 0.5
            sample = max(-1.0, min(1.0, noise + thump))
            frames += struct.pack("<h", int(sample * 32767))
        with wave.open(str(game_dir / "hit.wav"), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(rate)
            f.writeframes(bytes(frames))
        return True
    except (OSError, ValueError):
        return False


# ============================ 后台线程 ============================

class EnvProbeThread(QThread):
    """依次探测解释器，找到第一个能 import ursina 的"""
    progress = Signal(str)
    done = Signal(dict)

    def __init__(self, game_dir: Path, cfg: dict, parent=None):
        super().__init__(parent)
        self.game_dir = game_dir
        self.cfg = cfg

    def run(self):
        pythons = candidate_pythons(self.game_dir, self.cfg)
        if not pythons:
            self.done.emit({"ok": False, "error": "未找到任何 Python 解释器"})
            return
        failed = []
        for py in pythons:
            self.progress.emit(f"正在探测 {py.parent.parent.name} …")
            info = probe_python(py)
            info["python_file"] = str(py)
            if info.get("ok"):
                self.done.emit(info)
                return
            failed.append(f"{py}: {info.get('error', '?')}")
            self.progress.emit(f"跳过 {py.name}（{info.get('error', '不可用')[:40]}）")
        self.done.emit({"ok": False, "error": "所有解释器都无法导入 ursina", "detail": failed})


class RepairThread(QThread):
    """创建 .venv 并安装 ursina"""
    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, base_python: Path, game_dir: Path, parent=None):
        super().__init__(parent)
        self.base_python = Path(base_python)
        self.game_dir = Path(game_dir)

    def _run(self, args):
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.line.emit(line)
        return proc.wait()

    def run(self):
        venv_dir = self.game_dir / ".venv"
        python = venv_dir / "Scripts" / "python.exe"
        try:
            if not python.is_file():
                self.line.emit(f"创建虚拟环境：{venv_dir}")
                code = self._run([str(self.base_python), "-m", "venv", str(venv_dir)])
                if code != 0:
                    self.done.emit(False, "创建虚拟环境失败")
                    return
            self.line.emit("安装 ursina（可能需要几分钟）…")
            code = self._run([str(python), "-m", "pip", "install", "-U", "pip", "ursina"])
            if code != 0:
                self.done.emit(False, "安装依赖失败，请检查网络")
                return
            info = probe_python(python, timeout=60)
            if info.get("ok"):
                self.done.emit(True, str(python))
            else:
                self.done.emit(False, f"安装完成但仍无法导入：{info.get('error')}")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"{type(exc).__name__}: {exc}")


# ============================ 自绘组件 ============================

class StatusDot(QWidget):
    def __init__(self, color=C_MUTED, size=8, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size + 6, size + 6)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        glow = QColor(self._color)
        glow.setAlpha(60)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(self.rect())
        p.setBrush(self._color)
        r = self.rect().adjusted(3, 3, -3, -3)
        p.drawEllipse(r)


class StatusRow(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(8)
        self.dot = StatusDot()
        self.title = QLabel(title)
        self.title.setFixedWidth(64)
        self.value = QLabel("—")
        self.value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.dot)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        self.set_state("wait", "检测中…")

    def set_state(self, state, text):
        colors = {"ok": C_OK, "bad": C_BAD, "warn": C_WARN, "wait": C_MUTED, "info": C_INFO}
        self.dot.set_color(colors.get(state, C_MUTED))
        self.value.setText(text)
        color = C_TEXT if state in ("ok", "info") else (C_MUTED if state == "wait" else colors[state])
        self.value.setStyleSheet(f"color:{color}; font-size:12px;")


class Card(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 14, 18, 16)
        self.body.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.head = head
        self.body.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(6)
        self.body.addLayout(self.content)


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(46, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self):
        return self._checked

    def setChecked(self, value, animate=True):
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        target = 1.0 if value else 0.0
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._pos = target
            self.update()
        self.toggled.emit(value)

    def get_pos(self):
        return self._pos

    def set_pos(self, value):
        self._pos = value
        self.update()

    pos = Property(float, get_pos, set_pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        off = QColor("#1B2432")
        on = QColor(C_ACCENT)
        blend = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        p.setPen(QPen(QColor(C_BORDER), 1))
        p.setBrush(blend)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        knob_x = 3 + (self.width() - 24) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#F4F8FF"))
        p.drawEllipse(QRectF(knob_x, 3, 18, 18))


class HeroPanel(QWidget):
    """左侧主视觉：网格、光晕、旋转准星"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(392)
        self._angle = 0.0
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        self._angle = (self._angle + 0.7) % 360
        self._phase += 0.05
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 只裁左侧两个圆角（右侧与主面板接壤，保持直角）
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w + 16, h), 16, 16)
        p.setClipPath(clip)

        # 背景渐变
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor("#131B29"))
        grad.setColorAt(0.55, QColor("#0C1119"))
        grad.setColorAt(1, QColor("#090C11"))
        p.fillRect(self.rect(), grad)

        # 网格
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        step = 28
        for x in range(0, w, step):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, step):
            p.drawLine(0, y, w, y)

        # 光晕
        cx, cy = w * 0.5, h * 0.36
        glow = QRadialGradient(cx, cy, 210)
        accent = QColor(C_ACCENT)
        glow.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 46))
        glow.setColorAt(0.6, QColor(accent.red(), accent.green(), accent.blue(), 12))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(cx - 210, cy - 210, 420, 420))

        # 准星
        p.save()
        p.translate(cx, cy)
        pulse = 1.0 + 0.05 * math.sin(self._phase * 2)
        radius = 78 * pulse
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1))
        p.drawEllipse(QRectF(-radius, -radius, radius * 2, radius * 2))
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 120), 1.4))
        p.drawEllipse(QRectF(-radius * 0.62, -radius * 0.62, radius * 1.24, radius * 1.24))

        p.rotate(self._angle)
        p.setPen(QPen(QColor(C_ACCENT), 2.2))
        for i in range(4):
            p.drawLine(0, -radius - 2, 0, -radius - 16)
            p.rotate(90)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in range(4):
            p.drawLine(0, -radius * 0.62 + 12, 0, -radius * 0.62 + 26)
            p.rotate(90)
        p.restore()

        # 中心点
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_ACCENT))
        p.drawEllipse(QRectF(cx - 2.5, cy - 2.5, 5, 5))

        # 标题
        p.setPen(QColor(C_TEXT))
        f = QFont(FONT_FAMILY, 0)
        f.setPixelSize(44)
        f.setWeight(QFont.Black)
        p.setFont(f)
        p.drawText(QRectF(36, h - 196, w - 72, 58), Qt.AlignLeft | Qt.AlignBottom, "射击")

        p.setPen(QColor(C_ACCENT))
        f2 = QFont("Consolas", 0)
        f2.setPixelSize(12)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f2)
        p.drawText(QRectF(38, h - 130, w - 72, 20), Qt.AlignLeft, "SHOOTER  /  简约 3D")

        # 分割线 + 底部信息
        p.setPen(QPen(QColor(C_BORDER), 1))
        p.drawLine(38, h - 96, w - 38, h - 96)
        p.setPen(QColor(C_MUTED))
        f3 = QFont(FONT_FAMILY, 0)
        f3.setPixelSize(11)
        p.setFont(f3)
        p.drawText(QRectF(38, h - 78, w - 76, 18), Qt.AlignLeft, f"客户端 v{APP_VERSION}   ·   Powered by ursina")



class LogBox(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("LogBox")
        self.setFixedHeight(104)
        self.setFont(QFont(FONT_FAMILY_MONO, 9))

    def append_line(self, text):
        self.append(text.replace("\r", ""))
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ============================ 主窗口 ============================

class LauncherWindow(QWidget):
    def __init__(self, nickname="玩家"):
        super().__init__()
        self.cfg = load_config()
        self.nickname = nickname or self.cfg.get("nickname") or "玩家"
        self.game_path = locate_game(self.cfg)
        self.game_dir = game_dir_of(self.game_path)
        self.env = {}
        self.probe_thread = None
        self.repair_thread = None
        self.game_proc = None
        self.started_at = 0.0
        self._drag_origin = None
        self._window_origin = None
        self._game_finished_cb = None
        self._game_tag = "game"
        self.lobby = None

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(1140, 720)
        self._apply_global_style()
        self._build_ui()
        self._restore_position()
        self._refresh_scores()
        self._load_settings_into_ui(read_game_settings(self.game_dir))
        QTimer.singleShot(180, self.start_env_check)

    # ---------- 样式 ----------
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QWidget {{
                color: {C_TEXT};
                font-family: "{FONT_FAMILY}";
                font-size: 12px;
            }}
            QFrame#Card {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                border-radius: 14px;
            }}
            QLabel#CardTitle {{
                color: {C_MUTED};
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            QLabel#Hint {{ color: {C_MUTED}; font-size: 11px; }}
            QLabel#BigScore {{
                color: {C_ACCENT};
                font-family: "Consolas";
                font-size: 34px;
                font-weight: 700;
            }}
            QComboBox {{
                background: {C_PANEL_2};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 5px 10px;
                min-width: 108px;
                color: {C_TEXT};
            }}
            QComboBox:hover {{ border-color: #33445C; }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {C_PANEL};
                border: 1px solid {C_BORDER};
                selection-background-color: {C_ACCENT_DIM};
                outline: none;
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: #1B2432;
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {C_ACCENT};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #F4F8FF;
                width: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }}
            QPushButton#Ghost {{
                background: transparent;
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                color: {C_MUTED};
            }}
            QPushButton#Ghost:hover {{
                border-color: {C_ACCENT};
                color: {C_TEXT};
            }}
            QPushButton#Ghost:pressed {{ background: #16202D; }}
            QPushButton#WindowBtn {{
                background: transparent;
                border: none;
                color: {C_MUTED};
                font-size: 14px;
            }}
            QPushButton#WindowBtn:hover {{
                background: #1A2330;
                color: {C_TEXT};
                border-radius: 6px;
            }}
            QPushButton#CloseBtn {{
                background: transparent;
                border: none;
                color: {C_MUTED};
                font-size: 14px;
            }}
            QPushButton#CloseBtn:hover {{
                background: #C0392B;
                color: white;
                border-radius: 6px;
            }}
            QTextEdit#LogBox {{
                background: {C_PANEL_2};
                border: 1px solid {C_BORDER};
                border-radius: 10px;
                color: #9FB0C8;
                padding: 8px;
            }}
        """)

    # ---------- 界面 ----------
    def _build_ui(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        shell.addLayout(row)

        self.hero = HeroPanel()
        row.addWidget(self.hero)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        row.addLayout(right, 1)

        # 顶部栏
        top = QHBoxLayout()
        top.setContentsMargins(26, 14, 14, 6)
        brand = QLabel("客户 端 控 制 台")
        brand.setStyleSheet(f"color:{C_MUTED}; font-size:11px; letter-spacing:2px;")
        top.addWidget(brand)
        self.lbl_nick = QLabel(f"●  {self.nickname}")
        self.lbl_nick.setStyleSheet(
            f"color:{C_TEXT}; background:{C_PANEL_2}; border:1px solid {C_BORDER};"
            f"border-radius:10px; padding:2px 10px; font-size:11px;"
        )
        top.addWidget(self.lbl_nick)
        self.btn_switch = QPushButton("切换")
        self.btn_switch.setObjectName("WindowBtn")
        self.btn_switch.setCursor(Qt.PointingHandCursor)
        self.btn_switch.setFixedSize(38, 22)
        self.btn_switch.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{C_MUTED};font-size:11px;}}"
            f"QPushButton:hover{{color:{C_ACCENT};}}"
        )
        self.btn_switch.clicked.connect(self.switch_account)
        top.addWidget(self.btn_switch)
        top.addStretch(1)
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("WindowBtn")
        self.btn_min.setFixedSize(30, 26)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("CloseBtn")
        self.btn_close.setFixedSize(30, 26)
        self.btn_close.clicked.connect(self.close)
        top.addWidget(self.btn_min)
        top.addWidget(self.btn_close)
        right.addLayout(top)

        content = QVBoxLayout()
        content.setContentsMargins(24, 8, 26, 6)
        content.setSpacing(12)
        right.addLayout(content, 1)

        # ---- 环境状态 ----
        env_card = Card("环境状态")
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_recheck = QPushButton("重新检测")
        self.btn_recheck.setObjectName("Ghost")
        self.btn_recheck.clicked.connect(self.start_env_check)
        self.btn_repair = QPushButton("修复环境")
        self.btn_repair.setObjectName("Ghost")
        self.btn_repair.clicked.connect(self.repair_env)
        self.btn_sound = QPushButton("补齐音效")
        self.btn_sound.setObjectName("Ghost")
        self.btn_sound.clicked.connect(self.generate_sound)
        for b in (self.btn_recheck, self.btn_repair, self.btn_sound):
            b.setCursor(Qt.PointingHandCursor)
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        env_card.head.addLayout(btn_row)

        self.row_python = StatusRow("解释器")
        self.row_engine = StatusRow("引擎")
        self.row_font = StatusRow("中文字体")
        self.row_audio = StatusRow("音效")
        for r in (self.row_python, self.row_engine, self.row_font, self.row_audio):
            env_card.content.addWidget(r)
        content.addWidget(env_card)

        # ---- 游戏设置 ----
        set_card = Card("游戏设置")
        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.setObjectName("Ghost")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self.reset_settings)
        set_card.head.addWidget(self.btn_reset)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(9)

        grid.addWidget(self._label("窗口尺寸"), 0, 0)
        self.combo_size = QComboBox()
        for w, h in ((1280, 720), (1600, 900), (1920, 1080), (2560, 1440)):
            self.combo_size.addItem(f"{w} × {h}", (w, h))
        self.combo_size.currentIndexChanged.connect(self.save_settings_from_ui)
        grid.addWidget(self.combo_size, 0, 1)

        grid.addWidget(self._label("全屏"), 0, 2)
        self.sw_fullscreen = ToggleSwitch()
        self.sw_fullscreen.toggled.connect(self.save_settings_from_ui)
        grid.addWidget(self.sw_fullscreen, 0, 3, Qt.AlignLeft)

        grid.addWidget(self._label("灵敏度"), 1, 0)
        self.slider_sens = QSlider(Qt.Horizontal)
        self.slider_sens.setRange(5, 120)
        self.slider_sens.valueChanged.connect(self._on_sens_changed)
        self.slider_sens.sliderReleased.connect(self.save_settings_from_ui)
        grid.addWidget(self.slider_sens, 1, 1)
        self.lbl_sens = QLabel("40")
        self.lbl_sens.setFixedWidth(34)
        self.lbl_sens.setStyleSheet(f"color:{C_MUTED}; font-family:Consolas;")
        grid.addWidget(self.lbl_sens, 1, 2)

        grid.addWidget(self._label("音量"), 2, 0)
        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.valueChanged.connect(self._on_vol_changed)
        self.slider_vol.sliderReleased.connect(self.save_settings_from_ui)
        grid.addWidget(self.slider_vol, 2, 1)
        self.lbl_vol = QLabel("100%")
        self.lbl_vol.setFixedWidth(34)
        self.lbl_vol.setStyleSheet(f"color:{C_MUTED}; font-family:Consolas;")
        grid.addWidget(self.lbl_vol, 2, 2)

        grid.setColumnStretch(1, 1)
        set_card.content.addLayout(grid)
        hint = QLabel("设置会写入 settings.json，下次启动游戏时生效")
        hint.setObjectName("Hint")
        set_card.content.addWidget(hint)
        content.addWidget(set_card)

        # ---- 底部两张卡 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        score_card = Card("战绩")
        score_row = QHBoxLayout()
        score_row.setSpacing(6)
        score_col = QVBoxLayout()
        score_col.setSpacing(0)
        self.lbl_best = QLabel("0")
        self.lbl_best.setObjectName("BigScore")
        score_col.addWidget(self.lbl_best)
        cap = QLabel("历史最高分")
        cap.setObjectName("Hint")
        score_col.addWidget(cap)
        score_row.addLayout(score_col)
        score_row.addStretch(1)
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.lbl_last = QLabel("最近一局  —")
        self.lbl_last.setStyleSheet(f"color:{C_TEXT}; font-size:12px;")
        self.lbl_when = QLabel("—")
        self.lbl_when.setObjectName("Hint")
        info_col.addWidget(self.lbl_last)
        info_col.addWidget(self.lbl_when)
        info_col.addStretch(1)
        score_row.addLayout(info_col)
        score_card.content.addLayout(score_row)
        bottom.addWidget(score_card, 1)

        about_card = Card("客户端")
        ver_row = QHBoxLayout()
        ver_row.addWidget(self._label(f"版本 {APP_VERSION}"))
        ver_row.addStretch(1)
        self.btn_update = QPushButton("检查更新")
        self.btn_update.setObjectName("Ghost")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self.check_update)
        ver_row.addWidget(self.btn_update)
        about_card.content.addLayout(ver_row)

        quick = QHBoxLayout()
        quick.setSpacing(8)
        for text, handler in (
            ("打开目录", self.open_game_dir),
            ("查看日志", self.open_log_dir),
            ("打开配置", self.open_settings_file),
        ):
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(handler)
            quick.addWidget(b)
        about_card.content.addLayout(quick)
        bottom.addWidget(about_card, 1)
        content.addLayout(bottom)
        content.addStretch(1)

        # ---- 日志抽屉 ----
        self.log_box = LogBox()
        self.log_box.setVisible(False)
        content.addWidget(self.log_box)

        # ---- 底栏 ----
        bar = QHBoxLayout()
        bar.setContentsMargins(26, 10, 22, 18)
        bar.setSpacing(10)

        status_col = QVBoxLayout()
        status_col.setSpacing(2)
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet(f"color:{C_TEXT}; font-size:12px;")
        self.lbl_path = QLabel(str(self.game_path))
        self.lbl_path.setObjectName("Hint")
        self.lbl_path.setMaximumWidth(420)
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_col.addWidget(self.lbl_status)
        status_col.addWidget(self.lbl_path)
        bar.addLayout(status_col)
        bar.addStretch(1)

        self.btn_log = QPushButton("日志")
        self.btn_log.setObjectName("Ghost")
        self.btn_log.setCursor(Qt.PointingHandCursor)
        self.btn_log.clicked.connect(self.toggle_log)
        bar.addWidget(self.btn_log)

        self.btn_launch = QPushButton("开 始 游 戏")
        self.btn_launch.setCursor(Qt.PointingHandCursor)
        self.btn_launch.setFixedSize(196, 50)
        self.btn_launch.clicked.connect(self.toggle_game)
        self.btn_launch.setEnabled(False)
        self.btn_launch.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 {C_ACCENT}, stop:1 #FF8B57);
                color: #1A0D06;
                border: none;
                border-radius: 12px;
                font-size: 16px;
                font-weight: 800;
                letter-spacing: 2px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #FF7B4B, stop:1 #FFA070);
            }}
            QPushButton:pressed {{ background: #E05A28; }}
            QPushButton:disabled {{
                background: #2A3342;
                color: {C_MUTED};
            }}
        """)
        self.glow = QGraphicsDropShadowEffect(self)
        self.glow.setBlurRadius(34)
        self.glow.setOffset(0, 6)
        self.glow.setColor(QColor(255, 107, 53, 110))
        self.btn_launch.setGraphicsEffect(self.glow)
        bar.addWidget(self.btn_launch)
        right.addLayout(bar)

    @staticmethod
    def _label(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{C_MUTED}; font-size:11px;")
        return lbl

    # ---------- 窗口绘制 ----------
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0, QColor(C_BG))
        grad.setColorAt(1, QColor("#080B10"))
        p.fillPath(path, grad)
        p.setPen(QPen(QColor("#232E3E"), 1))
        p.drawPath(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._window_origin = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin and event.buttons() & Qt.LeftButton:
            self.move(self._window_origin + event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    # ---------- 位置记忆 ----------
    def _restore_position(self):
        try:
            x, y = self.cfg.get("window_x"), self.cfg.get("window_y")
            if isinstance(x, int) and isinstance(y, int):
                screens = QApplication.screens()
                for screen in screens:
                    if screen.availableGeometry().contains(QPoint(x + 40, y + 40)):
                        self.move(x, y)
                        return
        except (TypeError, ValueError):
            pass
        geo = self.frameGeometry()
        geo.moveCenter(self.screen().availableGeometry().center())
        self.move(geo.topLeft())

    def closeEvent(self, event):
        self.cfg["window_x"], self.cfg["window_y"] = self.x(), self.y()
        save_config(self.cfg)
        if self.lobby is not None:
            try:
                self.lobby.close()
            except Exception:  # noqa: BLE001
                pass
            self.lobby = None
        if self.game_proc and self.game_proc.state() != QProcess.NotRunning:
            self.game_proc.kill()
            self.game_proc.waitForFinished(1500)
        super().closeEvent(event)

    # ---------- 环境自检 ----------
    def start_env_check(self):
        self.row_python.set_state("wait", "检测中…")
        self.row_engine.set_state("wait", "检测中…")
        self.row_font.set_state("wait", "检测中…")
        self.btn_recheck.setEnabled(False)
        self.lbl_status.setText("正在检测运行环境…")

        # 文件类检查先做（快）
        ok_font, font_text = check_font(self.game_dir)
        self.row_font.set_state("ok" if ok_font else "warn", font_text)
        ok_audio, audio_text = check_audio(self.game_dir)
        self.row_audio.set_state("ok" if ok_audio else "warn",
                                 audio_text if ok_audio else "未找到（可点“补齐音效”）")

        self.probe_thread = EnvProbeThread(self.game_dir, self.cfg, self)
        self.probe_thread.progress.connect(lambda t: self.lbl_status.setText(t))
        self.probe_thread.done.connect(self._on_probe_done)
        self.probe_thread.start()

    def _on_probe_done(self, info):
        self.btn_recheck.setEnabled(True)
        self.env = info
        if info.get("ok"):
            version = f"Python {info.get('python', '?')} · {info.get('bits', '?')} 位"
            path = Path(info.get("python_path", ""))
            label = path.parent.name if path.parent.name.lower() != "scripts" else path.parent.parent.name
            self.row_python.set_state("ok", f"{version}   {label}")
            self.row_engine.set_state(
                "ok", f"ursina {info.get('ursina', '?')}  /  panda3d {info.get('panda3d', '?')}"
            )
            self.cfg["last_good_python"] = str(path)
            save_config(self.cfg)
            self.lbl_status.setText("环境就绪")
            self.btn_launch.setEnabled(True)
            self.btn_repair.setVisible(False)
        else:
            self.row_python.set_state("bad", info.get("error", "不可用"))
            self.row_engine.set_state("bad", "未检测到 ursina")
            self.lbl_status.setText("环境异常，请点“修复环境”")
            self.btn_launch.setEnabled(False)
            self.btn_repair.setVisible(True)
            detail = info.get("detail") or []
            self.log_box.setVisible(True)
            self.log_box.clear()
            self.log_box.append_line("【环境检测失败】")
            for line in detail[:12]:
                self.log_box.append_line(line)

    def repair_env(self):
        if self.repair_thread and self.repair_thread.isRunning():
            return
        pythons = candidate_pythons(self.game_dir, self.cfg)
        usable = [p for p in pythons if "_probe_skip" not in str(p)]
        if not usable:
            QMessageBox.warning(self, "无法修复", "没有找到可用的 Python 安装，请先安装 Python 3.11/3.12。")
            return
        base = usable[0]
        self.log_box.setVisible(True)
        self.log_box.append_line(f"【开始修复环境】基础解释器：{base}")
        self.lbl_status.setText("正在修复运行环境…")
        self.btn_repair.setEnabled(False)
        self.repair_thread = RepairThread(base, self.game_dir, self)
        self.repair_thread.line.connect(self.log_box.append_line)
        self.repair_thread.done.connect(self._on_repair_done)
        self.repair_thread.start()

    def _on_repair_done(self, ok, message):
        self.btn_repair.setEnabled(True)
        if ok:
            self.log_box.append_line(f"修复完成：{message}")
            self.lbl_status.setText("环境已修复，正在重新检测…")
            self.cfg["python_path"] = message
            save_config(self.cfg)
            self.start_env_check()
        else:
            self.log_box.append_line(f"修复失败：{message}")
            self.lbl_status.setText("修复失败，请查看日志")
            QMessageBox.warning(self, "修复失败", message)

    # ---------- 设置 ----------
    def _load_settings_into_ui(self, settings):
        size = (int(settings["window_width"]), int(settings["window_height"]))
        index = self.combo_size.findData(size)
        if index < 0:
            self.combo_size.addItem(f"{size[0]} × {size[1]}", size)
            index = self.combo_size.count() - 1
        self.combo_size.blockSignals(True)
        self.combo_size.setCurrentIndex(index)
        self.combo_size.blockSignals(False)

        self.sw_fullscreen.blockSignals(True)
        self.sw_fullscreen.setChecked(bool(settings["fullscreen"]), animate=False)
        self.sw_fullscreen.blockSignals(False)

        self.slider_sens.blockSignals(True)
        self.slider_sens.setValue(int(round(settings["sensitivity"])))
        self.slider_sens.blockSignals(False)
        self.lbl_sens.setText(str(int(round(settings["sensitivity"]))))

        self.slider_vol.blockSignals(True)
        self.slider_vol.setValue(int(round(settings["volume"] * 100)))
        self.slider_vol.blockSignals(False)
        self.lbl_vol.setText(f"{int(round(settings['volume'] * 100))}%")

    def _on_sens_changed(self, value):
        self.lbl_sens.setText(str(value))

    def _on_vol_changed(self, value):
        self.lbl_vol.setText(f"{value}%")

    def _collect_settings(self):
        w, h = self.combo_size.currentData() or (1600, 900)
        return {
            "window_width": int(w),
            "window_height": int(h),
            "fullscreen": bool(self.sw_fullscreen.isChecked()),
            "sensitivity": float(self.slider_sens.value()),
            "volume": round(self.slider_vol.value() / 100.0, 2),
        }

    def save_settings_from_ui(self, *args):
        if write_game_settings(self.game_dir, self._collect_settings()):
            self.flash_status("设置已保存，下次启动生效")
        else:
            self.flash_status("设置保存失败（目录不可写）")

    def reset_settings(self):
        write_game_settings(self.game_dir, dict(DEFAULT_GAME_SETTINGS))
        self._load_settings_into_ui(dict(DEFAULT_GAME_SETTINGS))
        self.flash_status("已恢复默认设置")

    # ---------- 战绩 ----------
    def _refresh_scores(self):
        data = read_scores(self.game_dir)
        self.lbl_best.setText(str(data.get("best", 0) or 0))
        self.lbl_last.setText(f"最近一局  {data.get('last', 0) or 0}")
        self.lbl_when.setText(data.get("updated") or "暂无记录")

    # ---------- 启动 / 模式选择 ----------

    def toggle_game(self):
        if self.game_proc and self.game_proc.state() != QProcess.NotRunning:
            self.stop_game()
        else:
            self.open_mode_select()

    def open_mode_select(self):
        if self.game_proc and self.game_proc.state() != QProcess.NotRunning:
            self.flash_status("游戏正在运行，请先结束游戏")
            return
        dlg = net_ui.ModeSelectDialog(self.nickname, self)
        if dlg.exec() != QDialog.Accepted:
            return
        mode = dlg.mode
        self.cfg["last_mode"] = mode
        save_config(self.cfg)
        if mode == "training":
            self.start_game()
            return
        net_dlg = net_ui.NetModeDialog(net_ui.MODE_TEXT.get(mode, ""), self)
        if net_dlg.exec() != QDialog.Accepted:
            return
        if net_dlg.choice == "host":
            self.host_room(mode)
        elif net_dlg.choice == "join":
            self.join_room()

    def host_room(self, mode):
        dlg = net_ui.CreateRoomDialog(self.nickname, mode, self)
        if dlg.exec() != QDialog.Accepted or not dlg.config:
            return
        cfg = dlg.config
        server = rn.RoomService(
            self.nickname, cfg["mode"],
            room_name=cfg["room_name"], password=cfg["password"], settings=cfg,
        )
        if not server.start():
            QMessageBox.critical(
                self, "创建房间失败",
                f"无法监听端口 {rn.ROOM_PORT}。\n"
                "可能是上一个房间还没释放，或该端口被其他程序占用；请稍后再试。",
            )
            return
        self._open_lobby("host", server=server, room_info=server.room)

    def join_room(self):
        dlg = net_ui.JoinRoomDialog(self.nickname, self)
        if dlg.exec() != QDialog.Accepted or dlg.client is None:
            return
        self._open_lobby("guest", client=dlg.client, room_info=dlg.client.room)

    def _open_lobby(self, role, server=None, client=None, room_info=None):
        callbacks = {
            "python_ready": lambda: bool(self.env.get("ok")) or bool(self.cfg.get("last_good_python")),
            "launch_game": self.launch_online_game,
            "on_leave": self._on_lobby_closed,
        }
        self.lobby = net_ui.RoomLobbyWindow(
            self.nickname, role,
            server=server, client=client, callbacks=callbacks, room_info=room_info,
        )
        geo = self.lobby.frameGeometry()
        geo.moveCenter(self.screen().availableGeometry().center())
        self.lobby.move(geo.topLeft())
        self.lobby.show()
        self.lobby.raise_()
        self.hide()

    def _on_lobby_closed(self):
        self.lobby = None
        self.show()
        self.raise_()
        self._refresh_scores()

    def switch_account(self):
        dlg = net_ui.LoginDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted and dlg.nickname:
            self.nickname = dlg.nickname
            self.cfg["nickname"] = dlg.nickname
            save_config(self.cfg)
            self.lbl_nick.setText(f"●  {self.nickname}")
            self.flash_status(f"已切换为 {self.nickname}")

    def launch_online_game(self, extra_args, tag, on_finished):
        return self.start_game(extra_args=extra_args, tag=tag, on_finished=on_finished)

    def start_game(self, extra_args=None, tag="game", on_finished=None):
        python = self.env.get("python_path") or self.cfg.get("last_good_python")
        if not python:
            QMessageBox.warning(self, "无法启动", "未找到可用的 Python 环境，请先点“修复环境”。")
            return False
        if not self.game_path.is_file():
            QMessageBox.warning(self, "无法启动", f"找不到游戏文件：\n{self.game_path}")
            return False

        args = [str(self.game_path)] + list(extra_args or [])
        self._game_finished_cb = on_finished
        self._game_tag = tag

        self.log_box.setVisible(True)
        self.log_box.clear()
        self.log_box.append_line(f"$ {python} \"{self.game_path.name}\" {' '.join(extra_args or [])}")
        self.log_dir().mkdir(parents=True, exist_ok=True)
        log_name = "latest.log" if tag == "game" else f"{tag}.log"
        self._log_file = open(self.log_dir() / log_name, "w", encoding="utf-8")

        self.game_proc = QProcess(self)
        self.game_proc.setProgram(python)
        self.game_proc.setArguments(args)
        self.game_proc.setWorkingDirectory(str(self.game_dir))
        self.game_proc.setProcessChannelMode(QProcess.MergedChannels)
        self.game_proc.readyReadStandardOutput.connect(self._read_game_output)
        self.game_proc.finished.connect(self._on_game_finished)
        self.game_proc.errorOccurred.connect(self._on_game_error)
        self.game_proc.start()

        self.started_at = time.time()
        self._set_running_ui(True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_running_status)
        self._timer.start(1000)
        return True

    def _set_running_ui(self, running):
        if running:
            self.btn_launch.setText("结 束 游 戏")
            self.btn_launch.setStyleSheet(f"""
                QPushButton {{
                    background: #2A1620;
                    color: #FF8A96;
                    border: 1px solid #5A2634;
                    border-radius: 12px;
                    font-size: 15px;
                    font-weight: 700;
                    letter-spacing: 2px;
                }}
                QPushButton:hover {{ background: #3A1B27; }}
            """)
            self.glow.setColor(QColor(255, 77, 94, 90))
            self.lbl_status.setText("游戏运行中…")
        else:
            self.btn_launch.setText("开 始 游 戏")
            self.btn_launch.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {C_ACCENT}, stop:1 #FF8B57);
                    color: #1A0D06;
                    border: none;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 800;
                    letter-spacing: 2px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #FF7B4B, stop:1 #FFA070);
                }}
                QPushButton:pressed {{ background: #E05A28; }}
            """)
            self.glow.setColor(QColor(255, 107, 53, 110))
            self.lbl_status.setText("就绪")

    def _read_game_output(self):
        if not self.game_proc:
            return
        text = bytes(self.game_proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                self.log_box.append_line(line)
                try:
                    self._log_file.write(line + "\n")
                    self._log_file.flush()
                except (OSError, AttributeError):
                    pass

    def _update_running_status(self):
        if not self.game_proc or self.game_proc.state() == QProcess.NotRunning:
            return
        elapsed = int(time.time() - self.started_at)
        self.lbl_status.setText(f"游戏运行中 · {elapsed // 60:02d}:{elapsed % 60:02d}")

    def _on_game_error(self, error):
        if error == QProcess.FailedToStart:
            self._set_running_ui(False)
            QMessageBox.critical(self, "启动失败", "无法启动 Python 进程，请检查解释器路径。")

    def _on_game_finished(self, code, status):
        self._set_running_ui(False)
        if hasattr(self, "_timer"):
            self._timer.stop()
        try:
            self._log_file.close()
        except (OSError, AttributeError):
            pass
        self._refresh_scores()
        cb = self._game_finished_cb
        self._game_finished_cb = None
        if cb:
            try:
                cb(code, status)
            except Exception:  # noqa: BLE001
                pass
        if self._game_tag != "game":
            return
        if code == 0:
            self.flash_status("游戏已退出")
        else:
            self.flash_status("游戏异常退出，已记录日志")
            tail = self.log_box.toPlainText().strip().splitlines()[-14:]
            box = QMessageBox(self)
            box.setWindowTitle("游戏异常退出")
            box.setIcon(QMessageBox.Warning)
            box.setText(f"游戏进程结束（退出码 {code}）。")
            box.setDetailedText("\n".join(tail) if tail else "无输出")
            box.exec()

    def stop_game(self):
        if self.game_proc and self.game_proc.state() != QProcess.NotRunning:
            self.log_box.append_line("正在结束游戏进程…")
            self.game_proc.kill()
            self.game_proc.waitForFinished(2000)

    # ---------- 资源 ----------
    def generate_sound(self):
        game_dir = self.game_dir
        if (game_dir / "hit.wav").exists() or (game_dir / "hit.ogg").exists():
            self.flash_status("已有音效文件，无需生成")
            return
        if make_placeholder_sound(game_dir):
            self.row_audio.set_state("ok", "hit.wav（占位）")
            self.flash_status("已生成占位音效 hit.wav")
        else:
            self.flash_status("生成音效失败（目录不可写）")

    # ---------- 快捷操作 ----------
    def open_game_dir(self):
        self._open_path(self.game_dir)

    def log_dir(self):
        return self.game_dir / "logs"

    def open_log_dir(self):
        self.log_dir().mkdir(parents=True, exist_ok=True)
        self._open_path(self.log_dir())

    def open_settings_file(self):
        path = self.game_dir / "settings.json"
        if not path.exists():
            write_game_settings(self.game_dir, self._collect_settings())
        self._open_path(path)

    @staticmethod
    def _open_path(path: Path):
        try:
            os.startfile(str(path))  # noqa: S606
        except (OSError, AttributeError):
            pass

    def toggle_log(self):
        self.log_box.setVisible(not self.log_box.isVisible())

    # ---------- 更新 ----------
    def check_update(self):
        url = (self.cfg.get("update_url") or "").strip()
        if not url:
            self.flash_status("未配置更新源（可在 config.json 设置 update_url）")
            return
        self.lbl_status.setText("正在检查更新…")
        try:
            with urllib.request.urlopen(url, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = str(data.get("version", "")).strip()
            if latest and latest != APP_VERSION:
                self.flash_status(f"发现新版本 {latest}（当前 {APP_VERSION}）")
            else:
                self.flash_status(f"已是最新版本 {APP_VERSION}")
        except Exception as exc:  # noqa: BLE001
            self.flash_status(f"更新检查失败：{type(exc).__name__}")

    # ---------- 状态提示 ----------
    def flash_status(self, text, msec=3200):
        self.lbl_status.setText(text)
        if hasattr(self, "_flash_timer") and self._flash_timer:
            self._flash_timer.stop()
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(
            lambda: self.lbl_status.setText("就绪")
        )
        self._flash_timer.start(msec)


# ============================ 单实例 ============================

def acquire_single_instance():
    lock = QLockFile(str(Path(os.environ.get("TEMP", ".")) / "shooting_launcher.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    return None


# ============================ selftest / 截图 ============================

def run_selftest():
    cfg = load_config()
    game_path = locate_game(cfg)
    game_dir = game_dir_of(game_path)
    report = {
        "version": APP_VERSION,
        "frozen": FROZEN,
        "game_path": str(game_path),
        "game_exists": game_path.is_file(),
        "settings": read_game_settings(game_dir),
        "scores": read_scores(game_dir),
        "font": check_font(game_dir),
        "audio": check_audio(game_dir),
        "net": {
            "port": rn.ROOM_PORT,
            "local_ip": rn.local_ip(),
            "prefixes": rn.subnet_prefixes(),
        },
        "pythons": [],
    }
    for py in candidate_pythons(game_dir, cfg)[:6]:
        info = probe_python(py, timeout=25)
        report["pythons"].append({
            "path": str(py),
            "ok": info.get("ok"),
            "python": info.get("python"),
            "ursina": info.get("ursina"),
            "error": info.get("error"),
        })
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    # 打包成 windowed exe 后没有控制台，报告同时写文件，便于自检
    try:
        out = Path(os.environ.get("TEMP", ".")) / "shooting_launcher_selftest.json"
        out.write_text(text, encoding="utf-8")
    except OSError:
        pass
    return 0 if report["game_exists"] else 1


def _pump(app, frames=160, delay=0.03):
    for _ in range(frames):
        app.processEvents()
        time.sleep(delay)


def run_screenshot(path):
    app = QApplication.instance() or QApplication(sys.argv)
    win = LauncherWindow(nickname="Ghost_07")
    win.show()
    screen_w = app.primaryScreen().geometry().width()
    win.move(screen_w + 200, 100)  # 移到屏幕外，不干扰用户
    _pump(app)
    win.grab().save(path)
    print(f"saved: {path}")
    return 0


def run_login_screenshot(path):
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = net_ui.LoginDialog(load_config())
    dlg.show()
    screen_w = app.primaryScreen().geometry().width()
    dlg.move(screen_w + 200, 100)
    _pump(app, 60)
    dlg.grab().save(path)
    print(f"saved: {path}")
    return 0


def run_lobby_screenshot(path, role="host"):
    app = QApplication.instance() or QApplication(sys.argv)
    server = rn.RoomService("Ghost_07", "team5", room_name="夜莺小队", password="",
                            settings={"score_target": 30, "time_limit": 600})
    server.start()
    server.execute_command("bot add 红 2")
    server.execute_command("bot add 蓝 3")
    callbacks = {"python_ready": lambda: True, "launch_game": lambda *a: True, "on_leave": lambda: None}
    win = net_ui.RoomLobbyWindow("Ghost_07", role, server=server, callbacks=callbacks,
                                 room_info=server.room)
    win.show()
    screen_w = app.primaryScreen().geometry().width()
    win.move(screen_w + 300, 60)
    _pump(app, 80)
    if role == "host":
        win._toggle_console()
        win.console_box.append("[00:00:00] [系统] 控制台就绪，输入 help 查看命令")
        win.console_box.append("[00:00:12] 房主&gt; god all")
        win.console_box.append("[00:00:12] 已下发无敌 → Ghost_07、小王")
        win._pump_console = True
    _pump(app, 30)
    win.grab().save(path)
    print(f"saved: {path}")
    server.stop()
    return 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return run_selftest()
    if "--screenshot" in argv:
        idx = argv.index("--screenshot")
        out = argv[idx + 1] if idx + 1 < len(argv) else "launcher.png"
        return run_screenshot(out)
    if "--shot-login" in argv:
        idx = argv.index("--shot-login")
        out = argv[idx + 1] if idx + 1 < len(argv) else "login.png"
        return run_login_screenshot(out)
    if "--shot-lobby" in argv:
        idx = argv.index("--shot-lobby")
        out = argv[idx + 1] if idx + 1 < len(argv) else "lobby.png"
        role = argv[idx + 2] if len(argv) > idx + 2 and argv[idx + 2] in ("host", "guest") else "host"
        return run_lobby_screenshot(out, role)

    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    lock = acquire_single_instance()
    if lock is None:
        QMessageBox.information(None, APP_NAME, "启动器已经在运行了。")
        return 0

    cfg = load_config()
    login = net_ui.LoginDialog(cfg)
    if login.exec() != QDialog.Accepted or not login.nickname:
        lock.unlock()
        return 0
    cfg["nickname"] = login.nickname
    save_config(cfg)

    window = LauncherWindow(login.nickname)
    window.show()
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
