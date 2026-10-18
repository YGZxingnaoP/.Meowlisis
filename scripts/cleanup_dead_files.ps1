<#
.SYNOPSIS
    清理 .vendor\.MeowLLM 里的死文件（δ-mem 实验包的历史残留）。

.DESCRIPTION
    **默认只列出会删什么（dry-run），不会删任何东西。**
    要真的删，必须加 -Apply：

        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cleanup_dead_files.ps1            # 只看
        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\cleanup_dead_files.ps1 -Apply     # 真删

    删之前请确认 MeowLLM 已停（.vendor\.MeowLLM\stop.bat），否则 .pt/.safetensors
    可能被进程占着 —— 脚本会如实告诉你哪几个没删掉，重跑即可。
#>
[CmdletBinding()]
param(
    # 真的删（不加就是只看）
    [switch]$Apply,
    # 顺手保留 __pycache__
    [switch]$SkipPycache
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- 定位
$Root    = Split-Path -Parent $PSScriptRoot              # D:\.Meowlisis
$MeowLLM = Join-Path $Root '.vendor\.MeowLLM'
$Labs    = Join-Path $MeowLLM 'labs'
$Train   = Join-Path $Labs 'dmem_train'
$Work    = Join-Path $Train '.dmem_work'

if (-not (Test-Path -LiteralPath (Join-Path $MeowLLM 'config.yml'))) {
    throw "找不到 MeowLLM 模块：$MeowLLM（脚本要放在 <项目根>\scripts\ 下）"
}

# ---------------------------------------------------------------- 目标
$targets = New-Object System.Collections.ArrayList

function Add-Target {
    param([string]$Path, [string]$Why)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $full = [System.IO.Path]::GetFullPath($Path)
    $okMeow = [System.IO.Path]::GetFullPath($MeowLLM)
    $okProj = [System.IO.Path]::GetFullPath($Root)
    $inside = $full.StartsWith($okMeow, [System.StringComparison]::OrdinalIgnoreCase) -or
              $full.StartsWith($okProj, [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $inside) { Write-Warning "跳过（不在项目内）：$full"; return }
    [void]$targets.Add((New-Object psobject -Property @{ Path = $full; Why = $Why }))
}

# ---- 1) labs/experiments：MIRROR 时代的场景数据，server.js 从不读
Add-Target (Join-Path $Labs 'experiments') 'MIRROR 遗留场景，零引用（server.js 不读）'

# ---- 2) 孤儿入口
Add-Target (Join-Path $Train 'start_cloud_engine.py') '零引用，且端口/日志与 cloud_serve.py 冲突'

# ---- 3) 陈旧缓存（内含已删除的 .dmem_work 路径）
Add-Target (Join-Path $Train 'out\dataset.json') '陈旧缓存，指向已删除的 .dmem_work\sft2.jsonl'

# ---- 4) 一次性脚本（全部零引用）
$oneShot = @(
    'batch_adapt.py', 'check_ids.py', 'cloud_fix_model.py', 'cloud_probe.py',
    'cloud_step1.py', 'cloud_step2.py', 'download_outputs.py', 'extract.py',
    'fix_limit.py', 'full_check_and_cloud.py', 'live_test.py', 'patch_panel.py',
    'patch_refresh.py', 'panel_check.js', 'survey_and_refresh.py',
    'survey_callsites.py', 'tail_engine_log.py', 'verify_mem_options.py',
    'wire_remember.py'
)
foreach ($n in $oneShot) { Add-Target (Join-Path $Work $n) '一次性运维脚本，零引用' }

# ---- 5) 一次性 shell（全部零引用）
$oneShotSh = @(
    'build_real.sh', 'diag_run.sh', 'finalize.sh', 'hang_diag.sh', 'net_test.sh',
    'probe.sh', 'run_train.sh', 'start_ui.sh', 'train_bg.sh'
)
foreach ($n in $oneShotSh) { Add-Target (Join-Path $Work $n) '一次性 shell，零引用' }

# ---- 6) 实验产物：dry-run 2 步的废权重（各约 56 MB）
foreach ($n in @('dmout', 'dmout2', 'dmout3', 'ui_out')) {
    Add-Target (Join-Path $Work $n) 'dry-run 废权重（各约 56 MB）'
}

# ---- 7) 浏览器 profile 垃圾
foreach ($n in @('edge_profile', 'edge_profile2')) {
    Add-Target (Join-Path $Work $n) 'Edge profile 垃圾'
}

# ---- 8) 空文件 / PDF 抽取副本
foreach ($n in @('panel_dom.html', 'watch.out', 'watch_probe.txt')) {
    Add-Target (Join-Path $Work $n) '空文件'
}
foreach ($n in @('dmem.txt', 'dmem_full.txt')) {
    Add-Target (Join-Path $Work $n) 'PDF 正文抽取副本（PDF 本体在 docs/）'
}

# ---- 9) 一次性测试产物
foreach ($n in @('realtest', 'userinfo_test', 'backup_test2', 'dmem_states')) {
    Add-Target (Join-Path $Work $n) '一次性测试产物'
}

# ---- 10) 已被 func/meowllm/ 取代的旧文件（全仓零引用）
foreach ($n in @('meowllm_config.py', 'memory_options.py')) {
    Add-Target (Join-Path $Root ('func\llm\' + $n)) '已迁移到 func/meowllm/，全仓零引用'
}

# ---------------------------------------------------------------- 统计
function Get-SizeOf {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) {
        $sum = (Get-ChildItem -LiteralPath $Path -Recurse -Force -File -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum
        if ($null -eq $sum) { return 0 }
        return [double]$sum
    }
    return [double]$item.Length
}

function Format-MB {
    param([double]$Bytes)
    return [string]([math]::Round($Bytes / 1MB, 2))
}

# ---------------------------------------------------------------- 执行
Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
if ($Apply) {
    Write-Host ' 清理死文件（真的删）' -ForegroundColor Yellow
} else {
    Write-Host ' 清理死文件（dry-run：只看，不删）' -ForegroundColor Cyan
}
Write-Host " 模块：$MeowLLM"
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''

$totalBytes = 0.0
$deleted = 0
$failed = New-Object System.Collections.ArrayList

foreach ($t in $targets) {
    $size = Get-SizeOf $t.Path
    $totalBytes += $size
    $mb = Format-MB $size
    $rel = $t.Path.Replace($Root + '\', '')
    if ($Apply) {
        try {
            Remove-Item -LiteralPath $t.Path -Recurse -Force -ErrorAction Stop
            $deleted++
            Write-Host ("  [DEL ] {0,-52} {1,9} MB" -f $rel, $mb) -ForegroundColor Green
        } catch {
            [void]$failed.Add($rel)
            Write-Host ("  [FAIL] {0,-52} {1,9} MB  {2}" -f $rel, $mb, $_.Exception.Message) -ForegroundColor Red
        }
    } else {
        Write-Host ("  [WILL] {0,-52} {1,9} MB  {2}" -f $rel, $mb, $t.Why)
    }
}

# ---- __pycache__
if (-not $SkipPycache) {
    $caches = @(Get-ChildItem -LiteralPath $MeowLLM -Recurse -Directory -Force -Filter '__pycache__' -ErrorAction SilentlyContinue)
    if ($caches.Count -gt 0) {
        $cBytes = 0.0
        foreach ($c in $caches) { $cBytes += Get-SizeOf $c.FullName }
        $totalBytes += $cBytes
        Write-Host ''
        if ($Apply) {
            foreach ($c in $caches) {
                try { Remove-Item -LiteralPath $c.FullName -Recurse -Force -ErrorAction Stop }
                catch { [void]$failed.Add($c.FullName) }
            }
            Write-Host ("  [DEL ] {0,-52} {1,9} MB" -f ("__pycache__ x" + $caches.Count), (Format-MB $cBytes)) -ForegroundColor Green
        } else {
            Write-Host ("  [WILL] {0,-52} {1,9} MB  （-SkipPycache 可保留）" -f ("__pycache__ x" + $caches.Count), (Format-MB $cBytes))
        }
    }
}

Write-Host ''
Write-Host '------------------------------------------------------------' -ForegroundColor Cyan
if ($Apply) {
    Write-Host (" 已删 {0} 项，释放约 {1} MB" -f $deleted, (Format-MB $totalBytes)) -ForegroundColor Green
} else {
    Write-Host (" 待删 {0} 项，合计约 {1} MB" -f $targets.Count, (Format-MB $totalBytes)) -ForegroundColor Cyan
    Write-Host ' 以上只是预览，什么都没删。要真的删加 -Apply。' -ForegroundColor Yellow
}
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host ' 以下没删掉（多半被进程占用）：' -ForegroundColor Yellow
    foreach ($f in $failed) { Write-Host "   - $f" -ForegroundColor Yellow }
    Write-Host ' 先跑 .vendor\.MeowLLM\stop.bat 再重跑本脚本。' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' 以下**故意保留**（有代码/文档引用，删了会坏）：' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
$keep = @(
    '.vendor\.MeowLLM\labs\dmem_train\.dmem_work\panel.html         webui.py 优先加载它（覆盖内置页面）',
    '.vendor\.MeowLLM\labs\dmem_train\.dmem_work\sft*.jsonl         面板的数据下拉框要列它们',
    '.vendor\.MeowLLM\labs\dmem_train\start_dashboard_remote.bat    模块 README 里有说明',
    '.vendor\.MeowLLM\labs\dmem_train\setup_autodl.sh / run_webui.sh / presets\r64.yaml / mix.py   均被引用',
    '.vendor\.MeowLLM\labs\autoDL\登录指令.txt / 密码.txt            云端凭据，已在 .gitignore 里',
    '.vendor\.MeowLLM\models\                                       backbone + δ-mem 权重，绝不删'
)
foreach ($k in $keep) { Write-Host "   $k" }
Write-Host ''
