@echo off
REM =============================================================================
REM run.bat — B 站离线缓存合并工具入口
REM 用法:
REM   run.bat [根目录] [输出目录]
REM   根目录默认为本脚本所在目录的父目录（即项目根）
REM =============================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

REM 脚本所在目录与默认根目录
set "_SCRIPT_DIR=%~dp0"
for %%d in ("!_SCRIPT_DIR!..") do set "_DEFAULT_ROOT=%%~fd"

REM 定位 python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python。请安装 Python 3.9+ 并确保在 PATH 中。
    echo 下载: https://www.python.org/downloads/
    exit /b 1
)

REM 检查 ffmpeg（核心脚本也会自行检查，此处仅提示）
set "_FFMPEG=%_SCRIPT_DIR%..\bin\ffmpeg.exe"
if not exist "!_FFMPEG!" (
    where ffmpeg >nul 2>nul || (
        echo [警告] 未找到 ffmpeg.exe。建议将 ffmpeg.exe 放入 bin\ 目录。
        echo 下载: https://ffmpeg.org/download.html
    )
)

REM 组装参数并执行核心脚本
set "_CMD=python "!_SCRIPT_DIR!merge_videos.py""
if not "%~1"=="" (
    set "_CMD=!_CMD! "%~1""
) else (
    set "_CMD=!_CMD! "!_DEFAULT_ROOT!""
)
if not "%~2"=="" set "_CMD=!_CMD! "%~2""

echo [信息] 执行: !_CMD!
echo.
call !_CMD!
set "_EXITCODE=%errorlevel%"

echo.
if "!_EXITCODE!"=="0" (
    echo 处理完成。
) else (
    echo 处理结束，存在失败项或错误（退出码 !_EXITCODE!）。
)

exit /b !_EXITCODE!
