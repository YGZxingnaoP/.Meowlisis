#requires -Version 5.1
# 停止拉起程序启动的所有子进程（tunnel / runwda / launcher 自身）
$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$runDir = Join-Path $root 'run'
if (-not (Test-Path -LiteralPath $runDir)) { New-Item -ItemType Directory -Path $runDir -Force | Out-Null }
$statePath = Join-Path $runDir 'state.json'

$targets = New-Object System.Collections.ArrayList
if (Test-Path -LiteralPath $statePath) {
  try {
    $o = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($name in 'launcher_pid', 'tunnel_pid', 'wda_pid', 'forward_pid') {
      $v = $o.$name
      if ($v -and [int]$v -gt 0) { [void]$targets.Add([int]$v) }
    }
  } catch { Write-Host "[stop] state.json 解析失败：$($_.Exception.Message)" -ForegroundColor Yellow }
}

# 兜底：本目录下的 ios.exe 进程
Get-Process -Name ios -ErrorAction SilentlyContinue | ForEach-Object {
  try {
    if ($_.Path -and ($_.Path -like "$root*")) { [void]$targets.Add($_.Id) }
  } catch { [void]$targets.Add($_.Id) }
}

$killed = 0
foreach ($procId in ($targets | Sort-Object -Unique)) {
  try {
    Stop-Process -Id $procId -Force -ErrorAction Stop
    Write-Host "[stop] 已结束 PID $procId" -ForegroundColor Yellow
    $killed++
  } catch { }
}

if ($killed -eq 0) { Write-Host '[stop] 没有需要结束的进程' -ForegroundColor Gray }
else { Write-Host "[stop] 共结束 $killed 个进程" -ForegroundColor Green }

Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
