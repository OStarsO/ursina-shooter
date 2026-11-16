# -*- coding: utf-8 -*-
"""射击 · 客户端启动器

功能：
  P0  一键启动 / 运行环境自检 / 启动日志与崩溃提示 / 单实例与进程托管
  P1  游戏设置（窗口、全屏、灵敏度、音量）/ 资源状态与补齐 / 最高分 / 版本检查 / 快捷操作

依赖：PySide6
"""

import sys
import os
import io
import json
import math
import random
import struct
import wave
import shutil
import socket
import subprocess
import http.client
import urllib.error
import urllib.parse
import urllib.request
import platform
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QProcess, QPropertyAnimation, QEasingCurve,
    QPoint, QRectF, Property, QLockFile,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QFont, QLinearGradient, QRadialGradient,
    QPainterPath, QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QMessageBox, QComboBox, QSlider,
    QGridLayout, QTextEdit, QSizePolicy, QDialog, QStackedWidget,
    QLineEdit, QScrollArea, QButtonGroup, QProgressBar, QFileDialog,
)

from app_style import (
    C_PANEL, C_PANEL_2, C_BORDER, C_TEXT, C_MUTED, C_ACCENT, C_ACCENT_DIM,
    C_OK, C_WARN, C_BAD, C_INFO, FONT_FAMILY, FONT_FAMILY_MONO,
)
import room_net as rn
import net_ui

# ============================ 基础常量 ============================

APP_NAME = "射击启动器"
APP_VERSION = "1.2.0"

FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent

# 数字 / 英文窄体（与游戏内同一套字体）
FONT_DIR = BASE_DIR / "fonts"
FONT_NUM = "Rajdhani"
_fonts_loaded = False


def _load_app_fonts():
    global _fonts_loaded
    if _fonts_loaded:
        return
    for font_name in ("Rajdhani-Bold.ttf", "Rajdhani-SemiBold.ttf",
                      "BarlowCondensed-SemiBold.ttf"):
        font_path = FONT_DIR / font_name
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
    _fonts_loaded = True

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ShootingLauncher"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "game_path": "",
    "python_path": "",
    "last_good_python": "",
    "update_url": "",
    "notice_url": "",
    "window_x": None,
    "window_y": None,
    "nickname": "",
    "last_mode": "training",
    "game_source_ref": "",
}

DEFAULT_GAME_SETTINGS = {
    "window_width": 1600,
    "window_height": 900,
    "fullscreen": False,
    "sensitivity": 40.0,
    "volume": 1.0,
}

# ============================ 游戏文件来源（GitHub） ============================
# 客户端只带启动器本体，游戏本体（射击.py / 模块 / 资源）在首次运行或文件缺失时
# 由启动器从公开仓库 OStarsO/ursina-shooter 下载补齐到玩家自己选择的目标目录。

GAME_REPO_OWNER = "OStarsO"
GAME_REPO_NAME = "ursina-shooter"
GAME_REPO_REF = "main"
GAME_ENTRY_NAME = "射击.py"

GAME_USER_AGENT = (f"ShooterLauncher/{APP_VERSION} "
                   f"(+https://github.com/{GAME_REPO_OWNER}/{GAME_REPO_NAME})")
GAME_ARCHIVE_URL = "https://api.github.com/repos/{owner}/{repo}/zipball/{ref}"
# 第二条整包通道：codeload 不走 API 限额
GAME_ARCHIVE_FALLBACK_URL = "https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"
GAME_TREE_URL = "https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
GAME_CONTENT_URL = "https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"

# 需要落地的目录（游戏运行时读取）
GAME_PAYLOAD_DIRS = ("assets/", "fonts/", "maps/", "sfx/", "characters/", "weapons/")
# 不需要落地的顶层文件（启动器本体、测试、工具、文档、仓库配置）
GAME_SKIP_TOP_FILES = (
    "launcher.py", "requirements.txt", ".gitattributes", ".gitignore",
    "LICENSE", "README.md",
)
GAME_SKIP_TOP_PREFIX = ("tests_", "tools/", "docs/", ".github/", "build_launcher/")
# 包体积校验：至少留出这么多空间
GAME_MIN_FREE_BYTES = 200 * 1024 * 1024
GAME_CHUNK = 64 * 1024
GAME_TIMEOUT = 45
GAME_PART_SUFFIX = ".part"


class GameDownloadError(Exception):
    """下载/落盘失败，message 面向玩家展示"""


