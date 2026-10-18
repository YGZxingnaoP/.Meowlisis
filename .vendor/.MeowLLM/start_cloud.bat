@echo off
rem ===========================================================================
rem  Start the CLOUD MeowLLM and tunnel it to 127.0.0.1:18100
rem
rem  Just double-click. It asks for two things (only when needed):
rem    1) the AutoDL login line  -> ssh -p 49229 root@connect.westb.seetacloud.com
rem    2) the password           (typed, not echoed)
rem
rem  Then it:
rem    - connects + pre-flight (python / torch / model / dmem weights / GPU)
rem    - uploads code + config automatically if the remote copy is missing
rem    - starts the remote service, waits for HTTP 200
rem    - opens the local tunnel and prints the lab URL (http://127.0.0.1:18700)
rem    - saves the credentials to labs\autoDL\ (gitignored) so next time it
rem      connects without asking; if the saved ones stopped working (new GPU
rem      card = new host/port/password) it asks again automatically.
rem
rem  Pass-through flags (also fine to run .scripts\cloud_serve.py directly):
rem      start_cloud.bat --preflight     only check the remote, do not start
rem      start_cloud.bat --setup         install deps + download the backbone
rem      start_cloud.bat --restart       force restart the remote service
rem      start_cloud.bat --attach        only open the tunnel
rem      start_cloud.bat --shared        not isolated: write real character/userinfo
rem      start_cloud.bat --stop          stop the remote service
rem
rem  ASCII only: cmd reads .bat with the OEM codepage.
rem ===========================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title MeowLLM cloud

set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
set "PY=%ROOT%\runtime\311\python.exe"
if not exist "%PY%" set "PY=%ROOT%\runtime\312\python.exe"
if not exist "%PY%" set "PY=%ROOT%\runtime\310\python.exe"
if not exist "%PY%" if defined MEOWLLM_PYTHON set "PY=%MEOWLLM_PYTHON%"
if not exist "%PY%" (
    echo [cloud] python not found under %ROOT%\runtime
    echo [cloud] set MEOWLLM_PYTHON=C:\path\to\python.exe and retry
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
cd /d "%HERE%"
echo.
echo [cloud] python = %PY%
echo [cloud] module = %CD%
echo.

"%PY%" "%~dp0.scripts\cloud_serve.py" %*
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" echo [cloud] exited with %RC%
echo [cloud] note: the tunnel dies with this window; the remote service keeps running.
echo [cloud]       reopen with:  start_cloud.bat --attach
if defined MEOWLLM_NO_PAUSE goto :done
pause
:done
exit /b %RC%
