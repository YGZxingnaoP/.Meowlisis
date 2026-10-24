@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
rem Must be captured BEFORE the argument loop: SHIFT also moves %0, which breaks %~dp0 afterwards
set "SCRIPT_DIR=%~dp0"

rem ============================================================
rem  Pack core (shared by pack_full.bat / pack_share.bat; do not run this file directly)
rem  PACK_MODE = full | share  (set by the wrapper)
rem
rem  Options:
rem     --check     dry run: sizes, free space, environment; writes nothing
rem     --verify    test the archive after packing (reads the whole file; slowest, safest)
rem     --nohash    skip SHA256 (saves one full read)
rem  (pausing is handled by the wrapper: only when called with no arguments)
rem     --with-temp keep .temp and logs in the full pack (excluded by default)
rem
rem  Behaviour:
rem     * writes dist\xxx.tmp first and renames to .zip only on success: no half archive, backup kept
rem     * WinRAR exit code 0=ok 1=some files locked/changed (archive created) >=2=real failure
rem     * after packing: content check (required present, excluded absent) then a .sha256 sidecar
rem ============================================================

set "DID_CHECK=0"
set "DO_VERIFY=0"
set "DO_HASH=1"
set "WITH_TEMP=0"
:argloop
if "%~1"=="" goto :argdone
if /i "%~1"=="--check"     set "DID_CHECK=1"
if /i "%~1"=="--verify"    set "DO_VERIFY=1"
if /i "%~1"=="--nohash"    set "DO_HASH=0"
if /i "%~1"=="--with-temp" set "WITH_TEMP=1"
shift
goto :argloop
:argdone


rem Compression level: -m1 fastest, -m3 balanced, -m5 smallest, -m0 store only (fastest, largest)
rem 47% of this project is already-compressed models/weights/wav, so -m1 is the default
set "MODE=-m1"

rem ---------- Locate the project root by the api.py marker (works from any launcher) ----------
rem Note: inside blocks use !CD! (delayed); %CD% is expanded when the block is parsed.
set "ROOT="
if defined PACK_ROOT if exist "%PACK_ROOT%\api.py" set "ROOT=%PACK_ROOT%"
if not defined ROOT (
  pushd "%SCRIPT_DIR%.." >nul 2>nul
  if exist "api.py" set "ROOT=!CD!"
  popd
)
if not defined ROOT (
  pushd "%CD%" >nul 2>nul
  if exist "api.py" set "ROOT=!CD!"
  popd
)
if not defined ROOT (
  pushd "%CD%\.." >nul 2>nul
  if exist "api.py" set "ROOT=!CD!"
  popd
)
if not defined ROOT (
  echo [ERROR] Cannot locate the project root - no api.py found.
  echo         Run this from inside the project, or set PACK_ROOT=^<project root^> first.
  exit /b 1
)
set "OUT=%ROOT%\scripts\dist"
set "HELPER=%ROOT%\scripts\_pack_helper.ps1"
set "PS=powershell -NoProfile -ExecutionPolicy Bypass -File"

if /i "%PACK_MODE%"=="full" (
  set "NAME=Meowlisis_full"
  set "LABEL=full project"
) else if /i "%PACK_MODE%"=="share" (
  set "NAME=Meowlisis_share"
  set "LABEL=share package"
) else (
  echo [ERROR] PACK_MODE must be full or share - run pack_full.bat or pack_share.bat
  pause
  goto :fail
)

rem ---------- Exclude list ----------
rem WinRAR -x: a mask WITHOUT wildcards matches only the archiving root; wildcards make it recursive.
rem So -x"config.yml" excludes only the root one, not .vendor\.MeowLLM\config.yml or plugin configs.
set "EXCOMMON=-x"*.pyc" -x"*.pyo" -x"__pycache__\*" -x".git\*" -x".vs\*" -x".idea\*" -x".github\*" -x"scripts\dist\*" -x"scripts\backup\*""

