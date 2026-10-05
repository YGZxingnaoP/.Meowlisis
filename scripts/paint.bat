@echo off
chcp 65001 >nul
title Meowlisis 绘画脚本（生产链路 / Pro）
cd /d "%~dp0.."
"%~dp0..\runtime\python.exe" "%~dp0paint.py"
echo.
pause
