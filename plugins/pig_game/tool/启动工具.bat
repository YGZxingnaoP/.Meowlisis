@echo off
chcp 65001 >nul
title 猪种配置工具
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY goto nopy

%PY% -c "import sys;raise SystemExit(0 if sys.version_info>=(3,6) else 1)" >nul 2>nul
if errorlevel 1 goto nopy

echo.
echo  猪种配置工具启动中，浏览器会自动打开...
echo  关掉本窗口 = 关闭工具。
echo.
%PY% "%~dp0server.py" %*
if errorlevel 1 pause
exit /b 0

:nopy
echo.
echo  [x] 没找到可用的 Python 3。
echo      装好 Python 后记得勾选 "Add python.exe to PATH"，再双击本文件。
echo.
pause
exit /b 1
