@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\runtime\python.exe" cover_server.py
pause
