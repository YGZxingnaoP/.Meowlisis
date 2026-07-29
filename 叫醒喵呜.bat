@echo off
if not exist ".\runtime\python.exe" (
    echo 错误: 未找到 Python 运行环境，请确保 runtime 目录下存在 python.exe
    pause
    exit /b 1
)
.\runtime\python.exe config_gui.py
pause
