@echo off
setlocal
rem =====================================================================
rem  SHAREABLE PACK  D:\.Meowlisis  ->  .zip   (no private data / no keys)
rem
rem  IMPORTANT : WinRAR masks NEED WILDCARDS -> use -x*\dir\ and -x*name
rem              a bare name like -x.git / -xconfig.yml does NOTHING
rem  exclusions below (ALL in one pass, because 'a' only adds):
rem    caches      : __pycache__ , *.pyc , .git , .vs , todolist.md
rem    spec        : character(data) , .temp , config secrets , *.bak
rem    audit       : .NapCat(QQ login) , .DataBase , logs , *.log , ncm cookie
rem  role prompts are put back in pass 2
rem  NOTE      : Rar.exe cannot build .zip, so we use WinRAR.exe (-afzip)
rem =====================================================================

set "RAR=D:\WinRAR\WinRAR.exe"
set "SRCDIR=D:\"
set "SRCNAME=.Meowlisis"

rem ---- date stamp YYYYMMDD (Chinese Windows %date% = 2026/09/14 ...) ----
set "STAMP=%date:~0,4%%date:~5,2%%date:~8,2%"
set "OUT=D:\Meowlisis_%STAMP%_clean.zip"

if not exist "%RAR%" (
  echo [ERROR] WinRAR.exe not found: %RAR%
  pause
  exit /b 1
)

cd /d "%SRCDIR%"
if exist "%OUT%" del /f /q "%OUT%"

echo =====================================================================
echo  SHAREABLE PACK (zip)
echo   source : %SRCDIR%%SRCNAME%
echo   output : %OUT%
echo =====================================================================
echo.

echo [1/2] packing tree ...
"%RAR%" a -afzip -r -m0 -o+ -x*\__pycache__\ -x*.pyc -x*\.git\ -x*\.vs\ -x*todolist.md -x*\character\ -x*\.temp\ -x*config.yml* -x*.bak* -x*\.NapCat\ -x*\.DataBase\ -x*\logs\ -x*.log -x*ncm_cookie.json -x*\.ComfyNode\ComfyUI\models\ -x*\.ComfyNode\ComfyUI\output\ "%OUT%" "%SRCNAME%"

echo.
echo [2/2] re-adding role prompts ...
"%RAR%" a -afzip -m0 -o+ "%OUT%" "%SRCNAME%\character\info\character_prompt\prompt.json" "%SRCNAME%\character\front\prompt.json" "%SRCNAME%\character\front\armor-piercing-prompt.json"

echo.
echo Done: %OUT%
pause
