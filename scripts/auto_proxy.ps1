# auto_proxy.ps1 - 探测本机代理端口，成功时只输出端口号
# 顺序：Windows 系统代理设置里登记的端口 -> 常见代理软件端口
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

$candidates = New-Object System.Collections.Generic.List[int]

try {
    $reg = Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction Stop
    if ($reg.ProxyServer) {
        foreach ($m in [regex]::Matches([string]$reg.ProxyServer, ':(\d{2,5})')) {
            $candidates.Add([int]$m.Groups[1].Value)
        }
    }
    if ($reg.ProxyOverride) { }
} catch { }

foreach ($p in 7890, 7897, 10809, 10808, 1080, 8080, 20171, 10801, 10802) {
    $candidates.Add($p)
}

foreach ($port in ($candidates | Select-Object -Unique)) {
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect('127.0.0.1', $port)
        if ($client.Connected) {
            Write-Output $port
            break
        }
    } catch { }
    finally {
        if ($client) { $client.Close() }
    }
}
