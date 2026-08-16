@echo off
chcp 65001 >nul

if not exist ".\runtime\python.exe" (
    echo 错误: 未找到 Python 运行环境，请确保 runtime 目录下存在 python.exe
    pause
    exit /b 1
)
start /b .\runtime\python.exe config_gui.py

echo 等待服务准备就绪...
timeout /t 3 /nobreak >nul
start  http://127.0.0.1:1801

pause
