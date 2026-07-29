@echo off
chcp 65001
cd /d "%~dp0"

:: 启动新版 API 服务（前台运行，关闭窗口则服务停止）
set PATH=%~dp0FFmpeg\bin;%PATH%
..\runtime\python.exe api_v2.py -c tts_infer.yaml -a 127.0.0.1 -p 9880

pause