# 仅修复Windows客户端到本项目服务器的代理路径，不修改服务器或任何模型。
[CmdletBinding()]
param(
    [string]$BackupDirectory = (Join-Path $PSScriptRoot 'dist\client_proxy_backup')
)
$ErrorActionPreference = 'Stop'
$serverAddress = '47.243.232.201'
$settingsPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$settings = Get-ItemProperty -LiteralPath $settingsPath
$property = $settings.PSObject.Properties['ProxyOverride']
$previous = if ($null -eq $property) { '' } else { [string]$property.Value }
$entries = @($previous.Split(';') | ForEach-Object { $_.Trim() })
if ($entries -contains $serverAddress) {
    Write-Output 'Proxy exception already contains the GeneScope IP. No change made.'
    exit 0
}
$separator = if ($previous.Length -gt 0 -and -not $previous.EndsWith(';')) { ';' } else { '' }
$updated = $previous + $separator + $serverAddress
$originalKind = if ($null -eq $property) { $null } else { (Get-Item -LiteralPath $settingsPath).GetValueKind('ProxyOverride').ToString() }
if ($null -ne $originalKind -and $originalKind -ne 'String') {
    throw 'Unexpected registry value type; no changes were made.'
}
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
$backupPath = Join-Path $BackupDirectory ('proxy_override_before_' + [guid]::NewGuid().ToString('N') + '.json')
$backup = [ordered]@{
    registry_path = $settingsPath
    value_name = 'ProxyOverride'
    original_value_existed = ($null -ne $property)
    original_kind = $originalKind
    original_value = $previous
    updated_value = $updated
    added_ip = $serverAddress
    scope = 'local_windows_client_only_not_uploaded'
}
$backup | ConvertTo-Json | Set-Content -LiteralPath $backupPath -Encoding UTF8
if ($null -eq $property) {
    New-ItemProperty -LiteralPath $settingsPath -Name 'ProxyOverride' -PropertyType String -Value $updated | Out-Null
} else {
    Set-ItemProperty -LiteralPath $settingsPath -Name 'ProxyOverride' -Value $updated
}
if ((Get-ItemProperty -LiteralPath $settingsPath).ProxyOverride -cne $updated) {
    throw 'The registry update could not be verified. Original value was backed up.'
}
# 通知遵循Windows系统代理的应用刷新设置；不停止或重启浏览器。
if (-not ('GeneScope.WinInetProxyRefresh' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace GeneScope {
    public static class WinInetProxyRefresh {
        [DllImport("wininet.dll", SetLastError=true)]
        public static extern bool InternetSetOption(IntPtr h, int option, IntPtr buffer, int length);
    }
}
'@
}
$notified = [GeneScope.WinInetProxyRefresh]::InternetSetOption([IntPtr]::Zero, 39, [IntPtr]::Zero, 0)
$refreshed = [GeneScope.WinInetProxyRefresh]::InternetSetOption([IntPtr]::Zero, 37, [IntPtr]::Zero, 0)
[ordered]@{
    added_ip = $serverAddress
    proxy_server_and_enable_flags_changed = $false
    backup_file = $backupPath
    settings_change_notified = $notified
    refresh_notified = $refreshed
} | ConvertTo-Json
