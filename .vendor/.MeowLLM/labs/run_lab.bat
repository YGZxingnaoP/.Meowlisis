@echo off
rem Launcher shim only. All logic lives in launch.py.
rem Keep this file ASCII-only and LINEAR (no labels, no goto, no multi-line if).
rem Reason: if this file ever gets rewritten with LF-only line endings, cmd.exe
rem mis-parses Chinese rem lines and multi-line constructs, producing garbage
rem like "'m' is not recognized as an internal or external command".
setlocal
set "PY=%~dp0..\..\..\runtime\311\python.exe"
if not exist "%PY%" set "PY=%MEOWLLM_PYTHON%"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"
"%PY%" "%~dp0launch.py" %*
if errorlevel 1 pause
