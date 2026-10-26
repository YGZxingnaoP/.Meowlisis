@echo off
setlocal
rem Show device / tunnel / installed CatPaws / WDA health.
set "PS=pwsh"
where pwsh >nul 2>nul || set "PS=powershell"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1"
