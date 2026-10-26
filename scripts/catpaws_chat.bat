@echo off
setlocal
cd /d "%~dp0.."
set "PY=%CD%\runtime\311\python.exe"
netstat -ano | findstr /R /C:":18110 .*LISTENING" >nul
if not errorlevel 1 goto chat
echo [1/2] starting CatPaws service on 127.0.0.1:18110 ...
pushd "%CD%\.vendor\.CatPaws"
start "CatPaws Server" /min "%PY%" "src\cw\server.py"
popd
ping -n 7 127.0.0.1 >nul
:chat
echo [2/2] chat mode, type q to quit
"%PY%" "%CD%\scripts\catpaws_chain_test.py" chat %*
endlocal
