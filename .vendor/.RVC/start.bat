@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0..\..\runtime\311\python.exe" cover_server.py
pause
