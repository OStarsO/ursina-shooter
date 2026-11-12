# -*- coding: utf-8 -*-
"""把当前 git 仓库一键发布到 GitHub（纯标准库，无需 gh / git push 凭据）。

用法（Windows PowerShell / cmd）：
    set GITHUB_TOKEN=ghp_xxxxxxxx
    python tools/upload_github.py --owner OStarsO --repo ursina-shooter --public

可选：
    --description "仓库描述"
    --topics python,ursina,pyinstaller,game
    --release v1.1.0 --asset dist/射击启动器.exe
        创建 Release 并上传 exe（走 uploads.github.com，单文件 < 2GB）

令牌要求（Fine-grained PAT）：
    Administration: Read and write   （创建仓库）
    Contents: Read and write         （提交文件、建 Release）

脚本做的事：
    1. 仓库不存在则创建（public/private 由参数决定）
    2. 按 `git ls-files` 收集已提交文件（自动跳过 dist/、logs/ 等被 .gitignore 忽略的内容）
    3. 用 Git Data API 一次性生成 tree + commit，更新 main 分支（单个提交，保留原提交信息）
    4. 设置仓库描述与 topics
    5. 可选：创建 tag/Release 并上传 exe
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
UA = "shooting-launcher-uploader/1.0"


def log(msg):
    print(msg, flush=True)


class GitHubError(Exception):
    pass


def api(method, path, token, data=None, timeout=60, base=API, raw_body=None, extra_headers=None):
    url = path if path.startswith("http") else base + path
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }
    if raw_body is not None:
        body = raw_body
        headers["Content-Type"] = "application/octet-stream"
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            if not payload:
                return {}
            try:
                return json.loads(payload)
            except ValueError:
                return {"raw": payload.decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 401:
            raise GitHubError("令牌无效或已过期（401）。请检查 GITHUB_TOKEN。") from None
        if exc.code == 403:
            raise GitHubError(f"权限不足（403）：{detail}") from None
        raise GitHubError(f"{method} {url} 失败（{exc.code}）：{detail}") from None
    except urllib.error.URLError as exc:
        raise GitHubError(f"网络错误：{exc.reason}") from None


def git(*args, check=True):
    proc = subprocess.run(["git", *args], capture_output=True)
    if check and proc.returncode != 0:
        raise GitHubError(f"git {' '.join(args)} 失败：{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def collect_files():
    """返回 [(path, blob_sha_in_local_git, mode)]，只含已提交文件"""
    out = git("ls-files", "-s", "-z").decode("utf-8", "replace")
    files = []
    for chunk in out.split("\0"):
        if not chunk.strip():
            continue
        meta, path = chunk.split("\t", 1)
        mode, _sha, _stage = meta.split()
        if mode == "160000":  # submodule 跳过
            continue
        files.append((path, mode))
    return files


def read_blob(path):
    """按工作区内容读取（保证上传的是当前文件，而非旧 blob）"""
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def ensure_repo(owner, repo, token, private, description, homepage=""):
    try:
        info = api("GET", f"/repos/{owner}/{repo}", token)
        log(f"仓库已存在：{info.get('html_url')}")
        return info, False
    except GitHubError as exc:
        if "404" not in str(exc):
            raise
    log(f"创建仓库 {owner}/{repo} …")
    payload = {
        "name": repo,
        "description": description or "",
        "private": private,
        "has_issues": True,
        "has_wiki": False,
        "auto_init": False,
    }
    if homepage:
        payload["homepage"] = homepage
    try:
        info = api("POST", "/user/repos", token, payload)
    except GitHubError:
        if not owner:
            raise
        info = api("POST", f"/orgs/{owner}/repos", token, payload)
    log(f"仓库已创建：{info.get('html_url')}")
    return info, True


def current_commit(owner, repo, branch, token):
    try:
        ref = api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}", token)
        return ref["object"]["sha"]
    except GitHubError:
        return None


def push_tree(owner, repo, token, branch="main"):
    files = collect_files()
    if not files:
        raise GitHubError("仓库里没有已提交的文件，先 git add && git commit。")
    head = current_commit(owner, repo, branch, token)
    parent_tree = None
    if head:
        commit = api("GET", f"/repos/{owner}/{repo}/git/commits/{head}", token)
        parent_tree = commit["tree"]["sha"]

    tree_items = []
    for i, (path, mode) in enumerate(files, 1):
        log(f"  上传 {i}/{len(files)}: {path}")
        blob = api("POST", f"/repos/{owner}/{repo}/git/blobs", token,
                   {"content": read_blob(path), "encoding": "base64"}, timeout=180)
        tree_items.append({
            "path": path,
            "mode": "100755" if mode == "100755" else "100644",
            "type": "blob",
            "sha": blob["sha"],
        })

    tree_payload = {"tree": tree_items}
    if parent_tree:
        tree_payload["base_tree"] = parent_tree
    tree = api("POST", f"/repos/{owner}/{repo}/git/trees", token, tree_payload, timeout=180)

    message = git("log", "-1", "--pretty=%B").decode("utf-8", "replace").strip()
    commit_payload = {"message": message or "Initial commit", "tree": tree["sha"], "parents": []}
    if head:
        commit_payload["parents"] = [head]
    new_commit = api("POST", f"/repos/{owner}/{repo}/git/commits", token, commit_payload, timeout=180)

    if head:
        api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}", token, {"sha": new_commit["sha"], "force": False})
    else:
        api("POST", f"/repos/{owner}/{repo}/git/refs", token,
            {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
    log(f"已推送到 {branch}：{new_commit['sha'][:10]}（{len(tree_items)} 个文件）")
    return new_commit["sha"]


def set_meta(owner, repo, token, description, topics, homepage=""):
    payload = {}
    if description:
        payload["description"] = description
    if homepage:
        payload["homepage"] = homepage
    if payload:
        api("PATCH", f"/repos/{owner}/{repo}", token, payload)
    if topics:
        try:
            api("PUT", f"/repos/{owner}/{repo}/topics", token, {"names": topics})
            log(f"topics: {', '.join(topics)}")
        except GitHubError as exc:
            log(f"（topics 设置失败，可忽略：{exc}）")


def create_release(owner, repo, token, tag, asset=None, name=None, body=None):
    try:
        rel = api("POST", f"/repos/{owner}/{repo}/releases", token, {
            "tag_name": tag,
            "name": name or tag,
            "body": body or "射击启动器（Windows x64）。许可证：PolyForm Noncommercial 1.0.0，仅限非商业用途。",
            "draft": False,
            "prerelease": False,
        })
    except GitHubError as exc:
        if "422" in str(exc):
            rel = api("GET", f"/repos/{owner}/{repo}/releases/tags/{tag}", token)
        else:
            raise
    log(f"Release: {rel.get('html_url')}")
    if asset:
        path = Path(asset)
        if not path.is_file():
            raise GitHubError(f"找不到要上传的文件：{asset}")
        size_mb = path.stat().st_size / 1048576
        log(f"上传资源 {path.name}（{size_mb:.1f} MB）…")
        query = urllib.parse.urlencode({"name": path.name})
        api("POST", f"/repos/{owner}/{repo}/releases/{rel['id']}/assets?{query}", token,
            raw_body=path.read_bytes(), timeout=900, base=UPLOADS)
        log("资源上传完成")
    return rel


def main():
    parser = argparse.ArgumentParser(description="把当前 git 仓库发布到 GitHub")
    parser.add_argument("--owner", default=os.environ.get("GITHUB_OWNER", ""), help="仓库所有者（用户名），默认用令牌对应账号")
    parser.add_argument("--repo", required=True, help="仓库名，例如 ursina-shooter")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""), help="PAT，默认读 GITHUB_TOKEN")
    parser.add_argument("--public", action="store_true", help="创建公开仓库（默认私有）")
    parser.add_argument("--private", action="store_true", help="创建私有仓库")
    parser.add_argument("--description", default="基于 ursina 的 3D 射击游戏 + PySide6 启动器（游客登录/单挑/团队竞技/局域网房间 25250），仅限非商业用途。")
    parser.add_argument("--topics", default="ursina,pygame,python,pyinstaller,pyside6,lan-multiplayer,game")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--release", default="", help="创建 Release 的 tag，例如 v1.1.0")
    parser.add_argument("--asset", default="", help="随 Release 上传的文件，例如 dist/射击启动器.exe")
    parser.add_argument("--skip-push", action="store_true", help="只建仓库/设元信息，不推文件")
    args = parser.parse_args()

    if not args.token:
        log("缺少令牌：请设置环境变量 GITHUB_TOKEN，或传 --token。")
        log("Fine-grained PAT 需勾选：Administration(读写) + Contents(读写)")
        return 2

    private = not args.public if (args.public or args.private) else True

    try:
        me = api("GET", "/user", args.token)
        owner = args.owner or me["login"]
        log(f"账号：{me['login']}（owner={owner}）")
        repo_info, created = ensure_repo(owner, args.repo, args.token, private, args.description)
        if not args.skip_push:
            push_tree(owner, args.repo, args.token, args.branch)
        set_meta(owner, args.repo, args.token, args.description,
                 [t.strip() for t in args.topics.split(",") if t.strip()],
                 homepage=repo_info.get("homepage", ""))
        if args.release:
            create_release(owner, args.repo, args.token, args.release, args.asset or None)
        log("")
        log(f"完成：{repo_info.get('html_url')}")
        return 0
    except GitHubError as exc:
        log(f"失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
