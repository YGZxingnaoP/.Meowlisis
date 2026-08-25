@echo off
chcp 65001 >nul
cd /d "%~dp0"

set VER=31.7.7
set EDIR=node_modules\electron
set DIST=%EDIR%\dist

echo ========================================
echo   喵呜桌宠 - 安装 / 启动
echo ========================================
echo.

:: ---- 检测依赖是否已就绪 ----
if exist "node_modules\ws\package.json" if exist "%DIST%\electron.exe" (
    echo [检测] 依赖已就绪，直接启动...
    echo.
    goto START
)

:: ---- 1. 安装 Node 依赖（跳过 electron 二进制下载） ----
echo [1/3] 安装 Node 依赖...
if exist node_modules rmdir /s /q node_modules
call npm install --ignore-scripts --registry=https://registry.npmmirror.com
if errorlevel 1 goto FAIL

:: ---- 2. 准备 Electron 运行时 ----
echo.
echo [2/3] 准备 Electron 运行时...
if exist "%DIST%\electron.exe" goto WRITEPATH
echo     下载 Electron 二进制 (约 100MB，请稍候)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://npmmirror.com/mirrors/electron/%VER%/electron-v%VER%-win32-x64.zip' -OutFile '.electron.zip'"
if not exist .electron.zip (
    echo [错误] Electron 二进制下载失败，请检查网络
    goto FAIL
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Path '.electron.zip' -DestinationPath '%DIST%' -Force"
if exist .electron.zip del /q .electron.zip

:WRITEPATH
echo electron.exe> "%EDIR%\path.txt"

:: ---- 3. 启动桌宠 ----
:START
echo [3/3] 启动桌宠...
npm start
goto END

:FAIL
echo.
echo ========================================
echo [错误] 安装失败，请检查网络后重新运行本脚本
echo ========================================
pause

:END
