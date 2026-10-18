@echo off
rem ===========================================================================
rem  dmem dashboard - REMOTE mode. Double-click this.
rem
rem  Order matters (this is what made the page look blank/white before):
rem    1. kill whatever is still listening on the port  (a stale panel serves
rem       the OLD page -> no chart, looks broken)
rem    2. start the server in the background
rem    3. wait 4s, THEN open the browser
rem
rem  ASCII only: cmd.exe parses .bat in the OEM codepage.
rem ===========================================================================
setlocal EnableExtensions

if /I "%~1"=="--check" (
    echo BAT_PARSE_OK
    exit /b 0
)

rem  NOTE: this value is bumped whenever the server code changes, so that a
rem  stale panel process (old Python, new HTML -> page hangs on "connecting")
rem  can never be reused by accident.
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8142"

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

pushd "%HERE%\..\..\..\.." >nul 2>nul
if errorlevel 1 (
    echo [ERROR] cannot resolve project root
    popd
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd >nul

set "PY="
if exist "%ROOT%\runtime\311\python.exe" set "PY=%ROOT%\runtime\311\python.exe"
if not defined PY if exist "%ROOT%\runtime\312\python.exe" set "PY=%ROOT%\runtime\312\python.exe"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [ERROR] python runtime not found
    pause
    exit /b 1
)

echo ============================================================
echo  dmem dashboard  [REMOTE: AutoDL]
echo    port  : %PORT%
echo    python: %PY%
echo    url   : http://127.0.0.1:%PORT%
echo ============================================================
echo.

echo [1/3] closing any stale panel on port %PORT% ...
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo       killing pid %%A
    taskkill /F /T /PID %%A >nul 2>nul
)
timeout /t 1 /nobreak >nul

echo [2/3] starting server in background ...
cd /d "%HERE%"
start "dmem-panel-%PORT%" /min "%PY%" webui.py --remote --model /root/autodl-tmp/models/Qwen3-8B --port %PORT%

echo [3/3] waiting for the server ...
set /a _TRY=0
:WAITLOOP
set /a _TRY+=1
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "try{ $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:%PORT%/api/state?out=out/r64-ctx768-a2'; exit 0 }catch{ exit 1 }" >nul 2>nul
if not errorlevel 1 goto READY
if %_TRY% lss 12 goto WAITLOOP
echo [WARN] server did not respond in time; opening browser anyway.

:READY
echo.
echo opening http://127.0.0.1:%PORT%
start "" "http://127.0.0.1:%PORT%"

echo.
echo Panel window is minimized (title: dmem-panel-%PORT%).
echo If the page looks empty, press Ctrl+F5 in the browser once.
echo Close this window anytime - the server keeps running in its own window.
echo.
pause
