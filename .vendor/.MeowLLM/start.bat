@echo off
rem ===========================================================================
rem  MeowLLM launcher (double-click friendly wrapper)
rem
rem  The real launcher lives in .test\bin\start.bat. This wrapper stays at the
rem  module root so you can double-click it without digging into subfolders.
rem
rem  It falls back to bin\start.bat so the module keeps working whether or not
rem  the folders have been reorganised into .test\ yet.
rem
rem    start.bat                 start with engine.kind from config.yml
rem    start.bat check           config + safety-gate self check only
rem    start.bat llamacpp        force llama.cpp engine
rem    start.bat bg              start detached (minimized window)
rem ===========================================================================
setlocal EnableExtensions
set "BINDIR=%~dp0.test\bin"
if not exist "%BINDIR%\start.bat" set "BINDIR=%~dp0bin"
endlocal & set "BINDIR=%BINDIR%"
call "%BINDIR%\start.bat" %*
exit /b %errorlevel%
