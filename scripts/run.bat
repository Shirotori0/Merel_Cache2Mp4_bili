@echo off
REM =============================================================================
REM run.bat — B 站离线缓存合并工具入口
REM
REM 用法:
REM   run.bat                       双击运行，弹出文件夹选择窗口
REM   run.bat <缓存目录>             指定缓存目录
REM   run.bat <缓存目录> <输出目录>  同时指定输出目录
REM
REM 不传参数时由 Python 脚本弹出文件夹选择窗口；
REM 生成的 mp4 默认输出到「所选文件夹的父目录」，避免污染缓存。
REM =============================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

set "_SCRIPT_DIR=%~dp0"

REM 定位 python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python。请安装 Python 3.9+ 并确保在 PATH 中。
    echo 下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查 ffmpeg（核心脚本也会自行检查，此处仅提示）
if not exist "%_SCRIPT_DIR%..\bin\ffmpeg.exe" (
    where ffmpeg >nul 2>nul || (
        echo [警告] 未找到 ffmpeg.exe。建议将 ffmpeg.exe 放入 bin\ 目录。
        echo 下载: https://ffmpeg.org/download.html
        echo.
    )
)

REM 组装参数并执行核心脚本
set "_CMD=python "!_SCRIPT_DIR!merge_videos.py""
if not "%~1"=="" set "_CMD=!_CMD! "%~1""
if not "%~2"=="" set "_CMD=!_CMD! "%~2""

call !_CMD!
set "_EXITCODE=%errorlevel%"

echo.
if "!_EXITCODE!"=="0" (
    echo 处理完成。
) else (
    echo 处理结束，存在失败项或错误（退出码 !_EXITCODE!）。
)

REM 双击运行时暂停，便于查看结果；命令行传参时不打扰
if "%~1"=="" pause

exit /b !_EXITCODE!