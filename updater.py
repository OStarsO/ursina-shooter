# -*- coding: utf-8 -*-
"""GitHub Releases 自动更新（纯标准库，无 Qt 依赖，可单测）。

能力：
    fetch_latest_release()  查询仓库最新 Release（版本号 / 更新说明 / 资产）
    is_newer()              本地版本 vs 远端版本的语义化比较
    pick_asset()            从资产列表里挑出启动器 exe
    download_asset()        下载资产：直连优先，失败按序回退镜像前缀
    stage_self_update()     生成替换脚本并重启（Windows 下 exe 无法自我覆盖）

镜像策略：GitHub API 走直连（镜像不代理 api.github.com）；Release 资产
（github.com/.../releases/download/...）支持通用加速前缀，直连失败后
依次尝试 ASSET_MIRRORS 中的前缀，全部失败才抛 UpdateError。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_OWNER = "OStarsO"
REPO_NAME = "ursina-shooter"
LATEST_API = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases"
USER_AGENT = "ShooterLauncher-Updater/1.0"

# 资产下载前缀：空串 = GitHub 直连；其余为 Release 通用加速镜像（按序回退）
ASSET_MIRRORS = ("", "https://gh-proxy.com/", "https://ghfast.top/")

CHUNK = 64 * 1024


class UpdateError(Exception):
    """更新过程中的可展示错误（message 面向玩家）。"""


# ============================ 版本比较 ============================

def parse_version(text):
    """把 'v1.3.0' / '1.2' / 'v1.3.0-beta.2' 解析成 (数字段, 预发布标记)。

    返回 (nums_tuple, prerelease_text, prerelease_num)：
      'v1.3.0'          -> ((1, 3, 0), '', 0)
      'v1.3.0-beta.2'   -> ((1, 3, 0), 'beta', 2)
    """
    s = str(text or "").strip()
    m = re.search(r"(\d+(?:\.\d+)*)", s)
    if not m:
        return (), "", 0
    nums = tuple(int(x) for x in m.group(1).split("."))
    pre = re.search(r"[-_ .]?(alpha|beta|rc|pre|dev)[.\-_]?(\d*)", s, re.I)
    if pre is None:
        return nums, "", 0
    return nums, pre.group(1).lower(), int(pre.group(2) or 0)


def _ver_key(text):
    nums, pre, pren = parse_version(text)
    if not nums:
        return ((0, 0, 0, 0), 0, 0)
    nums = nums + (0,) * (4 - len(nums))
    return (nums[:4], 0 if pre else 1, pren)


def is_newer(latest, current):
    """远端版本是否比本地新（预发布版低于同号正式版）。"""
    return _ver_key(latest) > _ver_key(current)


# ============================ Release 查询 ============================

def _request_json(url, timeout=10):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("仓库或 Release 不存在（可能尚未发布版本）") from None
        if exc.code == 403:
            raise UpdateError("GitHub 接口访问受限（请求过于频繁），请稍后重试") from None
        raise UpdateError(f"GitHub 返回错误 {exc.code}") from None
    except urllib.error.URLError as exc:
        raise UpdateError(f"无法连接 GitHub：{exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise UpdateError(f"更新检查超时或网络异常：{exc}") from None
    except ValueError:
        raise UpdateError("GitHub 返回了无法解析的数据") from None


def pick_asset(assets, keywords=("launcher", "启动器")):
    """从 Release 资产里挑启动器 exe：先按关键字，再退任意 .exe。"""
    exes = [a for a in (assets or []) if str(a.get("name", "")).lower().endswith(".exe")]
    for kw in keywords:
        for a in exes:
            if kw.lower() in str(a.get("name", "")).lower():
                return a
    return exes[0] if exes else None


def fetch_latest_release(timeout=10, url=None):
    """查询最新 Release，返回统一结构；失败抛 UpdateError。"""
    data = _request_json(url or LATEST_API, timeout=timeout)
    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        raise UpdateError("最新 Release 缺少版本号")
    assets = []
    for a in data.get("assets") or []:
        assets.append({
            "name": a.get("name", ""),
            "url": a.get("browser_download_url", ""),
            "size": int(a.get("size") or 0),
        })
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "name": data.get("name") or tag,
        "notes": data.get("body") or "",
        "html_url": data.get("html_url") or RELEASES_PAGE,
        "published_at": data.get("published_at") or "",
        "assets": assets,
        "asset": pick_asset(assets),
    }


# ============================ 资产下载 ============================

def download_asset(asset, dest_dir, on_progress=None, timeout=60):
    """下载资产到 dest_dir，直连失败按序回退镜像。返回本地文件 Path。

    on_progress(done_bytes, total_bytes) 每 64KB 回调一次（total 可能为 0）。
    """
    url = str((asset or {}).get("url") or "")
    name = str((asset or {}).get("name") or "update.exe")
    if not url:
        raise UpdateError("该 Release 没有可下载的 exe 资产")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    part = dest.with_suffix(dest.suffix + ".part")
    total = int((asset or {}).get("size") or 0)

    errors = []
    for prefix in ASSET_MIRRORS:
        target_url = prefix + url
        try:
            req = urllib.request.Request(target_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                done = 0
                if part.exists():
                    part.unlink()
                with open(part, "wb") as fp:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        fp.write(chunk)
                        done += len(chunk)
                        if on_progress:
                            on_progress(done, total)
            size = part.stat().st_size
            if total and size != total:
                raise UpdateError(f"下载不完整（{size}/{total} 字节）")
            if dest.exists():
                dest.unlink()
            part.replace(dest)
            return dest
        except UpdateError as exc:
            errors.append(f"{target_url}: {exc}")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            errors.append(f"{target_url}: {type(exc).__name__}: {exc}")
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
    raise UpdateError("所有下载源均失败：" + "；".join(errors[-2:]))


# ============================ 自替换 ============================

def is_frozen():
    return bool(getattr(sys, "frozen", False))


def current_executable():
    return Path(sys.executable).resolve() if is_frozen() else None


def stage_self_update(new_exe, target_exe=None, relaunch=True):
    """生成替换批处理：等待本进程退出 → 覆盖 exe → 重启 → 删除自身。

    返回批处理路径；调用方执行它之后应立刻退出应用。
    """
    new_exe = Path(new_exe).resolve()
    target_exe = Path(target_exe).resolve() if target_exe else current_executable()
    if target_exe is None:
        raise UpdateError("当前不是打包运行，无法自动替换（请手动下载安装包）")
    if not new_exe.is_file():
        raise UpdateError(f"下载的更新文件不存在：{new_exe}")

    bat = target_exe.with_name("_apply_update.bat")
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "rem 等待旧进程释放 exe 文件锁",
        "ping 127.0.0.1 -n 3 >nul",
        ":retry",
        f'move /Y "{new_exe}" "{target_exe}" >nul 2>&1',
        "if errorlevel 1 (",
        "  ping 127.0.0.1 -n 2 >nul",
        "  goto retry",
        ")",
    ]
    if relaunch:
        lines.append(f'start "" "{target_exe}"')
    lines += ["del \"%~f0\"", ""]
    try:
        bat.write_text("\r\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise UpdateError(f"无法写入更新脚本：{exc}") from None
    return bat


def run_update_script(bat_path):
    """以脱离父进程的方式执行替换脚本（父进程随后退出即可）。"""
    bat_path = str(bat_path)
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(["cmd", "/c", bat_path], creationflags=flags,
                         close_fds=True)
        return True
    except OSError:
        return False


def stage_dir():
    """下载临时目录（%TEMP%/ShootingLauncher-update）。"""
    path = Path(tempfile.gettempdir()) / "ShootingLauncher-update"
    path.mkdir(parents=True, exist_ok=True)
    return path
