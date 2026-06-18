@echo off
chcp 65001 >nul
title Sophia Chat 打包构建

echo ============================================
echo   Sophia Chat - 桌面端打包构建
echo ============================================
echo.

:: 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: 安装/更新依赖
echo [1/3] 安装项目依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: 安装 PyInstaller
echo [2/3] 安装 PyInstaller...
pip install pyinstaller -q

:: 清理旧构建
echo [3/3] 清理旧构建 & 开始打包...
if exist "build" rmdir /s /q "build"
if exist "dist\Sophia Chat" rmdir /s /q "dist\Sophia Chat"

pyinstaller sophia_chat.spec --clean --noconfirm

if %errorlevel% equ 0 (
    echo.
    echo ============================================
    echo   打包成功！
    echo   输出目录: dist\Sophia Chat\
    echo   主程序:   dist\Sophia Chat\Sophia Chat.exe
    echo ============================================
    :: 打开输出目录
    start "" "dist\Sophia Chat"
) else (
    echo.
    echo [错误] 打包失败，请检查输出日志
)

pause
