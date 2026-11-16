# scripts/_pack_helper.ps1
# Helper for the pack scripts: disk usage, junction inventory / repair, archive check, SHA256.
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI unless it has a UTF-8 BOM,
# so non-ASCII text here would corrupt string literals.
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('space', 'links', 'verify', 'hash')]
    [string]$Verb,
    [string]$Root,
    [string]$Zip,
    [ValidateSet('full', 'share')]
    [string]$Mode,
    [string]$Path,
    [switch]$Fix
)

$ErrorActionPreference = 'Stop'

# Directory junctions that only point at data stored once elsewhere in the project tree.
# WinRAR follows a junction when packing, so every one of these would be stored a second
# time (about 28 GB). They are excluded by the pack scripts and rebuilt on the target
# machine by the launcher bat in the repo root (or by the app when the engine starts).
$KnownLinks = @(
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\diffusion_models'; Target = '.vendor\.ComfyNode\models\diffusion_models' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\text_encoders'; Target = '.vendor\.ComfyNode\models\text_encoders' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\vae'; Target = '.vendor\.ComfyNode\models\vae' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\loras'; Target = '.vendor\.ComfyNode\models\loras' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\upscale_models'; Target = '.vendor\.ComfyNode\models\upscale_models' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\ultralytics'; Target = '.vendor\.ComfyNode\models\ultralytics' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\models\sams'; Target = '.vendor\.ComfyNode\models\sams' },
    @{ Link = '.vendor\.ComfyNode\ComfyUI\output'; Target = '.vendor\.ComfyNode\output' },
    @{ Link = '.vendor\.gsvlite\models\chinese-hubert-base'; Target = '.vendor\.Sovits\GPT_SoVITS\pretrained_models\chinese-hubert-base' },
    @{ Link = '.vendor\.gsvlite\models\chinese-roberta-wwm-ext-large'; Target = '.vendor\.Sovits\GPT_SoVITS\pretrained_models\chinese-roberta-wwm-ext-large' },
    @{ Link = '.vendor\.gsvlite\models\sv'; Target = '.vendor\.Sovits\GPT_SoVITS\pretrained_models\sv' }
)

function Get-TreeBytes([string]$dir) {
    $s = Get-ChildItem -LiteralPath $dir -Recurse -File -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum
    if ($null -eq $s.Sum) { return [double]0 }
    return [double]$s.Sum
}

