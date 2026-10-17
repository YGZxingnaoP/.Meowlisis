@echo off
rem Install bitsandbytes into the bundled python runtime.
rem Run this by double-click. It needs your normal user rights (the agent
rem sandbox cannot write into D:\.Meowlisis\runtime, which is why the install
rem has to be done by you).
setlocal
set "PY=%~dp0..\..\..\runtime\311\python.exe"
if not exist "%PY%" set "PY=%MEOWLLM_PYTHON%"
if not exist "%PY%" set "PY=python"
set "WHL=%~dp0..\bitsandbytes-0.47.0-py3-none-win_amd64.whl"

echo [1/3] python = %PY%
if not exist "%PY%" echo   ERROR: python not found & goto :end
echo [2/3] wheel  = %WHL%
if not exist "%WHL%" echo   ERROR: wheel not found & goto :end

echo.
echo [3/3] installing ...
"%PY%" -m pip install --no-user --no-deps "%WHL%"
echo.
echo --- verify ---
"%PY%" -c "import bitsandbytes as bnb; print('bitsandbytes', bnb.__version__)"
"%PY%" -c "from transformers import BitsAndBytesConfig; print('BitsAndBytesConfig OK')"

:end
echo.
echo Done. Press any key to close.
pause >nul
