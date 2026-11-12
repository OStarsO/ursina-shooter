@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   射击项目 - 上传到 GitHub
echo   目标：OStarsO/ursina-shooter  (Public)
echo ============================================
echo.

if "%GITHUB_TOKEN%"=="" (
    echo 请粘贴 Fine-grained PAT（输入过程不显示，回车确认）
    echo 权限需勾选：Administration 读写 + Contents 读写
    echo.
    for /f "delims=" %%i in ('powershell -NoProfile -Command "$s=Read-Host -AsSecureString; [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"') do set "GITHUB_TOKEN=%%i"
)

if "%GITHUB_TOKEN%"=="" (
    echo [错误] 没有拿到令牌，退出。
    pause
    exit /b 1
)

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

echo 使用解释器：%PY%
echo.
"%PY%" tools\upload_github.py --owner OStarsO --repo ursina-shooter --public ^
    --release v1.1.0 --asset "dist\射击启动器.exe"

echo.
echo ============================================
echo   完成。仓库：https://github.com/OStarsO/ursina-shooter
echo   记得回 GitHub 把刚才的令牌 Revoke 掉。
echo ============================================
pause
