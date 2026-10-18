@echo off
rem ===========================================================================
rem  Download trained dmem artifacts from AutoDL into docs/output/<date>/
rem
rem  Double-click this. It shows progress per file and writes MANIFEST.json.
rem
rem  Usage:
rem      download_artifacts.bat              -> newest finished run
rem      download_artifacts.bat out/run2     -> specific run
rem      download_artifacts.bat --check      -> parse self-test only
rem
rem  ASCII only: cmd.exe parses .bat in the OEM codepage.
rem ===========================================================================
setlocal EnableExtensions

if /I "%~1"=="--check" (
    echo BAT_PARSE_OK
    exit /b 0
)

chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

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

title dmem download artifacts
cd /d "%HERE%"
echo ============================================================
echo   downloading dmem artifacts from AutoDL
echo ============================================================
echo.

"%PY%" download_artifacts.py %1
set "RC=%ERRORLEVEL%"
echo.
echo ============================================================
echo   exit code: %RC%   (0 = all files downloaded)
echo ============================================================
echo.
echo Files are archived under:
echo   %ROOT%\.vendor\.MeowLLM\docs\output\
echo.
pause
