@echo off
chcp 65001 >nul
cd /d "%~dp0"
..\..\runtime\311\python.exe server.py --host 127.0.0.1 --port 9881 %*
pause
