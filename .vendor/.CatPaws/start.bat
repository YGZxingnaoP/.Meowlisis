@echo off
chcp 65001 >nul
set PROJECT_DIR=%~dp0
REM 运行环境与主项目共用：<项目根>\runtime\311\python.exe
set PYTHON_EXE=%PROJECT_DIR%..\..\runtime\311\python.exe
set PADDLEOCR_HOME=%PROJECT_DIR%env\models\ocr
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

cd /d "%PROJECT_DIR%"
echo 启动 CatPaws 客户端...
"%PYTHON_EXE%" "%PROJECT_DIR%src\server.py"

pause
