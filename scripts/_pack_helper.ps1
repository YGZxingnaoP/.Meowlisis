# scripts/_pack_helper.ps1
# Helper for the pack scripts: disk usage, archive content check, SHA256.
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI unless it has a UTF-8 BOM,
# so non-ASCII text here would corrupt string literals.
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('space', 'verify', 'hash')]
    [string]$Verb,
    [string]$Root,
    [string]$Zip,
    [ValidateSet('full', 'share')]
    [string]$Mode,
    [string]$Path
)

$ErrorActionPreference = 'Stop'

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

switch ($Verb) {

    'space' {
        # stdout is exactly two integers (MB): source bytes, free bytes on the target drive
        $src = Get-TreeBytes $Root
        $free = Get-FreeBytes $Root
        '{0} {1}' -f [long][math]::Floor($src / 1MB), [long][math]::Floor($free / 1MB)
    }

    'verify' {
        if (-not (Test-Path -LiteralPath $Zip)) {
            'MISS archive not found'
            exit 1
        }
        $entries = New-Object 'System.Collections.Generic.List[string]'
        $archive = $null
        try {
            Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
            $archive = [System.IO.Compression.ZipFile]::OpenRead($Zip)
            foreach ($e in $archive.Entries) { $entries.Add(($e.FullName -replace '\\', '/')) }
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
            $required = @('api.py', 'runtime/311/python.exe')
            $forbidden = @(
                @{ p = '^config\.yml$';                    why = 'root config.yml NOT excluded (secret leak)' },
                @{ p = '^config\.example\.yml$';           why = 'config.example.yml must not ship (personal data)' },
                @{ p = '(^|/)\.temp/';                     why = '.temp leaked in' },
                @{ p = '(^|/)logs/';                       why = 'logs leaked in' },
                @{ p = '(^|/)\.vendor/\.DataBase/';        why = 'knowledge base leaked in' },
                @{ p = '(^|/)\.vendor/\.NapCat/';          why = 'NapCat data leaked in' },
                @{ p = '(^|/)\.vendor/\.cam/cert/';        why = 'self-signed key leaked in' },
                @{ p = '(^|/)\.vendor/\.CatPaws/config\.yml$'; why = 'CatPaws config.yml NOT excluded (sk- key + device ip)' },
                @{ p = '(^|/)\.vendor/\.CatPaws/catpaws-launcher/run/'; why = 'CatPaws device identity or logs leaked in' },
                @{ p = '(^|/)character/userinfo/';         why = 'character/userinfo (personal profiles) leaked in' },
                @{ p = '(^|/)character/plugin_data/';      why = 'character/plugin_data (plugin user data) leaked in' },
                @{ p = '(^|/)plugins/[^/]+/config\.yml$';  why = 'plugin config.yml NOT excluded (sk- key leak)' },
                @{ p = '(^|/)__pycache__/';                why = '__pycache__ leaked in' },
                @{ p = '\.pyc$';                           why = '.pyc leaked in' }
            )
        }

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
        "COUNT entries $($entries.Count)"
        if ($bad -gt 0) { exit 1 } else { exit 0 }
    }

    'hash' {
        if (-not (Test-Path -LiteralPath $Path)) { exit 1 }
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
}
