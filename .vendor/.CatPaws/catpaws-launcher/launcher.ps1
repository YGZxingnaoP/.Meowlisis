#requires -Version 5.1
<#
.SYNOPSIS
  CatPaws 设备就绪管理器：自动起隧道、自动拉起 WDA、自动恢复。

.DESCRIPTION
  iOS 上 WDA 是 XCTest runner，必须由 testmanagerd 通过外部控制端拉起，
  且 iOS 17+ 需要一条 USB 隧道。本脚本把这三步串起来并守护：

    1) ios.exe list              → 确认设备在 USB 上
    2) ios.exe tunnel start --userspace   → 起隧道（不需要管理员）
    3) ios.exe apps              → 动态查已安装的 CatPaw runner id
                                   （签名器会给 id 加后缀，每次重签可能变，不能写死）
    4) ios.exe runwda ...        → 拉起 WDA，--log-output 落盘
    5) HTTP 轮询 /cw/v1/ping      → 判定就绪

  任何一环失败会等待并重试；拔线后自动回到"等待设备"，插回来自动恢复。

.PARAMETER Once
  只跑一轮就退出（用于排错），不进入守护循环。

.PARAMETER RefreshId
  忽略 config.json 里缓存的 runner_id，重新从设备上查一次。
#>
[CmdletBinding()]
param(
  [switch]$Once,
  [switch]$RefreshId
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runDir = Join-Path $root 'run'
if (-not (Test-Path -LiteralPath $runDir)) { New-Item -ItemType Directory -Path $runDir -Force | Out-Null }
$ios = Join-Path $root 'ios.exe'
$cfgPath = Join-Path $root 'config.json'
$logPath = Join-Path $runDir 'launcher.log'
$statePath = Join-Path $runDir 'state.json'

if (-not (Test-Path -LiteralPath $ios)) {
  Write-Host "[FATAL] 找不到 ios.exe：$ios" -ForegroundColor Red
  Write-Host "        请把 go-ios 的 ios.exe 放到本目录。" -ForegroundColor Yellow
  exit 1
}

function Write-Log {
  param([string]$Message, [string]$Color = 'Gray')
  $line = ('{0} {1}' -f (Get-Date).ToString('HH:mm:ss'), $Message)
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
  Write-Host $line -ForegroundColor $Color
}

# ---------- 配置 ----------
$defaults = @{
  runner_id          = ''      # 留空 = 每次自动查
  device_ip          = ''      # 可选：手机局域网 IP，填了就额外用 Wi-Fi 探活
  wda_port           = 8100
  health_interval_s  = 3
  tunnel_wait_s      = 25
  max_restarts       = 50
}
$cfg = $defaults.Clone()
if (Test-Path -LiteralPath $cfgPath) {
  try {
    $loaded = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($p in $loaded.PSObject.Properties) { if ($cfg.ContainsKey($p.Name)) { $cfg[$p.Name] = $p.Value } }
  } catch {
    Write-Log "[WARN] config.json 解析失败，用默认值：$($_.Exception.Message)" 'Yellow'
  }
} else {
  ($cfg | ConvertTo-Json) | Set-Content -LiteralPath $cfgPath -Encoding UTF8
  Write-Log "[INIT] 已生成 config.json（runner_id 留空 = 自动探测）"
}
if ($RefreshId) { $cfg['runner_id'] = '' }

# ---------- 子进程工具 ----------
function Invoke-Ios {
  param([string[]]$Arguments, [int]$TimeoutSec = 90)
  $out = [System.IO.Path]::GetTempFileName()
  $err = [System.IO.Path]::GetTempFileName()
  try {
    $p = Start-Process -FilePath $ios -ArgumentList $Arguments -WorkingDirectory $runDir -NoNewWindow -PassThru `
          -RedirectStandardOutput $out -RedirectStandardError $err
    if (-not $p.WaitForExit($TimeoutSec * 1000)) {
      try { $p.Kill() } catch { }
      return ''
    }
    if (Test-Path -LiteralPath $out) { return (Get-Content -LiteralPath $out -Raw -Encoding UTF8) }
    return ''
  } finally {
    Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue
  }
}

$script:tunnelProc = $null
$script:wdaProc = $null
$script:forwardProc = $null

function Save-State {
  $obj = @{
    launcher_pid = $PID
    tunnel_pid   = if ($script:tunnelProc -and -not $script:tunnelProc.HasExited) { $script:tunnelProc.Id } else { 0 }
    wda_pid      = if ($script:wdaProc -and -not $script:wdaProc.HasExited) { $script:wdaProc.Id } else { 0 }
    forward_pid  = if ($script:forwardProc -and -not $script:forwardProc.HasExited) { $script:forwardProc.Id } else { 0 }
    updated      = (Get-Date).ToString('s')
  }
  ($obj | ConvertTo-Json) | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Stop-Children {
  foreach ($p in @($script:forwardProc, $script:wdaProc, $script:tunnelProc)) {
    if ($p -and -not $p.HasExited) {
      try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Write-Log "[STOP] 已结束子进程 $($p.Id)" 'Yellow' } catch { }
    }
  }
  Save-State
}

function Get-DeviceList {
  $raw = Invoke-Ios -Arguments @('list')
  if ($raw -match '"deviceList"\s*:\s*\[\s*"([0-9A-Fa-f\-]+)"') { return $Matches[1] }
  return ''
}

function Get-TunnelInfo {
  $raw = Invoke-Ios -Arguments @('tunnel', 'ls')
  if ($raw -match 'rsdPort') { return $raw.Trim() }
  return ''
}

function Ensure-Tunnel {
  if (Get-TunnelInfo) { return $true }
  if ($script:tunnelProc -and -not $script:tunnelProc.HasExited) {
    # 进程在但没有 tunnel info，等一会
    for ($i = 0; $i -lt 8; $i++) { Start-Sleep -Milliseconds 600; if (Get-TunnelInfo) { return $true } }
    return $false
  }
  Write-Log '[TUNNEL] 启动用户态隧道（无需管理员）...' 'Cyan'
  $script:tunnelProc = Start-Process -FilePath $ios -ArgumentList @('tunnel', 'start', '--userspace') -WorkingDirectory $runDir -NoNewWindow -PassThru `
      -RedirectStandardOutput (Join-Path $runDir 'tunnel.out.log') `
      -RedirectStandardError (Join-Path $runDir 'tunnel.err.log')
  Save-State
  $deadline = (Get-Date).AddSeconds($cfg['tunnel_wait_s'])
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 800
    $info = Get-TunnelInfo
    if ($info) {
      Write-Log "[TUNNEL] 就绪：$info" 'Green'
      return $true
    }
    if ($script:tunnelProc.HasExited) {
      Write-Log "[TUNNEL] 进程提前退出（exit=$($script:tunnelProc.ExitCode)），稍后重试" 'Yellow'
      return $false
    }
  }
  Write-Log '[TUNNEL] 等待超时，稍后重试' 'Yellow'
  return $false
}

function Ensure-Forward {
  # runwda 只负责在手机上把 WDA 跑起来；PC 侧要访问 127.0.0.1:8100 还需要端口转发。
  if ($script:forwardProc -and -not $script:forwardProc.HasExited) { return }
  $port = [int]$cfg['wda_port']
  Write-Log "[FWD] 建立端口转发 127.0.0.1:$port -> device:$port" 'Cyan'
  $script:forwardProc = Start-Process -FilePath $ios -ArgumentList @('forward', "$port", "$port") -WorkingDirectory $runDir -NoNewWindow -PassThru `
      -RedirectStandardOutput (Join-Path $runDir 'forward.out.log') `
      -RedirectStandardError (Join-Path $runDir 'forward.err.log')
  Save-State
}

function Get-CatPawsApps {
  # 用 `ios apps --list`：输出是纯文本表 "bundleid 显示名 版本"，比解析 apps 的 JSON 稳得多。
  # （JSON 里有 BUILD_ID/build_id 这种大小写重复键，PowerShell 5.1 的 ConvertFrom-Json 会报错，
  #   而且对象字段顺序不固定，按块切也靠不住。）
  param([string]$Listing)
  $result = New-Object System.Collections.ArrayList
  if (-not $Listing) { return $result }
  foreach ($line in ($Listing -split "`r?`n")) {
    $m = [regex]::Match($line, '^(\S+)\s+(.+?)\s+(\S+)\s*$')
    if (-not $m.Success) { continue }
    $id = $m.Groups[1].Value
    $name = $m.Groups[2].Value
    $ver = $m.Groups[3].Value
    if ($name -notlike 'CatPaws*' -and $id -notlike '*catpaw*') { continue }
    [void]$result.Add([pscustomobject]@{ DisplayName = $name; BundleId = $id; Version = $ver })
  }
  return $result
}

function Get-RunnerId {
  if ($cfg['runner_id']) { return [string]$cfg['runner_id'] }
  $raw = Invoke-Ios -Arguments @('apps', '--list')
  $hits = Get-CatPawsApps -Listing $raw
  if (-not $hits -or $hits.Count -eq 0) { return '' }
  $hit = $hits | Sort-Object { try { [version]($_.Version -replace '[^0-9\.]', '') } catch { [version]'0.0' } } -Descending | Select-Object -First 1
  if (-not $hit -or -not $hit.BundleId) { return '' }
  Write-Log "[APP] 发现 $($hit.DisplayName)（v$($hit.Version)）" 'Green'
  Write-Log "[APP] runner id = $($hit.BundleId)" 'Green'
  return [string]$hit.BundleId
}
function Ensure-Wda {
  param([string]$RunnerId)
  if ($script:wdaProc -and -not $script:wdaProc.HasExited) { return }
  $wdaLog = Join-Path $runDir 'wda.log'
  Write-Log "[WDA] 拉起 runwda（id=$RunnerId）..." 'Cyan'
  # 必须用 --opt=值 的写法，并且给路径加引号：
  # Start-Process 用空格拼参数，本目录含空格（D:\Virtual Machines\...），
  # 拆成 "--log-output" + 两段路径 → docopt 解析失败，runwda 只打 usage 就退出。
  $script:wdaProc = Start-Process -FilePath $ios -ArgumentList @(
      'runwda',
      "--bundleid=$RunnerId",
      "--testrunnerbundleid=$RunnerId",
      '--xctestconfig=WebDriverAgentRunner.xctest',
      "--log-output=`"$wdaLog`""
    ) -WorkingDirectory $runDir -NoNewWindow -PassThru `
      -RedirectStandardOutput (Join-Path $runDir 'runwda.out.log') `
      -RedirectStandardError (Join-Path $runDir 'runwda.err.log')
  Save-State
}

function Test-Wda {
  param([string]$HostName)
  $url = 'http://{0}:{1}/cw/v1/ping' -f $HostName, $cfg['wda_port']
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Get-HealthTargets {
  $list = New-Object System.Collections.ArrayList
  [void]$list.Add('127.0.0.1')
  if ($cfg['device_ip']) { [void]$list.Add([string]$cfg['device_ip']) }
  return $list
}

# ---------- 主流程 ----------
Write-Log '===== CatPaws 设备就绪管理器 =====' 'Cyan'
Write-Log "工作目录：$root"
try { Save-State } catch { }

$restarts = 0
$lastState = ''
$lastStart = (Get-Date).AddMinutes(-5)
$failStreak = 0
$lastNoDevLog = (Get-Date).AddMinutes(-10)
try {
  while ($true) {
    $udid = Get-DeviceList
    if (-not $udid) {
      # 只在状态变化或每 60 秒打一次，避免刷屏
      $now = Get-Date
      if ($lastState -ne 'nodev' -or (($now - $lastNoDevLog).TotalSeconds -ge 60)) {
      Write-Log '[WAIT] USB 上没有设备（拔线/未解锁/未信任），等待中...' 'Yellow'
        $lastNoDevLog = $now
      }
      $lastState = 'nodev'
      Stop-Children
      Start-Sleep -Seconds $cfg['health_interval_s']
      if ($Once) { break }
      continue
    }

    if (-not (Ensure-Tunnel)) {
      Start-Sleep -Seconds $cfg['health_interval_s']
      if ($Once) { break }
      continue
    }

    $runnerId = Get-RunnerId
    if (-not $runnerId) {
      Write-Log '[WAIT] 没找到已安装的 CatPaws（或被重签名改了显示名）；7 天到期需重装' 'Yellow'
      Start-Sleep -Seconds 5
      if ($Once) { break }
      continue
    }

    # 如果 cached runner_id 为空，把探测值写回配置
    if (-not $cfg['runner_id']) {
      $cfg['runner_id'] = $runnerId
      ($cfg | ConvertTo-Json) | Set-Content -LiteralPath $cfgPath -Encoding UTF8
    }

    # 端口转发（只影响 127.0.0.1 探活；用局域网 IP 直连时不是必须，但保持常驻更省事）
    Ensure-Forward

    # —— 先探活，不健康才拉起 ——
    # 实测：go-ios 的 runwda 进程会自己退出，但 WDA(runner) 仍在手机上跑；
    # 如果每轮都无条件重开 runwda，会不断叠进程/会话。所以以 ping 为准。
    $ready = $false
    $readyHost = ''
    foreach ($h in (Get-HealthTargets)) {
      if (Test-Wda -HostName $h) { $ready = $true; $readyHost = $h; break }
    }

    if ($ready) {
      if ($lastState -ne 'ok') {
        Write-Log "[OK] WDA 就绪 → http://${readyHost}:$($cfg['wda_port'])/cw/v1/ping" 'Green'
      }
      $lastState = 'ok'
      $restarts = 0
      $failStreak = 0
    } else {
      # 连续失败 2 次才允许重拉：单次探活超时（WDA 忙/手机锁屏）不该把会话推倒重来，
      # 否则会出现“健康 → 重拉 → 会话被顶掉 → 短暂不可用”的抖动。
      $failStreak++
      $runwdaAlive = ($script:wdaProc -and -not $script:wdaProc.HasExited)
      $sinceLastStart = ((Get-Date) - $lastStart).TotalSeconds
      if ($failStreak -ge 2 -and -not $runwdaAlive -and $sinceLastStart -ge 8) {
        Ensure-Wda -RunnerId $runnerId
        $lastStart = Get-Date
        $lastState = 'starting'
        $failStreak = 0
      }
      $restarts++
      if (($lastState -ne 'wait') -or ($restarts % 5 -eq 0)) {
        Write-Log "[WDA] 尚未就绪（第 $restarts 次，连续失败 $failStreak，runwda alive=$runwdaAlive），继续重试" 'Yellow'
      }
      $lastState = 'wait'
      if ($restarts -ge $cfg['max_restarts']) {
        Write-Log '[WDA] 连续失败过多：检查证书是否过期 / 手机是否锁屏 / wda.log 与 runwda.err.log' 'Red'
        $restarts = 0
      }
    }

    if ($Once) { break }
    Start-Sleep -Seconds $cfg['health_interval_s']
  }
} finally {
  Stop-Children
  Write-Log '===== 已退出，子进程已清理 =====' 'Cyan'
}