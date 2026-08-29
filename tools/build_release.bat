@echo off
REM =============================================================================
REM build_release.bat — 一键打包发布 ZIP
REM 将 bin/、scripts/、README.md、.gitignore 打包为 release.zip 到 release/ 目录
REM =============================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

set "_PROJECT_ROOT=%~dp0.."
set "_RELEASE_DIR=%~dp0..\release"
set "_STAGE=%_RELEASE_DIR%\staging\bili-cache2mp4"

echo [信息] 项目根: %_PROJECT_ROOT%
echo [信息] 发布目录: %_RELEASE_DIR%
echo.

REM 检查 ffmpeg 是否存在
if not exist "%_PROJECT_ROOT%\bin\ffmpeg.exe" (
    echo [警告] bin\ffmpeg.exe 不存在。发布包将不包含 ffmpeg，需用户自备。
    echo 建议将精简版 ffmpeg.exe 放入 bin\ 目录。
) else (
    echo [信息] 检测到 bin\ffmpeg.exe
)

REM 清理旧 staging
if exist "%_STAGE%" rmdir /s /q "%_STAGE%"
if not exist "%_STAGE%" mkdir "%_STAGE%"

REM 复制核心文件（排除 __pycache__）
if not exist "%_STAGE%\scripts" mkdir "%_STAGE%\scripts"
xcopy /y /i /e "%_PROJECT_ROOT%\scripts" "%_STAGE%\scripts" >nul
if exist "%_STAGE%\scripts\__pycache__" rmdir /s /q "%_STAGE%\scripts\__pycache__"
if exist "%_PROJECT_ROOT%\bin" xcopy /y /i /e "%_PROJECT_ROOT%\bin" "%_STAGE%\bin" >nul
if exist "%_PROJECT_ROOT%\README.md" copy /y "%_PROJECT_ROOT%\README.md" "%_STAGE%\README.md" >nul
if exist "%_PROJECT_ROOT%\LICENSE" copy /y "%_PROJECT_ROOT%\LICENSE" "%_STAGE%\LICENSE" >nul

REM 压缩（使用 PowerShell 的 Compress-Archive）
echo [信息] 压缩中...
powershell -NoProfile -Command "Compress-Archive -Path '%_STAGE%\*' -DestinationPath '%_RELEASE_DIR%\bili-cache2mp4-release.zip' -Force"
if errorlevel 1 (
    echo [错误] 压缩失败
    exit /b 1
)

REM 校验体积
for %%f in ("%_RELEASE_DIR%\bili-cache2mp4-release.zip") do set "_ZIPSIZE=%%~zf"
echo.
echo [完成] 发布包已生成: %_RELEASE_DIR%\bili-cache2mp4-release.zip
echo       体积: %_ZIPSIZE% 字节

REM 清理 staging（删除整个 staging 目录）
if exist "%_RELEASE_DIR%\staging" rmdir /s /q "%_RELEASE_DIR%\staging" >nul 2>&1

exit /b 0