def default_game_dir() -> Path:
    """默认建议目标目录（玩家仍可自行选择）"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "ShootingLauncher" / "游戏"


def resolve_source_ref(cfg) -> str:
    ref = str((cfg or {}).get("game_source_ref") or "").strip()
    return ref or GAME_REPO_REF


def is_game_payload(rel_path: str) -> bool:
    """判断仓库内某个文件是否属于游戏运行所需"""
    rel = rel_path.replace("\\", "/").strip("/")
    if not rel:
        return False
    if rel.startswith(GAME_SKIP_TOP_PREFIX):
        return False
    if rel.startswith(GAME_PAYLOAD_DIRS):
        return True
    if "/" in rel:
        return False
    if rel in GAME_SKIP_TOP_FILES:
        return False
    return rel.endswith(".py")


def _safe_join(root: Path, rel_path: str) -> Path:
    """防止解包穿越（../ 或绝对路径）"""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise GameDownloadError(f"压缩包内出现异常路径：{rel_path}")
    return root.joinpath(*parts)


def _github_token() -> str:
    """可选：环境变量里带令牌时提高 API 额度（不写入配置、不打印）"""
    return (os.environ.get("SHOOTER_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()


def _open_url(url: str, accept: str = "*/*", timeout: int = GAME_TIMEOUT):
    headers = {
        "User-Agent": GAME_USER_AGENT,
        "Accept": accept,
        "Cache-Control": "no-cache",
    }
    token = _github_token()
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def _describe_network_error(exc: BaseException, url: str) -> str:
    """把网络异常翻译成玩家能看懂的提示"""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return (f"下载源返回 404：仓库 {GAME_REPO_OWNER}/{GAME_REPO_NAME} 或分支不存在，"
                    f"请检查网络或稍后重试（{url}）")
        if exc.code in (403, 429):
            return "下载源拒绝访问（%d）：GitHub 接口访问过于频繁，请等待几分钟后重试" % exc.code
        if 500 <= exc.code < 600:
            return f"GitHub 服务暂时不可用（{exc.code}），请稍后重试"
        return f"下载请求失败（HTTP {exc.code} {exc.reason}）"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        return f"网络连接失败：{reason}。请检查网络、防火墙或代理设置后重试"
    if isinstance(exc, (TimeoutError, OSError)) and "timed out" in str(exc).lower():
        return "下载超时：GitHub 响应过慢，请检查网络后重试"
    if isinstance(exc, (socket.timeout, http.client.HTTPException)):
        return f"下载中断（{type(exc).__name__}），请重试"
    return f"{type(exc).__name__}: {exc}"


def _read_remote_bytes(url, accept="*/*", on_chunk=None, on_open=None,
                       attempts=3, label=""):
    """带重试的整段下载，返回 bytes；失败抛 GameDownloadError"""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            with _open_url(url, accept=accept) as resp:
                if on_open:
                    on_open(resp)
                buf = io.BytesIO()
                while True:
                    chunk = resp.read(GAME_CHUNK)
                    if not chunk:
                        break
                    buf.write(chunk)
                    if on_chunk:
                        on_chunk(len(chunk))
                data = buf.getvalue()
            if not data:
                raise GameDownloadError(f"下载内容为空：{label or url}")
            return data
        except GameDownloadError:
            raise
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise GameDownloadError(_describe_network_error(exc, url)) from exc
            last = exc
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as exc:
            last = exc
        if attempt < attempts:
            time.sleep(1.0 * attempt)
            continue
    raise GameDownloadError(_describe_network_error(last, url))


def validate_game_dir(raw_text: str, need_bytes: int = GAME_MIN_FREE_BYTES):
    """校验玩家选择的目录，返回 (Path, 错误提示)"""
    text = (raw_text or "").strip().strip('"').strip("'")
    if not text:
        return None, "还没有选择游戏文件路径，请先点“浏览…”选择一个文件夹。"
    try:
        path = Path(os.path.expandvars(text)).expanduser()
    except (OSError, ValueError) as exc:
        return None, f"路径无效：{exc}"
    if path.exists() and not path.is_dir():
        return None, f"这个路径是一个文件，请选择文件夹：{path}"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"无法创建目录 {path}：{exc.strerror or exc}"
    probe = path / ".launcher_write_test"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError:
        return None, f"目标目录没有写入权限，请换一个位置或改用管理员权限：{path}"
    try:
        free = shutil.disk_usage(str(path)).free
    except OSError:
        free = need_bytes
    if free < need_bytes:
        return None, (f"磁盘空间不足：{path} 所在磁盘剩余 {free / 1048576:.0f} MB，"
                      f"至少需要 {need_bytes / 1048576:.0f} MB。")
    # 目标目录不能是启动器自身所在目录的子路径以外的怪路径，这里只做规范化
    try:
        return path.resolve(), ""
    except OSError as exc:
        return None, f"路径无法解析：{exc}"


def download_game_package(target_dir, ref=None, cfg=None, on_progress=None, on_log=None,
                          url=None):
    """下载仓库整包（zipball/zip）并落地游戏文件。返回 {"files": n, "bytes": n}"""
    target = Path(target_dir)
    ref = ref or resolve_source_ref(cfg)
    url = url or GAME_ARCHIVE_URL.format(owner=GAME_REPO_OWNER, repo=GAME_REPO_NAME, ref=ref)
    log = on_log or (lambda _m: None)
    log(f"下载游戏包：{url}")

    total = 0
    done = 0

    def _on_open(resp):
        nonlocal total
        length = resp.headers.get("Content-Length")
        total = int(length) if length and length.isdigit() else 0

    def _on_chunk(size):
        nonlocal done
        done += size
        if on_progress:
            on_progress(done, total, f"下载游戏包 {done / 1048576:.1f} MB")

    raw = _read_remote_bytes(url, accept="application/zip", on_chunk=_on_chunk,
                             on_open=_on_open, label="游戏包")
    if len(raw) < 1024:
        raise GameDownloadError("下载到的游戏包为空，请重试")
    if raw[:2] != b"PK":
        snippet = raw[:200].decode("utf-8", "replace").strip().replace("\n", " ")
        raise GameDownloadError(f"下载源返回的不是游戏包（可能被接口限流）：{snippet[:150]}")
    buf = io.BytesIO(raw)
    files, written = 0, 0
    try:
        with zipfile.ZipFile(buf) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            picked = []
            for m in members:
                name = m.filename.replace("\\", "/")
                parts = name.split("/", 1)
                rel = parts[1] if len(parts) == 2 else ""
                if rel and is_game_payload(rel):
                    picked.append((m, rel))
            if not picked:
                raise GameDownloadError("游戏包里没有找到游戏文件，请稍后重试")
            all_bytes = sum(m.file_size for m, _ in picked)
            for index, (member, rel) in enumerate(picked, 1):
                dest = _safe_join(target, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_name(dest.name + GAME_PART_SUFFIX)
                try:
                    with zf.open(member) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out, GAME_CHUNK)
                    os.replace(tmp, dest)
                except OSError as exc:
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except OSError:
                        pass
                    raise GameDownloadError(
                        f"写入游戏文件失败：{dest}（{exc.strerror or exc}）。"
                        f"请确认该目录没有被占用，或换一个位置。"
                    ) from exc
                files += 1
                written += member.file_size
                if on_progress:
                    on_progress(written, all_bytes, f"写入 {rel}")
    except zipfile.BadZipFile as exc:
        raise GameDownloadError("游戏包解压失败（文件不完整），请重试") from exc

    if not (target / GAME_ENTRY_NAME).is_file():
        raise GameDownloadError(f"补齐后仍找不到 {GAME_ENTRY_NAME}，请重试或手动指定已有游戏目录")
    log(f"游戏文件落地完成：{files} 个文件，{written / 1048576:.1f} MB")
    return {"files": files, "bytes": written}


def download_game_files(target_dir, ref=None, cfg=None, on_progress=None, on_log=None):
    """逐个文件走 Contents API 下载（备用通道，zipball 不可用时使用）"""
    target = Path(target_dir)
    ref = ref or resolve_source_ref(cfg)
    log = on_log or (lambda _m: None)
    tree_url = GAME_TREE_URL.format(owner=GAME_REPO_OWNER, repo=GAME_REPO_NAME, ref=ref)
    log(f"读取文件清单：{tree_url}")
    try:
        raw_tree = _read_remote_bytes(tree_url, accept="application/vnd.github+json",
                                      label="文件清单")
        data = json.loads(raw_tree.decode("utf-8"))
    except GameDownloadError:
        raise
    except ValueError as exc:
        raise GameDownloadError(f"文件清单解析失败：{exc}") from exc

    entries = [e for e in data.get("tree", [])
               if e.get("type") == "blob" and is_game_payload(e.get("path", ""))]
    if not entries:
        raise GameDownloadError("仓库文件清单为空，请稍后重试")
    total = sum(int(e.get("size") or 0) for e in entries)
    done_total, files = 0, 0
    for entry in entries:
        rel = entry["path"]
        url = GAME_CONTENT_URL.format(owner=GAME_REPO_OWNER, repo=GAME_REPO_NAME,
                                      path=urllib.parse.quote(rel), ref=ref)
        dest = _safe_join(target, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + GAME_PART_SUFFIX)
        try:
            payload = _read_remote_bytes(url, accept="application/vnd.github.raw",
                                         label=rel)
        except GameDownloadError as exc:
            raise GameDownloadError(f"下载 {rel} 失败：{exc}") from exc
        try:
            with open(tmp, "wb") as out:
                out.write(payload)
            os.replace(tmp, dest)
        except OSError as exc:
            raise GameDownloadError(
                f"写入游戏文件失败：{dest}（{exc.strerror or exc}）") from exc
        files += 1
        done_total += len(payload)
        if on_progress:
            on_progress(done_total, max(total, done_total), f"下载 {rel}")

    if not (target / GAME_ENTRY_NAME).is_file():
        raise GameDownloadError(f"补齐后仍找不到 {GAME_ENTRY_NAME}，请重试")
    log(f"游戏文件落地完成：{files} 个文件，{done_total / 1048576:.1f} MB")
    return {"files": files, "bytes": done_total}


def fetch_game_files(target_dir, ref=None, cfg=None, on_progress=None, on_log=None):
    """整包（API）→ 整包（codeload）→ 逐文件，依次尝试；全部失败抛 GameDownloadError"""
    log = on_log or (lambda _m: None)
    ref = ref or resolve_source_ref(cfg)
    channels = (
        # codeload 不走 API 限额，优先使用
        ("codeload zip", GAME_ARCHIVE_FALLBACK_URL.format(owner=GAME_REPO_OWNER,
                                                          repo=GAME_REPO_NAME, ref=ref)),
        ("api zipball", GAME_ARCHIVE_URL.format(owner=GAME_REPO_OWNER,
                                                repo=GAME_REPO_NAME, ref=ref)),
    )
    errors = []
    for name, url in channels:
        try:
            return download_game_package(target_dir, ref=ref, cfg=cfg, url=url,
                                         on_progress=on_progress, on_log=log)
        except GameDownloadError as exc:
            errors.append(f"{name}：{exc}")
            log(f"{name} 失败：{exc}")
            log("换下一个下载通道…")
    log("整包通道都失败，改用逐文件下载…")
    try:
        return download_game_files(target_dir, ref=ref, cfg=cfg,
                                   on_progress=on_progress, on_log=log)
    except GameDownloadError as exc:
        errors.append(f"逐文件：{exc}")
    detail = "；".join(errors)
    raise GameDownloadError(f"游戏文件下载失败：{detail}")


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
    """按优先级查找 射击.py（cfg["game_path"] 可以是目录，也可以是文件）"""
    candidates = []
    raw = str(cfg.get("game_path") or "").strip()
    if raw:
        try:
            p = Path(os.path.expandvars(raw)).expanduser()
            if p.is_dir():
                p = p / GAME_ENTRY_NAME
            candidates.append(p)
        except (OSError, ValueError):
            pass
    candidates += [
        BASE_DIR / GAME_ENTRY_NAME,
        BASE_DIR.parent / GAME_ENTRY_NAME,
        default_game_dir() / GAME_ENTRY_NAME,
        Path(r"D:/PyCharmMiscProject/射击/射击.py"),
    ]
    for path in candidates:
        try:
            if path and path.is_file():
                return path.resolve()
        except OSError:
            continue
    if candidates and isinstance(candidates[0], Path):
        return candidates[0]
    return BASE_DIR / GAME_ENTRY_NAME


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


class GamePackageThread(QThread):
    """从 GitHub 下载游戏文件到玩家选择的目录"""
    progress = Signal(int, int, str)     # 已完成字节 / 总字节 / 文案
    log = Signal(str)
    done = Signal(bool, str, dict)       # 成功? / 提示 / 结果

    def __init__(self, target_dir, ref=None, cfg=None, parent=None):
        super().__init__(parent)
        self.target_dir = Path(target_dir)
        self.ref = ref
        self.cfg = cfg or {}
        self.cancelled = False

    def run(self):
        self.log.emit(f"目标目录：{self.target_dir}")
        try:
            info = fetch_game_files(
                self.target_dir, ref=self.ref, cfg=self.cfg,
                on_progress=lambda d, t, m: self.progress.emit(d, t, m),
                on_log=lambda m: self.log.emit(m),
            )
        except GameDownloadError as exc:
            self.done.emit(False, str(exc), {})
            return
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"补齐游戏文件时发生未知错误：{type(exc).__name__}: {exc}", {})
            return
        self.done.emit(True, str(self.target_dir), info)


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
        bar = QFrame()
        bar.setFixedSize(3, 14)
        bar.setStyleSheet(f"background:{C_ACCENT}; border-radius:2px;")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        head.addWidget(bar)
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.head = head
        self.body.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(6)
        self.body.addLayout(self.content)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(6, 10, 18, 70))
        self.setGraphicsEffect(shadow)


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




class LogBox(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setObjectName("LogBox")
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFont(QFont(FONT_FAMILY_MONO, 9))

    def append_line(self, text):
        self.append(text.replace("\r", ""))
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


# ============================ 游戏文件补齐对话框 ============================

class GameSetupDialog(QDialog):
    """让玩家先选目标路径，再从 GitHub 下载补齐游戏文件"""

    def __init__(self, parent=None, cfg=None, reason="", start_dir=None):
        super().__init__(parent)
        self.cfg = dict(cfg or {})
        self.chosen_dir = None
        self.thread = None
        self.setWindowTitle(f"{APP_NAME} · 补齐游戏文件")
        self.setMinimumWidth(660)
        self.setStyleSheet(f"""
            QDialog {{ background: {C_PANEL}; }}
            QLabel {{ color: {C_TEXT}; }}
            QLabel#Title {{ font-size: 16px; font-weight: 700; letter-spacing: 1px; }}
            QLabel#Hint {{ color: {C_MUTED}; font-size: 11px; }}
            QLineEdit {{
                background: {C_PANEL_2}; border: 1px solid {C_BORDER};
                border-radius: 8px; padding: 7px 10px; color: {C_TEXT};
            }}
            QPushButton#Ghost {{
                background: rgba(255, 255, 255, 0.03); border: 1px solid #2A3648;
                border-radius: 8px; padding: 6px 14px; color: #B9C6D9;
            }}
            QPushButton#Ghost:hover {{ border-color: {C_ACCENT}; color: {C_TEXT}; }}
            QPushButton#Primary {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 {C_ACCENT}, stop:1 #FF8B57);
                border: none; border-radius: 10px; padding: 9px 22px;
                color: #1A0D06; font-size: 13px; font-weight: 800; letter-spacing: 1px;
            }}
            QPushButton#Primary:disabled {{ background: #2A3342; color: {C_MUTED}; }}
            QProgressBar {{
                background: {C_PANEL_2}; border: 1px solid {C_BORDER};
                border-radius: 5px; height: 8px; text-align: center; color: {C_MUTED};
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 {C_ACCENT}, stop:1 #FF8B57);
                border-radius: 4px;
            }}
            QTextEdit#LogBox {{
                background: {C_PANEL_2}; border: 1px solid {C_BORDER};
                border-radius: 8px; color: #9FB0C8; padding: 8px;
            }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: #33425A; border-radius: 4px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._build_ui(reason, start_dir)

    # ---------- 界面 ----------
    def _build_ui(self, reason, start_dir):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        title = QLabel("选择游戏文件保存位置")
        title.setObjectName("Title")
        lay.addWidget(title)

        hint = QLabel(reason or (
            "当前机器上还没有游戏文件。客户端只自带启动器本体，"
            f"游戏文件会从 GitHub（{GAME_REPO_OWNER}/{GAME_REPO_NAME}）下载补齐。"
        ))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_path = QLineEdit(str(start_dir or default_game_dir()))
        self.edit_path.setPlaceholderText("例如 D:\\Games\\射击")
        self.edit_path.editingFinished.connect(self._revalidate)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.setObjectName("Ghost")
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.clicked.connect(self._browse)
        row.addWidget(self.edit_path, 1)
        row.addWidget(self.btn_browse)
        lay.addLayout(row)

        self.lbl_tip = QLabel("")
        self.lbl_tip.setObjectName("Hint")
        self.lbl_tip.setWordWrap(True)
        lay.addWidget(self.lbl_tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        self.log_box = LogBox()
        self.log_box.setMinimumHeight(126)
        lay.addWidget(self.log_box, 1)

        self.lbl_license = QLabel(
            "游戏文件以 PolyForm Noncommercial 1.0.0 授权发布，仅限非商业用途。"
        )
        self.lbl_license.setObjectName("Hint")
        lay.addWidget(self.lbl_license)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self.btn_later = QPushButton("稍后再说")
        self.btn_later.setObjectName("Ghost")
        self.btn_later.setCursor(Qt.PointingHandCursor)
        self.btn_later.clicked.connect(self.reject)
        self.btn_start = QPushButton("开始下载并补齐")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self._start)
        btn_row.addWidget(self.btn_later)
        btn_row.addWidget(self.btn_start)
        lay.addLayout(btn_row)

        self._revalidate()

    def _tip(self, text, color=C_MUTED):
        self.lbl_tip.setText(text)
        self.lbl_tip.setStyleSheet(f"color:{color}; font-size:11px;")

    def _revalidate(self):
        if self.thread and self.thread.isRunning():
            return
        path, err = validate_game_dir(self.edit_path.text())
        if err:
            self._tip(err, C_WARN)
            self.btn_start.setEnabled(False)
        else:
            exists = (path / GAME_ENTRY_NAME).is_file()
            self._tip(("该目录已有游戏文件：下载将刷新为仓库最新版本。" if exists
                       else f"将把游戏文件写入：{path}"), C_INFO if exists else C_MUTED)
            self.btn_start.setEnabled(True)

    def _browse(self):
        start = self.edit_path.text().strip() or str(default_game_dir())
        chosen = QFileDialog.getExistingDirectory(self, "选择游戏文件保存位置", start)
        if chosen:
            self.edit_path.setText(chosen)
            self._revalidate()

    # ---------- 下载 ----------
    def _start(self):
        if self.thread and self.thread.isRunning():
            return
        path, err = validate_game_dir(self.edit_path.text())
        if err:
            self._tip(err, C_BAD)
            QMessageBox.warning(self, "路径不可用", err)
            return
        if (path / GAME_ENTRY_NAME).is_file():
            answer = QMessageBox.question(
                self, "覆盖确认",
                f"该目录已存在游戏文件：\n{path}\n\n继续会从 GitHub 重新下载并覆盖同名文件，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return
        self.edit_path.setText(str(path))
        self.chosen_dir = path
        self.log_box.clear()
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.edit_path.setEnabled(False)
        self.btn_later.setEnabled(False)
        self._tip("正在连接 GitHub…", C_INFO)
        self.thread = GamePackageThread(path, ref=resolve_source_ref(self.cfg),
                                       cfg=self.cfg, parent=self)
        self.thread.progress.connect(self._on_progress)
        self.thread.log.connect(self.log_box.append_line)
        self.thread.done.connect(self._on_done)
        self.thread.start()

    def _on_progress(self, done, total, message):
        if total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(max(0, min(1000, int(done * 1000 / total))))
            self._tip(f"{message}（{done / 1048576:.1f} / {total / 1048576:.1f} MB）", C_INFO)
        else:
            self.bar.setRange(0, 0)
            self.bar.setValue(0)
            self._tip(f"{message}（{done / 1048576:.1f} MB）", C_INFO)

    def _on_done(self, ok, message, info):
        self.btn_browse.setEnabled(True)
        self.edit_path.setEnabled(True)
        self.btn_later.setEnabled(True)
        self.btn_start.setEnabled(True)
        self.bar.setRange(0, 1000)
        if ok:
            self.bar.setValue(1000)
            files = info.get("files", 0) if isinstance(info, dict) else 0
            size = (info.get("bytes", 0) / 1048576) if isinstance(info, dict) else 0.0
            self._tip(f"补齐完成：{files} 个文件，{size:.1f} MB。", C_OK)
            self.log_box.append_line("补齐完成，可以开始游戏了。")
            QTimer.singleShot(600, self.accept)
            return
        self.bar.setValue(0)
        self._tip(f"补齐失败：{message}", C_BAD)
        self.log_box.append_line(f"补齐失败：{message}")
        box = QMessageBox(self)
        box.setWindowTitle("下载失败")
        box.setIcon(QMessageBox.Warning)
        box.setText("游戏文件下载失败。")
        box.setInformativeText(f"{message}\n\n可以检查网络后点“开始下载并补齐”重试，"
                              f"或点“浏览…”换一个可写的目录。")
        box.exec()

    def closeEvent(self, event):
        if self.thread and self.thread.isRunning():
            event.ignore()
            self._tip("正在下载游戏文件，请等待完成后再关闭。", C_WARN)
            return
        super().closeEvent(event)

    def reject(self):
        if self.thread and self.thread.isRunning():
            self._tip("正在下载游戏文件，请等待完成后再关闭。", C_WARN)
            return
        super().reject()


# ============================ 主窗口 ============================

class LauncherWindow(QWidget):
    def __init__(self, nickname="玩家"):
        super().__init__()
        _load_app_fonts()
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
        self._refresh_game_row()
        QTimer.singleShot(180, self.start_env_check)
        # 缺少游戏文件时，先让玩家选择目标路径再下载补齐
        QTimer.singleShot(900, self._prompt_missing_game)

    # ---------- 样式 ----------
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QWidget {{
                color: {C_TEXT};
                font-family: "{FONT_FAMILY}";
                font-size: 12px;
            }}
            QFrame#Card {{
                background: rgba(255, 255, 255, 0.055);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 18px;
            }}
            QLabel#CardTitle {{
                color: #B9C6D9;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 1.5px;
            }}
            QLabel#Hint {{ color: {C_MUTED}; font-size: 11px; }}
            QLabel#BigScore {{
                color: {C_ACCENT};
                font-family: "{FONT_NUM}";
                font-size: 38px;
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
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid #2A3648;
                border-radius: 8px;
                padding: 6px 12px;
                color: #B9C6D9;
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
                border-radius: 8px;
                color: #9FB0C8;
                padding: 8px;
            }}
            QLineEdit {{
                background: {C_PANEL_2};
                border: 1px solid {C_BORDER};
                border-radius: 8px;
                padding: 7px 10px;
                color: {C_TEXT};
                selection-background-color: {C_ACCENT_DIM};
            }}
            QLineEdit:focus {{ border-color: {C_ACCENT}; }}
            QPushButton#NavBtn {{
                background: transparent;
                border: none;
                border-bottom: 2px solid transparent;
                border-radius: 0;
                padding: 8px 14px;
                color: {C_MUTED};
                font-size: 13px;
                letter-spacing: 1px;
            }}
            QPushButton#NavBtn:hover {{ color: {C_TEXT}; }}
            QPushButton#NavBtn:checked {{
                color: {C_ACCENT};
                border-bottom-color: {C_ACCENT};
                font-weight: 600;
            }}
        """)

    # ---------- 界面 ----------
    def _build_ui(self):
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        shell.addLayout(right)

        # 顶部栏
        top = QHBoxLayout()
        top.setContentsMargins(26, 14, 14, 6)

        brand = QWidget()
        brand_lay = QHBoxLayout(brand)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(10)
        mark = QFrame()
        mark.setFixedSize(28, 28)
        mark.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #FF7A45, stop:1 #FF9E6B); border-radius:9px;"
        )
        bt = QVBoxLayout()
        bt.setSpacing(2)
        bt_t = QLabel("射击")
        bt_t.setStyleSheet("color:#EDF2FA; font-size:15px; font-weight:700; letter-spacing:2px;")
        bt_s = QLabel(f"SHOOTER · v{APP_VERSION}")
        bt_s.setStyleSheet(
            f"color:{C_MUTED}; font-family:'{FONT_NUM}'; font-size:10px; letter-spacing:2px;"
        )
        bt.addWidget(bt_t)
        bt.addWidget(bt_s)
        brand_lay.addWidget(mark)
        brand_lay.addLayout(bt)
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

        # 顶部导航菜单：公告 / 设置 / 控制台 / 我的
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav = QHBoxLayout()
        nav.setContentsMargins(24, 2, 26, 4)
        nav.setSpacing(4)
        self.nav_buttons = {}
        for key, title in (("notice", "公告"), ("settings", "设置"),
                           ("console", "控制台"), ("profile", "我的")):
            b = QPushButton(title)
            b.setObjectName("NavBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._switch_page(k))
            self.nav_group.addButton(b)
            nav.addWidget(b)
            self.nav_buttons[key] = b
        nav.addStretch(1)
        right.addLayout(nav)

        # 页面栈
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_notice_page())
        self.stack.addWidget(self._build_settings_page())
        self.stack.addWidget(self._build_console_page())
        self.stack.addWidget(self._build_profile_page())
        self._switch_page("settings")

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

        self.btn_log = QPushButton("控制台")
        self.btn_log.setObjectName("Ghost")
        self.btn_log.setCursor(Qt.PointingHandCursor)
        self.btn_log.clicked.connect(lambda: self._switch_page("console"))
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

    # ---------- 页面框架 ----------
    PAGE_KEYS = ("notice", "settings", "console", "profile")

    def _wrap_page(self, content_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent; border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}"
        )
        scroll.setWidget(content_widget)
        return scroll

    def _switch_page(self, key):
        if key not in self.PAGE_KEYS:
            return
        self.stack.setCurrentIndex(self.PAGE_KEYS.index(key))
        btn = self.nav_buttons.get(key)
        if btn:
            btn.setChecked(True)

    # ---------- 公告页 ----------
    DEFAULT_NOTICES = [
        ("2026-11-16", "v1.2.0 客户端更新",
         "新增「选择路径 + 从 GitHub 下载补齐游戏文件」：客户端只自带启动器本体，"
         "首次启动会先让你选择游戏文件保存位置，再从 GitHub（OStarsO/ursina-shooter）"
         "下载补齐；路径无效、磁盘不足、下载失败都会给出明确提示，可随时在"
         "「设置 → 选择路径 / 下载游戏文件」重新补齐或更换目录。"),
        ("2026-11-12", "v1.1.0 客户端更新",
         "主界面顶部新增「公告 / 设置 / 控制台 / 我的」导航；环境自检、游戏设置、战绩与联机入口已按页面归类。"),
        ("2026-11-12", "玩法提示",
         "WASD 移动，空格跳跃，左键射击，R 换弹，按住 Tab 查看计分板，ESC 打开暂停菜单。"),
        ("2026-11-12", "联机说明",
         "同一局域网内可建房或加入房间（TCP 25250）；进入对局后的位置 / 命中 / 比分同步仍在开发中。"),
    ]

    def _build_notice_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 8, 26, 6)
        lay.setSpacing(12)
        card = Card("公告")
        self.notice_layout = QVBoxLayout()
        self.notice_layout.setSpacing(12)
        card.content.addLayout(self.notice_layout)
        lay.addWidget(card)
        lay.addStretch(1)
        for date, title, body in self.DEFAULT_NOTICES:
            self._add_notice(date, title, body)
        # 预留：cfg["notice_url"] 配置后可在此拉取远程公告并追加
        return self._wrap_page(page)

    def _add_notice(self, date, title, body):
        box = QVBoxLayout()
        box.setSpacing(3)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(f"color:{C_TEXT}; font-size:13px; font-weight:600;")
        d = QLabel(date)
        d.setObjectName("Hint")
        head.addWidget(t)
        head.addStretch(1)
        head.addWidget(d)
        b = QLabel(body)
        b.setObjectName("Hint")
        b.setWordWrap(True)
        box.addLayout(head)
        box.addWidget(b)
        self.notice_layout.addLayout(box)

    # ---------- 设置页 ----------
    def _build_settings_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 8, 26, 6)
        lay.setSpacing(12)

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

        self.row_game = StatusRow("游戏文件")
        self.btn_pick_game = QPushButton("选择路径")
        self.btn_pick_game.setObjectName("Ghost")
        self.btn_pick_game.setCursor(Qt.PointingHandCursor)
        self.btn_pick_game.clicked.connect(self.pick_game_path)
        self.btn_fetch_game = QPushButton("下载游戏文件")
        self.btn_fetch_game.setObjectName("Ghost")
        self.btn_fetch_game.setCursor(Qt.PointingHandCursor)
        self.btn_fetch_game.clicked.connect(self.open_game_setup)
        game_btn_row = QHBoxLayout()
        game_btn_row.setContentsMargins(0, 0, 0, 6)
        game_btn_row.setSpacing(8)
        game_btn_row.addWidget(self.btn_pick_game)
        game_btn_row.addWidget(self.btn_fetch_game)
        game_btn_row.addStretch(1)

        self.row_python = StatusRow("解释器")
        self.row_engine = StatusRow("引擎")
        self.row_font = StatusRow("中文字体")
        self.row_audio = StatusRow("音效")
        env_card.content.addWidget(self.row_game)
        env_card.content.addLayout(game_btn_row)
        for r in (self.row_python, self.row_engine, self.row_font, self.row_audio):
            env_card.content.addWidget(r)
        lay.addWidget(env_card)

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
        self.lbl_sens.setStyleSheet(f"color:#D7E1EE; font-family:'{FONT_NUM}'; font-size:14px; font-weight:600;")
        grid.addWidget(self.lbl_sens, 1, 2)

        grid.addWidget(self._label("音量"), 2, 0)
        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.valueChanged.connect(self._on_vol_changed)
        self.slider_vol.sliderReleased.connect(self.save_settings_from_ui)
        grid.addWidget(self.slider_vol, 2, 1)
        self.lbl_vol = QLabel("100%")
        self.lbl_vol.setFixedWidth(44)
        self.lbl_vol.setStyleSheet(f"color:#D7E1EE; font-family:'{FONT_NUM}'; font-size:14px; font-weight:600;")
        grid.addWidget(self.lbl_vol, 2, 2)

        grid.setColumnStretch(1, 1)
        set_card.content.addLayout(grid)
        hint = QLabel("设置会写入 settings.json，下次启动游戏时生效")
        hint.setObjectName("Hint")
        set_card.content.addWidget(hint)
        lay.addWidget(set_card)
        lay.addStretch(1)
        return self._wrap_page(page)

    # ---------- 控制台页 ----------
    def _build_console_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 8, 26, 6)
        lay.setSpacing(12)

        console_card = Card("控制台")
        self.log_box = LogBox()
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        console_card.content.addWidget(self.log_box, 1)

        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(8)
        self.console_input = QLineEdit()
        self.console_input.setPlaceholderText("输入命令，help 查看可用命令")
        self.console_input.returnPressed.connect(self._run_local_command)
        btn_run = QPushButton("执行")
        btn_run.setObjectName("Ghost")
        btn_run.setCursor(Qt.PointingHandCursor)
        btn_run.clicked.connect(self._run_local_command)
        cmd_row.addWidget(self.console_input, 1)
        cmd_row.addWidget(btn_run)
        console_card.content.addLayout(cmd_row)
        lay.addWidget(console_card, 1)

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
        quick.addStretch(1)
        lay.addLayout(quick)
        return self._wrap_page(page)

    def _run_local_command(self):
        text = self.console_input.text().strip()
        if not text:
            return
        self.console_input.clear()
        self.log_box.append_line(f"> {text}")
        cmd = text.partition(" ")[0].lower()
        if cmd == "help":
            self.log_box.append_line("可用命令：help　status（环境摘要）　clear（清空控制台）")
        elif cmd == "status":
            py = self.env.get("python_path") or self.cfg.get("last_good_python") or "未检测到"
            self.log_box.append_line(f"环境：{'就绪' if self.env.get('ok') else '未就绪'}")
            self.log_box.append_line(f"解释器：{py}")
            self.log_box.append_line(f"游戏路径：{self.game_path}")
        elif cmd == "clear":
            self.log_box.clear()
        else:
            self.log_box.append_line(f"未知命令：{cmd}（输入 help 查看）")

    # ---------- 我的页 ----------
    def _build_profile_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 8, 26, 6)
        lay.setSpacing(12)

        # 账号卡
        account_card = Card("账号")
        acc_row = QHBoxLayout()
        self.avatar = QLabel((self.nickname[:1] or "?").upper())
        self.avatar.setFixedSize(46, 46)
        self.avatar.setAlignment(Qt.AlignCenter)
        self.avatar.setStyleSheet(
            f"background:{C_ACCENT_DIM}; color:{C_TEXT}; border-radius:23px;"
            f"font-size:18px; font-weight:700;"
        )
        acc_col = QVBoxLayout()
        acc_col.setSpacing(2)
        self.lbl_profile_nick = QLabel(self.nickname)
        self.lbl_profile_nick.setStyleSheet(f"color:{C_TEXT}; font-size:15px; font-weight:600;")
        cap = QLabel("游客登录 · 战绩保存在本机")
        cap.setObjectName("Hint")
        acc_col.addWidget(self.lbl_profile_nick)
        acc_col.addWidget(cap)
        acc_row.addWidget(self.avatar)
        acc_row.addLayout(acc_col)
        acc_row.addStretch(1)
        self.btn_profile_switch = QPushButton("切换账号")
        self.btn_profile_switch.setObjectName("Ghost")
        self.btn_profile_switch.setCursor(Qt.PointingHandCursor)
        self.btn_profile_switch.clicked.connect(self.switch_account)
        acc_row.addWidget(self.btn_profile_switch)
        account_card.content.addLayout(acc_row)
        lay.addWidget(account_card)

        # 战绩卡
        score_card = Card("战绩")
        score_row = QHBoxLayout()
        score_row.setSpacing(6)
        score_col = QVBoxLayout()
        score_col.setSpacing(0)
        self.lbl_best = QLabel("0")
        self.lbl_best.setObjectName("BigScore")
        score_col.addWidget(self.lbl_best)
        cap2 = QLabel("历史最高分")
        cap2.setObjectName("Hint")
        score_col.addWidget(cap2)
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
        lay.addWidget(score_card)

        # 客户端卡
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
        lay.addWidget(about_card)
        lay.addStretch(1)
        return self._wrap_page(page)


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
        grad.setColorAt(0, QColor("#0C1017"))
        grad.setColorAt(0.55, QColor("#0A0D13"))
        grad.setColorAt(1, QColor("#0B0F16"))
        p.fillPath(path, grad)

        p.save()
        p.setClipPath(path)

        def _glow(cx, cy, r, rgb, a0):
            c = QColor(rgb[0], rgb[1], rgb[2])
            g = QRadialGradient(cx, cy, r)
            g.setColorAt(0, QColor(c.red(), c.green(), c.blue(), a0))
            g.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        _glow(-80, -80, 300, (64, 92, 168), 86)
        _glow(self.width() + 70, self.height() + 70, 280, (31, 110, 128), 76)
        _glow(self.width() - 170, 120, 240, (255, 107, 53), 40)

        p.setPen(QPen(QColor(255, 255, 255, 7), 1))
        step = 30
        for x in range(0, self.width(), step):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), step):
            p.drawLine(0, y, self.width(), y)
        p.restore()

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

    # ---------- 游戏文件补齐 ----------
    def _refresh_game_row(self):
        if not hasattr(self, "row_game"):
            return
        path = self.game_path
        if path.is_file():
            try:
                size_kb = path.stat().st_size / 1024
            except OSError:
                size_kb = 0
            self.row_game.set_state("ok", f"{path.name} · {size_kb:.0f} KB")
            if hasattr(self, "lbl_path"):
                self.lbl_path.setText(str(path))
        else:
            self.row_game.set_state("warn", "缺失 · 需从 GitHub 下载补齐")
            if hasattr(self, "lbl_path"):
                self.lbl_path.setText(f"{self.game_dir}（游戏文件缺失）")

    def _apply_game_dir(self, target):
        target = Path(target)
        self.game_path = target / GAME_ENTRY_NAME
        self.game_dir = target
        self.cfg["game_path"] = str(target)
        save_config(self.cfg)
        self._refresh_game_row()
        self._refresh_scores()
        self._load_settings_into_ui(read_game_settings(self.game_dir))
        self.flash_status(f"游戏目录：{target}")

    def pick_game_path(self):
        start = str(self.game_dir) if str(self.game_dir) else str(default_game_dir())
        chosen = QFileDialog.getExistingDirectory(self, "选择游戏文件目录", start)
        if not chosen:
            return
        path, err = validate_game_dir(chosen)
        if err:
            QMessageBox.warning(self, "路径不可用", err)
            return
        self._apply_game_dir(path)

    def open_game_setup(self, checked=False, reason=""):
        """打开“选择路径 + 下载补齐”对话框"""
        start = self.game_dir if str(self.game_dir) else default_game_dir()
        dlg = GameSetupDialog(self, cfg=self.cfg, reason=reason, start_dir=start)
        if dlg.exec() == QDialog.Accepted and dlg.chosen_dir:
            self._apply_game_dir(dlg.chosen_dir)
            self.start_env_check()
            self._refresh_game_row()
            return True
        self._refresh_game_row()
        return False

    def ensure_game_files(self, reason=""):
        """游戏文件不存在时先让玩家选路径并下载"""
        if self.game_path.is_file():
            return True
        tip = reason or (
            f"找不到游戏文件：\n{self.game_path}\n\n"
            "请先选择保存位置，客户端会从 GitHub 下载补齐游戏文件。"
        )
        return self.open_game_setup(reason=tip)

    def _prompt_missing_game(self):
        if self.game_path.is_file():
            self._refresh_game_row()
            return
        self._refresh_game_row()
        self.ensure_game_files()

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
            if not self.game_path.is_file():
                self.lbl_status.setText("环境就绪 · 游戏文件缺失，请先下载补齐")
            self._refresh_game_row()
        else:
            self.row_python.set_state("bad", info.get("error", "不可用"))
            self.row_engine.set_state("bad", "未检测到 ursina")
            self.lbl_status.setText("环境异常，请点“修复环境”")
            self.btn_launch.setEnabled(False)
            self.btn_repair.setVisible(True)
            detail = info.get("detail") or []
            self._switch_page("console")
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
        self._switch_page("console")
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
            if hasattr(self, "lbl_profile_nick"):
                self.lbl_profile_nick.setText(self.nickname)
            if hasattr(self, "avatar"):
                self.avatar.setText((self.nickname[:1] or "?").upper())
            self.flash_status(f"已切换为 {self.nickname}")

    def launch_online_game(self, extra_args, tag, on_finished):
        return self.start_game(extra_args=extra_args, tag=tag, on_finished=on_finished)

    def start_game(self, extra_args=None, tag="game", on_finished=None):
        python = self.env.get("python_path") or self.cfg.get("last_good_python")
        if not python:
            QMessageBox.warning(self, "无法启动", "未找到可用的 Python 环境，请先点“修复环境”。")
            return False
        if not self.game_path.is_file() and not self.ensure_game_files():
            return False
        if not self.game_path.is_file():
            QMessageBox.warning(
                self, "无法启动",
                f"仍然找不到游戏文件：\n{self.game_path}\n\n"
                "请点“设置 → 选择路径 / 下载游戏文件”重新补齐。",
            )
            return False

        args = [str(self.game_path)] + list(extra_args or [])
        self._game_finished_cb = on_finished
        self._game_tag = tag

        self._switch_page("console")
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

def run_fetch_game(target, ref=None):
    """命令行补齐游戏文件（无界面，便于自检/排错）"""
    cfg = load_config()
    path, err = validate_game_dir(target)
    if err:
        print(f"[路径不可用] {err}")
        return 2
    print(f"目标目录：{path}")
    try:
        info = fetch_game_files(
            path, ref=ref or resolve_source_ref(cfg), cfg=cfg,
            on_progress=lambda d, t, m: print(f"  {m}"),
            on_log=lambda m: print(m),
        )
    except GameDownloadError as exc:
        print(f"[下载失败] {exc}")
        return 3
    entry = path / GAME_ENTRY_NAME
    print(f"完成：{info['files']} 个文件，{info['bytes'] / 1048576:.1f} MB")
    print(f"{GAME_ENTRY_NAME} 存在：{entry.is_file()}（{entry.stat().st_size if entry.is_file() else 0} B）")
    return 0 if entry.is_file() else 4


def run_selftest():
    cfg = load_config()
    game_path = locate_game(cfg)
    game_dir = game_dir_of(game_path)
    report = {
        "version": APP_VERSION,
        "frozen": FROZEN,
        "game_path": str(game_path),
        "game_exists": game_path.is_file(),
        "game_source": {
            "repo": f"{GAME_REPO_OWNER}/{GAME_REPO_NAME}",
            "ref": resolve_source_ref(cfg),
            "archive_urls": [
                GAME_ARCHIVE_FALLBACK_URL.format(
                    owner=GAME_REPO_OWNER, repo=GAME_REPO_NAME, ref=resolve_source_ref(cfg)),
                GAME_ARCHIVE_URL.format(
                    owner=GAME_REPO_OWNER, repo=GAME_REPO_NAME, ref=resolve_source_ref(cfg)),
            ],
        },
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
    if "--fetch-game" in argv:
        idx = argv.index("--fetch-game")
        target = argv[idx + 1] if len(argv) > idx + 1 else str(default_game_dir())
        ref = None
        if "--ref" in argv:
            ridx = argv.index("--ref")
            if len(argv) > ridx + 1:
                ref = argv[ridx + 1]
        return run_fetch_game(target, ref)
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
