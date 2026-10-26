#requires -Version 5.1
# 查看设备 / 隧道 / WDA 探活状态
$ErrorActionPreference = 'SilentlyContinue'
$root = $PSScriptRoot
$runDir = Join-Path $root 'run'
if (-not (Test-Path -LiteralPath $runDir)) { New-Item -ItemType Directory -Path $runDir -Force | Out-Null }
$ios = Join-Path $root 'ios.exe'
$cfgPath = Join-Path $root 'config.json'

$port = 8100
$deviceIp = ''
if (Test-Path -LiteralPath $cfgPath) {
  try {
    $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.wda_port) { $port = [int]$cfg.wda_port }
    if ($cfg.device_ip) { $deviceIp = [string]$cfg.device_ip }
  } catch { }
}

Write-Host '=== 设备（USB）===' -ForegroundColor Cyan
$devRaw = & $ios list 2>$null | Out-String
if ($devRaw -match '"deviceList"\s*:\s*\[\s*"([0-9A-Fa-f\-]+)"') {
  Write-Host ("  UDID: " + $Matches[1]) -ForegroundColor Green
} else {
  Write-Host '  未发现设备（拔线 / 未解锁 / 未信任）' -ForegroundColor Yellow
}

Write-Host '=== 隧道 ===' -ForegroundColor Cyan
$tunRaw = & $ios tunnel ls 2>$null | Out-String
if ($tunRaw -match 'rsdPort') { Write-Host ('  ' + $tunRaw.Trim()) -ForegroundColor Green }
else { Write-Host '  无隧道（拉起程序会自动建立）' -ForegroundColor Yellow }

Write-Host '=== 已安装的 CatPaws ===' -ForegroundColor Cyan
$appsRaw = & $ios apps --list 2>$null | Out-String
$found = $false
foreach ($line in ($appsRaw -split "`r?`n")) {
  $m = [regex]::Match($line, '^(\S+)\s+(.+?)\s+(\S+)\s*$')
  if (-not $m.Success) { continue }
  $id = $m.Groups[1].Value; $name = $m.Groups[2].Value; $ver = $m.Groups[3].Value
  if ($name -notlike 'CatPaws*' -and $id -notlike '*catpaw*') { continue }
  $found = $true
  Write-Host ("  {0}  v{1}" -f $name, $ver) -ForegroundColor Green
  Write-Host ("    id: " + $id) -ForegroundColor DarkGray
}
if (-not $found) { Write-Host '  未安装（或显示名不是 CatPaws*）' -ForegroundColor Yellow }
Write-Host '=== WDA 探活 ===' -ForegroundColor Cyan
$urls = @("http://127.0.0.1:$port/cw/v1/ping")
if ($deviceIp) { $urls += "http://${deviceIp}:$port/cw/v1/ping" }
foreach ($u in $urls) {
  try {
    $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    Write-Host ("  {0} -> {1}" -f $u, $r.StatusCode) -ForegroundColor Green
    $body = $r.Content -replace '\s+', ' '
    Write-Host ('    ' + $body.Substring(0, [Math]::Min(160, $body.Length))) -ForegroundColor DarkGray
  } catch {
    Write-Host ("  {0} -> FAIL" -f $u) -ForegroundColor Yellow
  }
}
