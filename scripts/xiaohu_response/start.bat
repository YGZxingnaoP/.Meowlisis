@echo off
chcp 65001 >nul
title 筱狐必回机器人
cd /d D:\.Meowlisis

rem 优先使用主项目自带 runtime 解释器（依赖齐全：websockets / openai 等）
if exist "runtime\python.exe" (
    runtime\python.exe scripts\xiaohu_response\main.py
    goto end
)

rem 兜底：系统 python
where python >nul 2>nul
if %errorlevel%==0 (
    python scripts\xiaohu_response\main.py
) else (
    py -3 scripts\xiaohu_response\main.py
)

:end
pause
