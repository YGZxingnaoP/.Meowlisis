@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  分享整合包（同样含运行环境 runtime .vendor/.ComfyNode .vendor/.Sovits .vendor/.SenseVoice .vendor/.RVC）
rem  在开发文件之外，再去掉密钥、配置、运行数据和角色的私人内容
rem  排除清单见下面那段，想留下哪一项就把对应那行 -x 删掉
rem  注意：config.yml 被排除，包里带的是脱敏模板 config.example.yml；
rem        对方第一次启动时程序会拿它生成 config.yml（见 func\config\default_config.py）
rem  产物：scripts\dist\Meowlisis_share.zip（同名旧包会先删掉）
rem  用法：双击本文件，或在命令行执行 pack_share.bat
rem ============================================================

rem WinRAR 路径（D 盘那个）
set "RAR=D:\WinRAR\WinRAR.exe"
rem 压缩级别：-m1 最快，-m3 折中，-m5 最小
set "MODE=-m5"

set "ROOT=%~dp0.."
set "OUT=%~dp0dist"
set "NAME=Meowlisis_share"

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

echo 正在打包分享包（含环境，已去掉密钥和私人数据），要等一会儿...
rem 想让它缩到托盘后台跑，就在下面这行加 -ibck（那样脚本不等它结束）
"%RAR%" a -afzip -r %MODE% -y ^
 -x"*.pyc" -x"*.pyo" ^
 -x"__pycache__\*" -x"*\__pycache__\*" ^
 -x".git\*" -x".vs\*" -x".idea\*" ^
 -x"config.yml" ^
 -x".temp\*" ^
 -x"logs\*" ^
 -x".vendor/.DataBase\*" ^
 -x".vendor/.NapCat\*" ^
 -x".vendor/.NeteaseMusic\*" ^
 -x".vendor/.cam\*" ^
 -x".vendor/.desktopet\config.json" -x".vendor/.desktopet\.run.log" ^
 -x"character\memory\*" ^
 -x"character\abstract_memory\*" ^
 -x"character\info\users_info\*" ^
 -x"character\info\values\*" ^
 -x"character\backlog\*" ^
 -x"character\turtle_soup\*" ^
 -x"character\rewards\*" ^
 -x"character\shared_videos\*" ^
 -x"character\audio\*" ^
 -x"character\songs\*" ^
 -x"character\paints\*" ^
 -x"character\svg_paints\*" ^
 -x"character\books\*" ^
 -x"character\catfiles\*" ^
 -x"scripts\backup\*" ^
 -x"scripts\dist\*" ^
 "%OUT%\%NAME%.zip" "*"

if errorlevel 1 (
  echo [失败] 打包没成功，看 WinRAR 窗口里的报错
) else (
  for %%F in ("%OUT%\%NAME%.zip") do echo [完成] %%~fF  大小 %%~zF 字节
)

popd
pause
