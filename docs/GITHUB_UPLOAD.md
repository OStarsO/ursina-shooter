# 上传到 GitHub

仓库目标：`OStarsO/ursina-shooter` · Public · 许可证 PolyForm Noncommercial 1.0.0

三种方式任选，**推荐方式 A**（脚本内置建仓、提交、Release 上传）。

---

## 方式 A：用内置脚本（无需 gh、无需 git push 凭据）

最省事：直接双击项目根目录的 **`上传到GitHub.bat`**，粘贴 PAT 后回车即可（输入不回显），
脚本会建仓、推送、设置元信息、创建 Release 并上传 exe。

或手动执行下面的命令：

### 1. 生成令牌

GitHub → Settings → Developer settings → **Personal access tokens → Fine-grained tokens → Generate new token**

- Repository access：`All repositories`（新建仓库需要）
- Permissions：
  - **Administration: Read and write**（创建仓库）
  - **Contents: Read and write**（提交文件 / 发 Release）
- 复制生成的 `github_pat_...`（只显示一次）

### 2. 运行

```bat
cd /d D:\PyCharmMiscProject\射击
set GITHUB_TOKEN=github_pat_xxx
python tools\upload_github.py --owner OStarsO --repo ursina-shooter --public
```

要连 exe 一起发 Release（约 48MB）：

```bat
python tools\upload_github.py --owner OStarsO --repo ursina-shooter --public ^
  --release v1.1.0 --asset dist\射击启动器.exe
```

脚本会：检测/创建仓库 → 按 `git ls-files` 上传（自动跳过 dist、logs 等）→ 设置描述与 topics → 可选建 Release 并上传 exe。

> 令牌用完请到 GitHub 立即 Revoke。

---

## 方式 B：GitHub CLI（需先装 gh）

```bat
gh auth login
gh repo create OStarsO/ursina-shooter --public --source=. --remote=origin ^
  --description "基于 ursina 的 3D 射击游戏 + PySide6 启动器，仅限非商业用途"
git push -u origin main
gh release create v1.1.0 "dist\射击启动器.exe" --title "v1.1.0 联机版" --notes "首个带登录与局域网房间的版本"
```

## 方式 C：纯手动

1. <https://github.com/new> → 名称 `ursina-shooter` → **Public** → 不勾 README/.gitignore/license → Create
2. 本目录执行：
   ```bat
   git remote add origin https://github.com/OStarsO/ursina-shooter.git
   git push -u origin main
   ```
3. 网页 Release 页面 → Draft a new release → tag `v1.1.0` → 拖入 `dist\射击启动器.exe`

---

## 上传后检查

- [ ] 仓库首页 README 正常渲染（中文、表格、代码块）
- [ ] 侧栏 License 显示 **PolyForm Noncommercial 1.0.0**
- [ ] 文件数 19 个（含 `上传到GitHub.bat`），**没有** `dist/`、`logs/`、`__pycache__`、`settings.json`、`scores.json`
- [ ] Topics 已设置（ursina / python / pyside6 / lan-multiplayer …）
- [ ] 如需发布 exe：Release 里有 `射击启动器.exe`，或已推 `v*` tag 由 Actions 自动构建
