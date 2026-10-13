@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  完整项目打包（含运行环境 runtime .vendor/.ComfyNode .vendor/.Sovits .vendor/.SenseVoice .vendor/.RVC）
rem  只排除开发文件：.git  .vs  .idea  __pycache__  *.pyc  *.pyo
rem  产物：scripts\dist\Meowlisis_full.zip（同名旧包会先删掉）
rem  用法：双击本文件，或在命令行执行 pack_full.bat
rem ============================================================

rem WinRAR 路径（D 盘那个）
set "RAR=D:\WinRAR\WinRAR.exe"
rem 压缩级别：-m1 最快，-m3 折中，-m5 最小
set "MODE=-m3"

set "ROOT=%~dp0.."
set "OUT=%~dp0dist"
set "NAME=Meowlisis_full"

if not exist "%RAR%" (
  echo [错误] 找不到 WinRAR：%RAR%
  echo         请改本脚本里的 RAR 变量
  pause
  exit /b 1
)
if not exist "%OUT%" mkdir "%OUT%"
if exist "%OUT%\%NAME%.zip" del /q "%OUT%\%NAME%.zip"

pushd "%ROOT%"

for %%D in (runtime .vendor/.ComfyNode .vendor/.Sovits .vendor/.SenseVoice .vendor/.RVC) do (
  if not exist "%%D" echo [警告] 缺环境目录：%%D
)

echo 正在打包完整项目（含环境），包很大，要等一会儿...
rem 想让它缩到托盘后台跑，就在下面这行加 -ibck（那样脚本不等它结束）
"%RAR%" a -afzip -r %MODE% -y ^
 -x"*.pyc" -x"*.pyo" ^
 -x"__pycache__\*" -x"*\__pycache__\*" ^
 -x".git\*" -x".vs\*" -x".idea\*" ^
 -x"scripts\dist\*" ^
 "%OUT%\%NAME%.zip" "*"

if errorlevel 1 (
  echo [失败] 打包没成功，看 WinRAR 窗口里的报错
) else (
  for %%F in ("%OUT%\%NAME%.zip") do echo [完成] %%~fF  大小 %%~zF 字节
)

popd
pause
