@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem ============================================================
rem  Full project pack (includes runtime and the .vendor components)
rem  Output: scripts\dist\Meowlisis_full.zip and a .sha256 sidecar
rem  Always excluded: .git .vs .idea .github __pycache__ *.pyc *.pyo .temp logs scripts\dist
rem                 (add --with-temp to keep .temp and logs)
rem  Usage: double-click this file, or run  pack_full.bat --check  for a dry run
rem ============================================================
set "PACK_MODE=full"
call "%~dp0_pack_core.bat" %*
set "RC=%ERRORLEVEL%"

rem  No arguments (double-click) keeps the window open; with arguments it returns directly
if "%~1"=="" pause

endlocal & exit /b %RC%