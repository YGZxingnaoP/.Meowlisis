@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set PROJECT_DIR=%~dp0
cd /d "%PROJECT_DIR%"

:: Python 解释器路径（使用项目根目录 runtime）
set PYTHON_EXE=%PROJECT_DIR%..\runtime\python.exe
if not exist "%PYTHON_EXE%" (
    echo 错误：未找到 Python 解释器：%PYTHON_EXE%
    echo 请确认项目根目录 runtime 下存在 python.exe
    pause
    exit /b 1
)

:: 模型存放目录（与 download_models.py 保持一致）
set MODELS_DIR=%PROJECT_DIR%localmodels

:: 声纹数据库路径（可自行调整）
set SPEAKER_DB_PATH=%PROJECT_DIR%voicetexture\speaker_db.json

:: 服务端口（默认 10095，可修改）
set PORT=10095

:: 服务端脚本路径
set SERVER_SCRIPT=%PROJECT_DIR%server\sensevoice_server.py

if not exist "%SERVER_SCRIPT%" (
    echo 错误：找不到服务端脚本 %SERVER_SCRIPT%
    echo 请确认 server\sensevoice_server.py 已存在
    pause
    exit /b 1
)

echo ==============================================
echo   SenseVoice WebSocket 服务启动器（CPU 模式）
echo ==============================================
echo 项目目录: %PROJECT_DIR%
echo Python: %PYTHON_EXE%
echo 模型目录: %MODELS_DIR%
echo 声纹数据库: %SPEAKER_DB_PATH%
echo 监听端口: %PORT%
echo 运行设备: CPU（识别速度略慢于 GPU，属正常现象）
echo ==============================================

:: 设置 modelscope 缓存目录（可选）
set MODELSCOPE_CACHE=%MODELS_DIR%

:: 模型路径（使用 localmodels 下的本地模型）
set ASR_MODEL=%MODELS_DIR%\SenseVoiceSmall
set SV_MODEL=%MODELS_DIR%\speech_campplus_sv_zh-cn_16k-common

:: 检查模型是否存在
if not exist "%ASR_MODEL%" (
    echo 错误：SenseVoice 模型不存在：%ASR_MODEL%
    echo 请先运行 download_models.bat 下载模型
    pause
    exit /b 1
)

if not exist "%SV_MODEL%" (
    echo 错误：声纹模型不存在：%SV_MODEL%
    echo 请先运行 download_models.bat 下载模型
    pause
    exit /b 1
)

echo 启动 SenseVoice 服务端...
echo 使用设备: cpu（CPU 模式，不占用显存）
echo.

:: 延迟观测打点文件（供 scripts/sensevoice_latency 监听；目录不存在则自动创建）
set LATENCY_LOG=%PROJECT_DIR%..\scripts\sensevoice_latency\logs\sv_events.log
if not exist "%PROJECT_DIR%..\scripts\sensevoice_latency\logs" mkdir "%PROJECT_DIR%..\scripts\sensevoice_latency\logs"

:: 启动服务（CPU 模式）
"%PYTHON_EXE%" "%SERVER_SCRIPT%" ^
    --host 0.0.0.0 ^
    --port %PORT% ^
    --model_dir "%ASR_MODEL%" ^
    --sv_model "%SV_MODEL%" ^
    --speaker_db_path "%SPEAKER_DB_PATH%" ^
    --device cpu ^
    --ngpu 0 ^
    --ncpu 8 ^
    --worker_threads 4 ^
    --concurrent_asr 4 ^
    --concurrent_sv 2 ^
    --sv_threshold 0.2 ^
    --latency_log "%LATENCY_LOG%"

:: 如果服务异常退出，暂停以显示错误信息
if errorlevel 1 (
    echo.
    echo 服务启动失败，请检查上方错误信息。
    pause
)
