@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

set "PY=runtime\311\python.exe"
if not exist "%PY%" (
  echo [ERROR] %PY% not found
  pause
  exit /b 1
)

"%PY%" "scripts\MossLive-test\mosslive_test.py" --config "scripts\MossLive-test\config.json" %*
set "CODE=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %CODE%
