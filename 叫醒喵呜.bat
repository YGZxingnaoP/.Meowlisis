@echo off
chcp 65001 >nul

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\runtime\python.exe" (
    echo 错误: 未找到 Python 运行环境
    pause
    exit /b 1
)

cd /d "%ROOT%"

echo 正在清理残留的配置服务进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":1801 " ^| findstr "LISTENING"') do (
    echo 发现残留进程 PID=%%a，正在结束...
    taskkill /F /PID %%a >nul 2>nul
)

echo.
echo 正在启动配置管理服务...
start "喵呜配置服务-运行日志" /D "%ROOT%" cmd /k "runtime\python.exe config_gui.py"

echo 等待服务准备就绪...
timeout /t 3 /nobreak >nul
start http://127.0.0.1:1801

echo.
echo 服务已启动。若独立窗口消失，说明程序报错，请查看该窗口内容。
echo.
pause