if /i "%PACK_MODE%"=="full" (
  set "EXCLUSIVE="
  if "%WITH_TEMP%"=="0" set "EXCLUSIVE=-x".temp\*" -x"logs\*""
) else (
  rem share package: drop secrets, configs, runtime data and personal content
set "EXCLUSIVE=-x"config.yml" -x"config.example.yml" -x".temp\*" -x"logs\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x".vendor\.DataBase\*" -x".vendor\.NapCat\*" -x".vendor\.NeteaseMusic\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x".vendor\.cam\cert\*" -x".vendor\.cam\mode.txt""
  set "EXCLUSIVE=!EXCLUSIVE! -x".vendor\.desktopet\config.json" -x".vendor\.desktopet\.run.log""
  rem plugin config.yml files hold sk- keys (plugins fall back to built-in defaults)
  set "EXCLUSIVE=!EXCLUSIVE! -x"plugins\*\config.yml""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\memory\*" -x"character\abstract_memory\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\info\users_info\*" -x"character\info\values\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\backlog\*" -x"character\turtle_soup\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\rewards\*" -x"character\shared_videos\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\audio\*" -x"character\songs\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\paints\*" -x"character\svg_paints\*""
  set "EXCLUSIVE=!EXCLUSIVE! -x"character\books\*" -x"character\catfiles\*""
)
set "EXCLUDES=%EXCOMMON% %EXCLUSIVE%"

rem ---------- Find WinRAR ----------
rem To use another path: set PACK_RAR=X:\path\WinRAR.exe before running.
set "RAR="
if defined PACK_RAR if exist "%PACK_RAR%" set "RAR=%PACK_RAR%"
for %%P in ("D:\WinRAR\WinRAR.exe" "%ProgramFiles%\WinRAR\WinRAR.exe") do (
  if not defined RAR if exist "%%~P" set "RAR=%%~P"
)
if not defined RAR if exist "%ProgramFiles(x86)%\WinRAR\WinRAR.exe" set "RAR=%ProgramFiles(x86)%\WinRAR\WinRAR.exe"
if not defined RAR (
  echo [ERROR] WinRAR.exe not found.
  echo         Looked in: D:\WinRAR, Program Files, Program Files x86, PATH
  echo         Install it, or set PACK_RAR to your WinRAR.exe path.
  goto :fail
)
for %%D in ("%RAR%") do set "RARDIR=%%~dpD"
set "RARCLI=%RARDIR%Rar.exe"
if not exist "%RARCLI%" set "RARCLI=%RAR%"

echo ============================================================
echo  %LABEL% pack        mode %PACK_MODE%
echo  source : %ROOT%
echo  output : %OUT%\%NAME%.zip
echo  level  : %MODE%
echo ============================================================

pushd "%ROOT%" || (
  echo [ERROR] Cannot enter %ROOT%
  goto :fail
)

echo.
echo [1/5] Size and free space...
for /f "usebackq tokens=1,2" %%A in (`%PS% "%HELPER%" space -Root "%ROOT%"`) do (
  set "SRC_MB=%%A"
  set "FREE_MB=%%B"
)
if not defined SRC_MB (
  echo [ERROR] Size scan failed - the PowerShell helper did not run.
  popd
  goto :fail
)
set /a SRC_GB=SRC_MB/1024
set /a FREE_GB=FREE_MB/1024
echo         source about %SRC_GB% GB - %SRC_MB% MB, free on target drive %FREE_GB% GB - %FREE_MB% MB
if %FREE_MB% EQU 0 (
  echo         [note] free space unknown, skipping the check; WinRAR fails only if the disk is full
) else if %FREE_MB% LSS 1024 (
  echo [ERROR] Less than 1 GB free, aborting.
  popd
  goto :fail
)

echo.
echo [2/5] Environment and bootstrap files...
for %%D in (runtime .vendor\.ComfyNode .vendor\.Sovits .vendor\.SenseVoice .vendor\.RVC) do (
  if not exist "%%D" echo         [WARN] missing environment folder: %%D
)
if /i "%PACK_MODE%"=="share" (
  rem share package carries no config at all: default_config.py writes a minimal
  rem config.yml on first start and everything else falls back to code defaults.
  if exist "config.example.yml" echo         config.example.yml will NOT be packed
)

