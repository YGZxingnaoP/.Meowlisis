@echo off
rem ===========================================================================
rem  Stop MeowLLM + the lab (double-click friendly wrapper).
rem
rem  Use this whenever you see the stub reply instead of your model:
rem  it means an old instance is still squatting port 18100.
rem
rem  Falls back to bin\stop.bat so it works before and after the folders are
rem  reorganised into .test\.
rem ===========================================================================
setlocal EnableExtensions
set "BINDIR=%~dp0.test\bin"
if not exist "%BINDIR%\stop.bat" set "BINDIR=%~dp0bin"
endlocal & set "BINDIR=%BINDIR%"
call "%BINDIR%\stop.bat" %*
exit /b %errorlevel%
