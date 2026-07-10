[CmdletBinding()]
param(
    [string]$LanSubnet
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-EnvValue {
    param([string]$Name)

    $envFile = Join-Path $repoRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile)) {
        return $null
    }

    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match "^$([regex]::Escape($Name))=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

if ([string]::IsNullOrWhiteSpace($LanSubnet)) {
    $LanSubnet = Get-EnvValue -Name 'UMBREL_LAN_SUBNET'
}

if ([string]::IsNullOrWhiteSpace($LanSubnet)) {
    throw 'Defina UMBREL_LAN_SUBNET no .env ou informe -LanSubnet, por exemplo 192.168.1.0/24.'
}

$isAdministrator = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdministrator) {
    throw 'Execute este script em um PowerShell iniciado como Administrador.'
}

$group = 'Umbrel Dockyard'
$tcpPorts = @(8080, 8094, 8096, 11434, 18790, 3435, 8000)

Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule `
    -DisplayName 'Umbrel Dockyard LAN - TCP' `
    -Group $group `
    -Direction Inbound `
    -Action Allow `
    -Profile Public,Private `
    -Protocol TCP `
    -LocalPort $tcpPorts `
    -RemoteAddress $LanSubnet `
    -Description 'Permite os serviços publicados pelo Umbrel Dockyard somente na rede local.' | Out-Null

New-NetFirewallRule `
    -DisplayName 'Umbrel Dockyard LAN - Jellyfin Discovery' `
    -Group $group `
    -Direction Inbound `
    -Action Allow `
    -Profile Public,Private `
    -Protocol UDP `
    -LocalPort 7359 `
    -RemoteAddress $LanSubnet `
    -Description 'Permite a descoberta do Jellyfin somente na rede local.' | Out-Null

Write-Host "Regras aplicadas para $LanSubnet." -ForegroundColor Green
Get-NetFirewallRule -Group $group | Get-NetFirewallPortFilter |
    Select-Object Protocol, LocalPort, RemoteAddress |
    Format-Table -AutoSize
