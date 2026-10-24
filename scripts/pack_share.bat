@echo off
chcp 65001 >nul
setlocal EnableExtensions

rem ============================================================
rem  Share package (includes runtime; drops secrets, configs, runtime data and personal content)
rem  Output: scripts\dist\Meowlisis_share.zip and a .sha256 sidecar
rem  Notes:
rem    * root config.yml is NOT packed; the sanitized template config.example.yml is included
rem      (on first start func\config\default_config.py copies it to config.yml)
rem    * plugin config.yml files hold sk- keys, so they are excluded (plugins fall back to defaults)
rem    * .vendor\.cam: only cert and mode.txt are excluded; phone module code stays (cert is regenerated)
rem  Usage: double-click this file, or run  pack_share.bat --check  for a dry run
rem ============================================================

set "PACK_MODE=share"
call "%~dp0_pack_core.bat" %*
set "RC=%ERRORLEVEL%"

rem  No arguments (double-click) keeps the window open; with arguments it returns directly
if "%~1"=="" pause

endlocal & exit /b %RC%