@echo off
setlocal
rem Stop every child process started by the launcher (tunnel / runwda).
set "PS=pwsh"
where pwsh >nul 2>nul || set "PS=powershell"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
