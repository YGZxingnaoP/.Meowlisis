@echo off
chcp 65001 >nul
title NapCat diag (uin 3781465760)
cd /d "%~dp0"

REM Elevate if not admin: NapCat injection needs administrator.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [diag] requesting administrator...
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)

set "SHELLDIR=%~dp0..\..\.vendor\.NapCat\NapCat.Shell"
if not exist "%SHELLDIR%\NapCatWinBootMain.exe" (
    echo [diag] ERROR: not found: %SHELLDIR%\NapCatWinBootMain.exe
    pause
    exit /b 1
)

pushd "%SHELLDIR%"
echo ==============================================================
echo  [diag] cwd  : %CD%
echo  [diag] run  : NapCatWinBootMain.exe 3781465760
echo  [diag] note : -q uses the REAL uin instead of the 10086 placeholder
echo ==============================================================
echo.

.\NapCatWinBootMain.exe 3781465760

echo.
echo ==============================================================
echo  [diag] NapCat exited at %DATE% %TIME%
echo  [diag] keep this window open so the full log stays available
echo ==============================================================
popd
pause
