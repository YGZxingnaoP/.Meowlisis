@echo off
rem ===========================================================================
rem  Upload to AutoDL over SSH with password from labs\autoDL\
rem
rem  ASCII only: cmd.exe parses .bat in the OEM codepage, UTF-8 breaks it.
rem
rem  Usage:
rem      upload_cloud.bat --check     -> parse self-test only
rem      upload_cloud.bat check       -> connect and inspect the instance
rem      upload_cloud.bat upsync      -> upload the training package
rem      upload_cloud.bat setup       -> pip deps + fetch Qwen3-0.6B
rem      upload_cloud.bat fetch-data  -> clone LoCoMo / PerLTQA
rem      upload_cloud.bat serve       -> start dashboard in background
rem      upload_cloud.bat all         -> check + upsync + setup + fetch + serve
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

set "CMD=%~1"
if "%CMD%"=="" set "CMD=check"

cd /d "%HERE%"
echo [cloud] cmd=%CMD%  python=%PY%
"%PY%" cloud.py %CMD%
set "RC=%ERRORLEVEL%"
echo.
echo [cloud] exit code %RC%
pause
