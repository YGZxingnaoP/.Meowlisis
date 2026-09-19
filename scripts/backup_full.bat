@echo off
setlocal
rem =====================================================================
rem  FULL BACKUP  D:\.Meowlisis  ->  .zip
rem  Ignore ONLY : __pycache__ , *.pyc , .git , .vs , todolist.md
rem  IMPORTANT  : WinRAR masks NEED WILDCARDS -> use -x*\dir\ and -x*name
rem               a bare name like -x.git / -x__pycache__ does NOTHING
rem  NOTE       : Rar.exe cannot build .zip, so we use WinRAR.exe (-afzip)
rem =====================================================================

set "RAR=D:\WinRAR\WinRAR.exe"
set "SRCDIR=D:\"
set "SRCNAME=.Meowlisis"

rem ---- date stamp YYYYMMDD (Chinese Windows %date% = 2026/09/14 ...) ----
set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%"
set "OUT=D:\Meowlisis_%STAMP%_all.zip"

if not exist "%RAR%" (
  echo [ERROR] WinRAR.exe not found: %RAR%
  pause
  exit /b 1
)

cd /d "%SRCDIR%"
if exist "%OUT%" del /f /q "%OUT%"

echo =====================================================================
echo  FULL BACKUP (zip)
echo   source : %SRCDIR%%SRCNAME%
echo   output : %OUT%
echo =====================================================================
echo.

rem ---- do NOT follow ComfyUI junctions (they point back to .ComfyNode\models /
rem      .ComfyNode\output; following them stores ~10.5GB of models TWICE) ----
"%RAR%" a -afzip -r -m0 -o+ -x*\__pycache__\ -x*.pyc -x*\.git\ -x*\.vs\ -x*todolist.md -x*\.ComfyNode\ComfyUI\models\ -x*\.ComfyNode\ComfyUI\output\ "%OUT%" "%SRCNAME%"

echo.
echo Done: %OUT%
pause