function Get-FreeBytes([string]$dir) {
    try {
        $abs = (Resolve-Path -LiteralPath $dir).Path
        $qual = Split-Path -Qualifier $abs
        if (-not $qual) { return [double]0 }
        $name = $qual.TrimEnd(':', '\', '/')
        $d = Get-PSDrive -Name $name -ErrorAction SilentlyContinue
        if ($null -eq $d) { return [double]0 }
        return [double]$d.Free
    } catch { return [double]0 }
}

function Get-ItemSafe([string]$p) {
    try { return Get-Item -LiteralPath $p -Force -ErrorAction Stop } catch { return $null }
}

function Test-IsLink([string]$p) {
    $it = Get-ItemSafe $p
    if ($null -eq $it) { return $false }
    return [bool]($it.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

function Test-IsAlive([string]$p) {
    return [IO.Directory]::Exists($p)
}

function Remove-Entry([string]$p) {
    $it = Get-ItemSafe $p
    if ($null -eq $it) { return }
    if ($it.PSIsContainer) { [IO.Directory]::Delete($p, $false) } else { [IO.File]::Delete($p) }
}

function New-Junction([string]$link, [string]$target) {
    $null = & cmd /c "mklink /J `"$link`" `"$target`"" 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Test-DirEmpty([string]$p) {
    $n = @(Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue).Count
    return ($n -eq 0)
}

switch ($Verb) {

    'space' {
        # stdout is exactly two integers (MB): source bytes, free bytes on the target drive
        # Previous archives live inside the tree but are never packed, so they must not
        # inflate the source size shown to the user.
        $src = Get-TreeBytes $Root
        foreach ($rel in @('scripts\dist', 'scripts\backup')) {
            $p = Join-Path $Root $rel
            if (Test-Path -LiteralPath $p) { $src -= Get-TreeBytes $p }
        }
        if ($src -lt 0) { $src = 0 }
        $free = Get-FreeBytes $Root
        '{0} {1}' -f [long][math]::Floor($src / 1MB), [long][math]::Floor($free / 1MB)
    }

    'links' {
        if (-not (Test-Path -LiteralPath $Root)) { 'ERROR root not found: ' + $Root; exit 1 }
        $base = (Resolve-Path -LiteralPath $Root).ProviderPath
        $bad = 0
        $avoid = [double]0
        $counted = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        $known = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

        foreach ($k in $KnownLinks) {
            [void]$known.Add($k.Link)
            $lp = Join-Path $base $k.Link
            $tp = Join-Path $base $k.Target
            $targetOk = Test-Path -LiteralPath $tp
            $it = Get-ItemSafe $lp
            $isLink = Test-IsLink $lp
            $alive = Test-IsAlive $lp

            if ($targetOk -and $counted.Add($tp)) { $avoid += Get-TreeBytes $tp }

            if ($null -eq $it) {
                $state = 'MISSING'
            } elseif ($isLink -and $alive) {
                $state = 'OK'
            } elseif ($isLink) {
                $state = 'BROKEN'
            } elseif ($it.PSIsContainer) {
                $state = 'REALDIR'
            } else {
                $state = 'STRAYFILE'
            }

            if ($Fix) {
                if ($state -eq 'OK') {
                    'LINK ok       ' + $k.Link
                    continue
                }
                if (-not $targetOk) {
                    'LINK skipped  ' + $k.Link + '  (target missing: ' + $k.Target + ')'
                    $bad++
                    continue
                }
                if ($state -eq 'REALDIR' -and -not (Test-DirEmpty $lp)) {
                    'LINK kept     ' + $k.Link + '  (real directory holding files, left untouched)'
                    continue
                }
                try {
                    if ($state -ne 'MISSING') { Remove-Entry $lp }
                    $parent = Split-Path -Parent $lp
                    if (-not (Test-Path -LiteralPath $parent)) { $null = New-Item -ItemType Directory -Path $parent -Force }
                    if (New-Junction $lp $tp) {
                        'LINK rebuilt  ' + $k.Link
                    } else {
                        'LINK failed   ' + $k.Link
                        $bad++
                    }
                } catch {
                    'LINK failed   ' + $k.Link + '  (' + $_.Exception.Message + ')'
                    $bad++
                }
            } else {
                'LINK {0,-9} {1}' -f $state, $k.Link
            }
        }

        $extra = @()
        foreach ($d in (Get-ChildItem -LiteralPath $base -Recurse -Directory -Force -ErrorAction SilentlyContinue)) {
            if (-not ($d.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
            $rel = $d.FullName.Substring($base.Length).TrimStart('\')
            if ($known.Contains($rel)) { continue }
            $extra += $rel
        }
        foreach ($e in $extra) { 'EXTRA unknown junction not excluded from the pack: ' + $e }

        if ($Fix) {
            'TOTAL repaired, failures ' + $bad
            if ($bad -gt 0) { exit 1 } else { exit 0 }
        } else {
            'AVOID {0:N1} GB would be duplicated if these junctions were packed as files' -f ($avoid / 1GB)
            if ($extra.Count -gt 0) { 'WARN  ' + $extra.Count + ' junction(s) are not in the known list above'; exit 1 }
            exit 0
        }
    }

    'verify' {
        if (-not (Test-Path -LiteralPath $Zip)) {
            'MISS archive not found'
            exit 1
        }
        $entries = New-Object 'System.Collections.Generic.List[string]'
        $unpacked = [double]0
        $archive = $null
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
            $archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
            foreach ($e in $archive.Entries) {
                if ($e.Name -eq '') { continue }
                $entries.Add(($e.FullName -replace '\\', '/'))
                $unpacked += $e.Length
            }
        } catch {
            'WARN cannot read archive directory: ' + $_.Exception.Message
            exit 0
        } finally {
            if ($null -ne $archive) { $archive.Dispose() }
        }

        if ($Mode -eq 'full') {
            $required = @('api.py', 'config.yml', 'runtime/311/python.exe')
            $forbidden = @(
                @{ p = '(^|/)__pycache__/'; why = '__pycache__ leaked in' },
                @{ p = '\.pyc$';           why = '.pyc leaked in' },
                @{ p = '(^|/)\.git/';      why = '.git leaked in' }
            )
        } else {
            $required = @('api.py', 'runtime/311/python.exe', 'character/info/character_prompt/prompt.json')
            $forbidden = @(
                @{ p = '^config\.yml$';                    why = 'root config.yml NOT excluded (secret leak)' },
                @{ p = '^config\.example\.yml$';           why = 'config.example.yml must not ship (personal data)' },
                @{ p = '(^|/)\.temp/';                     why = '.temp leaked in' },
                @{ p = '(^|/)logs/';                       why = 'logs leaked in' },
                @{ p = '(^|/)\.vendor/\.DataBase/';        why = 'knowledge base leaked in' },
                @{ p = '(^|/)\.vendor/\.NapCat/';          why = 'NapCat data leaked in' },
                @{ p = '(^|/)\.vendor/\.NeteaseMusic/server/ncm_cookie\.json$'; why = 'Netease login cookie leaked in' },
                @{ p = '(^|/)\.vendor/\.NeteaseMusic/server/ncm_qr\.png$';      why = 'Netease login QR leaked in' },
                @{ p = '(^|/)\.vendor/\.NeteaseMusic/server/songs_cache/';      why = 'Netease song cache leaked in' },
                @{ p = '(^|/)\.vendor/\.cam/cert/';        why = 'self-signed key leaked in' },
                @{ p = '(^|/)\.vendor/\.CatPaws/config\.yml$'; why = 'CatPaws config.yml NOT excluded (sk- key + device ip)' },
                @{ p = '(^|/)\.vendor/\.CatPaws/catpaws-launcher/run/'; why = 'CatPaws device identity or logs leaked in' },
                @{ p = '(^|/)character/userinfo/';         why = 'character/userinfo (personal profiles) leaked in' },
                @{ p = '(^|/)character/plugin_data/';      why = 'character/plugin_data (plugin user data) leaked in' },
                @{ p = '(^|/)character/director_topic/';   why = 'director plans NOT excluded' },
                @{ p = '(^|/)scripts/napcat_diagnose/out/'; why = 'napcat diagnostic dumps (personal QQ events) NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/output/'; why = 'ComfyUI output images NOT excluded' },
                @{ p = '(^|/)gui/resource/cat_photos_png/'; why = 'source PNG set (unused at runtime) NOT excluded' },
                @{ p = '(^|/)plugins/[^/]+/config\.yml$';  why = 'plugin config.yml NOT excluded (sk- key leak)' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/diffusion_models/moss_image_'; why = 'MOSS base model NOT excluded (9.7G)' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/text_encoders/qwen3\.5_9b_';   why = 'MOSS text encoder NOT excluded (5.8G)' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/vae/flux2-vae\.safetensors$';  why = 'MOSS VAE NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/MOSS-Image-';            why = 'MOSS DMD LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/age slider\.safetensors$'; why = 'MOSS age slider LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/wangzhe_moss\.safetensors$'; why = 'MOSS 2.5D LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/maliker_moss_base_style_'; why = 'MOSS maliker LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/szcb911_lora_r64\.safetensors$'; why = 'MOSS szcb911 v2 LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/kzmynon-moss-v1_'; why = 'MOSS kzmynon LoRA NOT excluded' },
                @{ p = '(^|/)\.vendor/\.ComfyNode/models/loras/moss_whale_'; why = 'MOSS whale LoRA NOT excluded' },
                @{ p = '(^|/)__pycache__/';                why = '__pycache__ leaked in' },
                @{ p = '\.pyc$';                           why = '.pyc leaked in' }
            )
        }

        # A junction packed as files shows up twice: once at the real location and once
        # under the link path. Anything below the link path means the archive got bigger
        # for nothing, so it is a hard failure in both modes.
        $forbidden += @(
            @{ p = '^\.vendor/\.ComfyNode/ComfyUI/models/[^/]+/'; why = 'ComfyUI models junction followed (models stored twice)' },
            @{ p = '^\.vendor/\.ComfyNode/ComfyUI/output/';       why = 'ComfyUI output junction followed (images stored twice)' },
            @{ p = '^\.vendor/\.gsvlite/models/(chinese-hubert-base|chinese-roberta-wwm-ext-large|sv)/'; why = 'gsvlite junction followed (voice models stored twice)' }
        )

        $set = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($e in $entries) { [void]$set.Add($e) }

        $bad = 0
        foreach ($r in $required) {
            if (-not $set.Contains($r)) { "MISS required file missing: $r"; $bad++ }
        }
        foreach ($f in $forbidden) {
            $hit = $null
            foreach ($e in $entries) {
                if ($e -match $f.p) { $hit = $e; break }
            }
            if ($hit) { "BAD  $($f.why): $hit"; $bad++ }
        }
        foreach ($k in $KnownLinks) {
            $rel = ($k.Link -replace '\\', '/')
            if ($set.Contains($rel)) { "WARN link entry stored as a file: $rel (the launcher bat rebuilds it)" }
        }
        'COUNT entries {0}' -f $entries.Count
        'SIZE  unpacked {0:N1} GB' -f ($unpacked / 1GB)
        if ($bad -gt 0) { exit 1 } else { exit 0 }
    }

    'hash' {
        if (-not (Test-Path -LiteralPath $Path)) { exit 1 }
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
}