echo.
echo [3/5] Checking for running processes...
set "RUNNING="
for %%N in (python.exe mpv.exe NapCatWinBootMain.exe) do (
  tasklist /FI "IMAGENAME eq %%N" 2>nul | find /i "%%N" >nul && set "RUNNING=!RUNNING! %%N"
)
if defined RUNNING (
  echo         [WARN] still running: !RUNNING!
  if "%DID_CHECK%"=="0" (
    echo                Files in use may be locked or half-written; close the app first if possible.
    echo                Continuing in 8 seconds, press Ctrl+C to abort...
    timeout /t 8 >nul 2>nul
  )
) else (
  echo         no related processes running
)

if "%DID_CHECK%"=="1" (
  echo.
  echo [check done] nothing was written.
  echo              Real run: drop --check and run again.
  echo              Excludes: %EXCLUDES%
  popd
  goto :done
)

echo.
echo [4/5] Packing now - large archive, do not close this window...
echo         time %DATE% %TIME%
if not exist "%OUT%" mkdir "%OUT%"
if not exist "%OUT%" (
  echo [ERROR] Cannot create output folder %OUT%
  popd
  goto :fail
)
if exist "%OUT%\%NAME%.tmp" del /q "%OUT%\%NAME%.tmp"

call "%RAR%" a -afzip -r %MODE% -y %EXCLUDES% "%OUT%\%NAME%.tmp" "*"
set "RC=%ERRORLEVEL%"

if %RC% GEQ 2 (
  echo.
  echo [FAILED] WinRAR returned %RC%
  echo        2=fatal 3=CRC 5=write error 6=cannot open 7=bad command line 9=cannot create 10=nothing to pack
  if exist "%OUT%\%NAME%.tmp" del /q "%OUT%\%NAME%.tmp"
  echo        Previous backup untouched: %OUT%\%NAME%.zip
  popd
  goto :fail
)
if %RC% EQU 1 (
  echo.
  echo [NOTE] WinRAR returned 1: some files were locked or changed; the archive exists but those files may be incomplete.
)

if not exist "%OUT%\%NAME%.tmp" (
  echo [FAILED] The temporary archive was not created.
  popd
  goto :fail
)
move /y "%OUT%\%NAME%.tmp" "%OUT%\%NAME%.zip" >nul
if not exist "%OUT%\%NAME%.zip" (
  echo [FAILED] Rename failed; the temporary archive is kept at %OUT%\%NAME%.tmp
  popd
  goto :fail
)

echo.
echo [5/5] Verifying...
%PS% "%HELPER%" verify -Zip "%OUT%\%NAME%.zip" -Mode %PACK_MODE%
if errorlevel 1 (
  echo         [WARN] Content check reported problems - see MISS / BAD above; the archive itself exists.
) else (
  echo         content check passed
)

if "%DO_VERIFY%"=="1" (
  echo         testing the whole archive - reads everything, slow...
  call "%RARCLI%" t -y "%OUT%\%NAME%.zip" >nul 2>nul
  if errorlevel 1 (
    echo         [WARN] archive test reported errors
  ) else (
    echo         archive test passed
  )
)

if "%DO_HASH%"=="1" (
  echo         computing SHA256...
  set "HASH="
  for /f "usebackq delims=" %%H in (`%PS% "%HELPER%" hash -Path "%OUT%\%NAME%.zip"`) do set "HASH=%%H"
  if defined HASH (
    > "%OUT%\%NAME%.zip.sha256" echo !HASH!  %NAME%.zip
    echo         SHA256 !HASH!
    echo         written to %OUT%\%NAME%.zip.sha256
  ) else (
    echo         [WARN] SHA256 failed - the archive itself is fine
  )
)

for %%F in ("%OUT%\%NAME%.zip") do set "SZ_MB=%%~zF"
set /a SZ_MB=SZ_MB/1048576
set /a SZ_GB=SZ_MB/1024
echo.
echo ============================================================
echo  [DONE] %OUT%\%NAME%.zip
echo         size %SZ_MB% MB - about %SZ_GB% GB
echo         time %DATE% %TIME%
echo ============================================================

popd

:done
endlocal
exit /b 0

:fail
endlocal
exit /b 1