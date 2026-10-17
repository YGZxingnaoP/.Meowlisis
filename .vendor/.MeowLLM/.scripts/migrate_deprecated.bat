@echo off
rem ===========================================================================
rem  Move retired MIRROR code out of the module into _deprecated\.
rem
rem  Run by double-click. ASCII only on purpose: cmd reads .bat with the OEM
rem  codepage, so non-ASCII characters in the file break parsing. File names
rem  that contain non-ASCII are matched with wildcards instead of being typed.
rem
rem  What it moves:
rem    meowllm\mirror\            -> _deprecated\mirror\
rem    docs\notes\MIRROR_*.md     -> _deprecated\
rem    labs\RESULT_MIRROR_*.md    -> _deprecated\
rem
rem  What it also removes:
rem    D:\.Meowlisis\.vendor\MeowLLM\   <- wrong-path tree created by mistake
rem
rem  What it deliberately does NOT move:
rem    meowllm\cache\prefix.py          still used by server\state.py
rem    config.yml  mirror: section      still read by config defaults
rem    labs\*                           dev tool, de-wire later
rem ===========================================================================
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title MeowLLM migrate retired code

set "HERE=%~dp0"
set "ROOT=%HERE%.."
set "DEP=%ROOT%\_deprecated"

echo [migrate] module = %ROOT%
echo [migrate] target = %DEP%
echo.

if not exist "%ROOT%\config.yml" echo [migrate] ERROR: config.yml not found, wrong folder
if not exist "%ROOT%\config.yml" goto :fail

if not exist "%DEP%" mkdir "%DEP%"
if not exist "%DEP%" echo [migrate] ERROR: cannot create _deprecated
if not exist "%DEP%" goto :fail

rem ---------------- 1) meowllm\mirror ----------------
if not exist "%ROOT%\meowllm\mirror" echo [migrate] meowllm\mirror already moved
if not exist "%ROOT%\meowllm\mirror" goto :mirror_done
echo [migrate] moving meowllm\mirror ...
move "%ROOT%\meowllm\mirror" "%DEP%\mirror" >nul 2>&1
if errorlevel 1 echo [migrate]   FAILED - close MeowLLM first if it is running
if not errorlevel 1 echo [migrate]   ok
:mirror_done

rem ---------------- 2) docs note ----------------
if not exist "%ROOT%\docs\notes\MIRROR_*.md" echo [migrate] docs note already moved
if not exist "%ROOT%\docs\notes\MIRROR_*.md" goto :note_done
echo [migrate] moving docs note ...
move "%ROOT%\docs\notes\MIRROR_*.md" "%DEP%\" >nul 2>&1
if errorlevel 1 echo [migrate]   FAILED
if not errorlevel 1 echo [migrate]   ok
:note_done

rem ---------------- 3) experiment report ----------------
if not exist "%ROOT%\labs\RESULT_MIRROR_*.md" echo [migrate] report already moved
if not exist "%ROOT%\labs\RESULT_MIRROR_*.md" goto :report_done
echo [migrate] moving experiment report ...
move "%ROOT%\labs\RESULT_MIRROR_*.md" "%DEP%\" >nul 2>&1
if errorlevel 1 echo [migrate]   FAILED
if not errorlevel 1 echo [migrate]   ok
:report_done

rem ---------------- 4) wrong-path tree ----------------
if not exist "D:\.Meowlisis\.vendor\MeowLLM" goto :stray_done
echo [migrate] removing wrong-path tree D:\.Meowlisis\.vendor\MeowLLM ...
rd /s /q "D:\.Meowlisis\.vendor\MeowLLM" >nul 2>&1
if errorlevel 1 echo [migrate]   FAILED - delete it manually
if not errorlevel 1 echo [migrate]   ok
:stray_done

echo.
echo [migrate] done.
echo [migrate] module root:
dir /b "%ROOT%"
echo.
echo [migrate] _deprecated:
dir /b "%DEP%"
echo.
echo [migrate] next: run start.bat check to confirm the service still loads

set "PAUSE_ON_EXIT="
if "%~1"=="" set "PAUSE_ON_EXIT=1"
if defined PAUSE_ON_EXIT pause
endlocal
exit /b 0

:fail
set "PAUSE_ON_EXIT="
if "%~1"=="" set "PAUSE_ON_EXIT=1"
if defined PAUSE_ON_EXIT pause
endlocal
exit /b 1
