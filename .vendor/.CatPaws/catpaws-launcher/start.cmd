@echo off
setlocal
rem Start the CatPaws device-ready daemon (Ctrl+C to stop).
rem Chinese text lives only in the .ps1 files (UTF-8 BOM); .cmd must stay ASCII.
set "PS=pwsh"
where pwsh >nul 2>nul || set "PS=powershell"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher.ps1" %*
if errorlevel 1 pause
