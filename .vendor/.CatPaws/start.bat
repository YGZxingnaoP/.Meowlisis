@echo off
chcp 65001 >nul
set PROJECT_DIR=%~dp0
set PYTHON_EXE=%PROJECT_DIR%..\..\runtime\311\python.exe
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

cd /d "%PROJECT_DIR%"
echo 启动 CatPaws 服务...
"%PYTHON_EXE%" "%PROJECT_DIR%src\cw\server.py" %*

pause
