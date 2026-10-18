@echo off
rem ===========================================================================
rem  START the cloud training. Double-click this. Nothing else.
rem
rem  It prints one of two things and then WAITS so you can read it:
rem      START OK    pid = 12345
rem      START FAILED + the real cloud log tail
rem
rem  Usage:
rem      start_train_cloud.bat                    -> out/r64-ctx768-a2
rem      start_train_cloud.bat out/run2
rem      start_train_cloud.bat --check            -> parse self-test only
rem
rem  ASCII only: cmd.exe parses .bat in the OEM codepage.
rem ===========================================================================
setlocal EnableExtensions

if /I "%~1"=="--check" (
    echo BAT_PARSE_OK
    exit /b 0
)

set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

pushd "%HERE%\..\..\..\.." >nul 2>nul
if errorlevel 1 (
    echo [ERROR] cannot resolve project root from %HERE%
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
    echo [ERROR] python runtime not found under %ROOT%\runtime
    pause
    exit /b 1
)

set "OUT=%~1"
if "%OUT%"=="" set "OUT=out/r64-ctx768-a2"

title dmem start - %OUT%
cd /d "%HERE%"

echo ============================================================
echo   starting cloud training
echo   out : %OUT
echo   py  : %PY%
echo ============================================================
echo.

"%PY%" remote.py start %OUT%
set "RC=%ERRORLEVEL%"
echo.
echo ============================================================
echo   exit code: %RC%    (0 = started successfully)
echo ============================================================
pause
