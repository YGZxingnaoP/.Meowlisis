@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

:: 使用嵌入式 Python 环境（假设 env 目录下有 python.exe）
set PYTHON_EXE=%~dp0env\python.exe

:: 如果不存在，尝试使用系统 Python
if not exist "%PYTHON_EXE%" (
    echo 未找到嵌入式 Python: %PYTHON_EXE%
    echo 尝试使用系统 Python...
    set PYTHON_EXE=python
)

echo 使用 Python: %PYTHON_EXE%
%PYTHON_EXE% -V

echo 开始下载模型...
%PYTHON_EXE% download_models.py

echo 按任意键退出...
pause > nul