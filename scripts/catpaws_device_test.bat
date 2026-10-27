@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\runtime\311\python.exe"
if not exist "%PY%" set "PY=python"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1

cd /d "%ROOT%\scripts"
start "CatPaws Dialog" cmd /k ""%PY%" -X utf8 catpaws_device_test.py"
timeout /t 2 >nul
start "CatPaws Ops Log" cmd /k ""%PY%" -X utf8 catpaws_live_log.py"
endlocal
