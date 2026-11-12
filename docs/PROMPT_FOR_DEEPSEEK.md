# 给 DeepSeek 的提示词（可直接复制）

> 场景：让具备本机文件访问能力的 AI 助手把 `D:\PyCharmMiscProject\射击` 上传到 GitHub。
> 若对方**不能**访问本机文件，见文末“无本机权限的降级提示词”。

---

## A. 完整版提示词

```
你的任务：把本地已经初始化好的 git 仓库发布到我的 GitHub 账号，不要改动任何代码内容。

【环境】
- 本地仓库：D:\PyCharmMiscProject\射击（已 git init，分支 main，已有 2 次提交）
- GitHub 账号：OStarsO（https://github.com/OStarsO）
- 本机 Python 可用，git 可用；不要使用 gh 命令（未安装）
- 我已准备好 Fine-grained PAT，权限为 Administration(读写) + Contents(读写)；
  运行前我会把令牌放进环境变量 GITHUB_TOKEN，你不需要、也不要在输出里打印令牌

【目标】
1. 在 OStarsO 下创建公开仓库 ursina-shooter
2. 推送 main 分支全部已提交文件（脚本会按 git ls-files 收集，自动跳过 dist/、logs/、
   __pycache__、settings.json、scores.json、hit.wav、.workbuddy/）
3. 仓库描述：基于 ursina 的 3D 射击游戏 + PySide6 启动器（游客登录/单挑/团队竞技/局域网房间 25250），仅限非商业用途。
4. topics：ursina, python, pyside6, pyinstaller, lan-multiplayer, game
5. 创建 Release：tag v1.1.0，标题「v1.1.0 联机版」，并上传 dist\射击启动器.exe（约 48MB）

【必须遵守的约束】
- 许可证是 PolyForm Noncommercial 1.0.0（仅限非商业用途），LICENSE 文件必须原样上传，
  不得替换成 MIT/Apache/GPL，也不得删除 README 里的非商用声明
- 仓库必须公开（Public）
- 不要上传 dist/、build/、logs/、*.log、settings.json、scores.json、*.spec、__pycache__、.workbuddy/
- 不要 force push，不要修改已有提交历史，不要改写代码文件
- 若仓库已存在：不要删除、不要清空，只在 main 上追加提交（脚本已处理）

【执行方式（优先）】
在 D:\PyCharmMiscProject\射击 下执行：
    python tools\upload_github.py --owner OStarsO --repo ursina-shooter --public ^
        --release v1.1.0 --asset dist\射击启动器.exe
该脚本会：检测/创建仓库 → 用 Git Data API 单次提交全部文件 → 设置描述与 topics →
创建 Release 并上传 exe。逐步把脚本输出贴给我，遇到报错先诊断再重试（最多 2 次）。

【备用方案】
若脚本因令牌权限失败：
- 401：令牌无效 → 让我重新生成
- 403：缺 Administration/Contents 写权限 → 告诉我具体缺哪个
- 422：仓库已存在且冲突 → 只做推送、跳过建仓
若脚本不可用，改用 GitHub REST API 手工完成同样的步骤（curl 或 python urllib 均可），
但不要改用 git push（本机没有配置凭据助手，HTTPS 推送会失败）。

【验收标准，逐条输出结果】
1. 仓库地址可访问且为 Public
2. main 分支文件清单（共 19 个，不含 exe）：
   .gitattributes、.github/workflows/release.yml、.gitignore、LICENSE、README.md、
   app_style.py、launcher.py、net_ui.py、requirements.txt、room_net.py、
   tests_room.py、tests_ui.py、tools/upload_github.py、
   docs/GITHUB_UPLOAD.md、docs/PROMPT_FOR_DEEPSEEK.md、
   assets/icon.ico、assets/icon.png、射击.py、上传到GitHub.bat
3. GitHub 侧栏 License 标签显示 PolyForm Noncommercial 1.0.0
4. Release v1.1.0 存在且含 射击启动器.exe，显示文件大小与下载链接
5. 最终输出：仓库 URL、Release URL、失败项（如有）
```

---

## B. 无本机权限的降级提示词

如果那个助手只能聊天、读不到你的磁盘，用这一版，让它生成可执行脚本，你本机运行：

```
帮我写一个 Python 脚本（只用标准库），把当前目录的 git 仓库发布到 GitHub：
1. 读环境变量 GITHUB_TOKEN，用 REST API 创建公开仓库 <owner>/ursina-shooter
2. 用 Git Data API（blobs → tree → commit → refs）一次性提交 git ls-files 列出的所有文件
3. 设置 description 与 topics
4. 创建 tag v1.1.0 的 Release，并把 dist\射击启动器.exe（48MB）上传为该 Release 的资源
   （注意资源上传走 https://uploads.github.com，Content-Type: application/octet-stream）
5. 错误处理：401 令牌无效、403 权限不足、422 仓库已存在时改为只推送
6. 输出每一步的进度与最终仓库 URL
不要使用 gh 命令，不要使用 git push，不要打印令牌明文。
```

（本仓库的 `tools/upload_github.py` 就是按这套要求实现并可直接使用的版本。）
