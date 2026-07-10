[CmdletBinding()]
param(
    [string]$EnvFile,
    [switch]$SkipRestart,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvFile) {
    $EnvFile = Join-Path $RepoRoot '.env'
}

function Import-DotEnv {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Environment file not found: $Path. Copy .env.example to .env and fill in the local values."
    }

    foreach ($rawLine in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).Trim() }
        $separator = $line.IndexOf('=')
        if ($separator -lt 1) { throw "Invalid .env line: $rawLine" }

        $name = $line.Substring(0, $separator).Trim()
        $value = $line.Substring($separator + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

function Get-Setting {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string]$Default,
        [switch]$Required
    )

    $value = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) { $value = $Default }
    if ($Required -and [string]::IsNullOrWhiteSpace($value)) {
        throw "Required setting '$Name' is missing from $EnvFile."
    }
    return $value
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [string]$InputText,
        [switch]$Capture
    )

    if ($PSBoundParameters.ContainsKey('InputText')) {
        if ($Capture) { $output = $InputText | & docker @Arguments 2>&1 }
        else { $InputText | & docker @Arguments }
    } else {
        if ($Capture) { $output = & docker @Arguments 2>&1 }
        else { & docker @Arguments }
    }
    if ($LASTEXITCODE -ne 0) {
        if ($Capture) { $output | Write-Host }
        throw "Docker command failed: docker $($Arguments -join ' ')"
    }
    if ($Capture) { return ($output -join "`n") }
}

function Test-ContainerRunning {
    param([Parameter(Mandatory)][string]$Name)
    $state = Invoke-Docker -Arguments @('inspect', '-f', '{{.State.Running}}', $Name) -Capture
    if ($state.Trim() -ne 'true') { throw "Container '$Name' is not running." }
}

function Remove-McpIfPresent {
    param([Parameter(Mandatory)][string]$Name)
    & docker exec $script:HermesContainer $script:HermesCli mcp remove $Name *> $null
}

Import-DotEnv -Path $EnvFile

$script:HermesContainer = Get-Setting -Name HERMES_CONTAINER -Default 'hermes-agent_web_1'
$UmbrelContainer = Get-Setting -Name UMBREL_CONTAINER -Default 'Umbrel'
$HermesAppId = Get-Setting -Name HERMES_APP_ID -Default 'hermes-agent'
$HermesDataDir = Get-Setting -Name HERMES_DATA_DIR -Default '/opt/data'
$script:HermesCli = Get-Setting -Name HERMES_CLI -Default '/opt/hermes/.venv/bin/hermes'
$HermesPython = Get-Setting -Name HERMES_PYTHON -Default '/opt/hermes/.venv/bin/python'

$CuaHost = Get-Setting -Name CUA_SSH_HOST -Required
$CuaPort = Get-Setting -Name CUA_SSH_PORT -Default '22'
$CuaUser = Get-Setting -Name CUA_SSH_USER -Required
$CuaKey = Get-Setting -Name CUA_SSH_KEY -Required
$CuaExecutable = Get-Setting -Name CUA_WINDOWS_EXECUTABLE -Required
$TorrentClawVersion = Get-Setting -Name TORRENTCLAW_VERSION -Default '0.2.1'

$QbtBaseUrl = Get-Setting -Name QBITTORRENT_BASE_URL -Default 'http://qbittorrent_server_1:8080'
$QbtUsername = Get-Setting -Name QBITTORRENT_USERNAME -Default 'admin'
$QbtPassword = Get-Setting -Name QBITTORRENT_PASSWORD
$QbtPasswordFile = Get-Setting -Name QBITTORRENT_PASSWORD_FILE -Default "$HermesDataDir/secrets/qbittorrent_password"
$QbtTimeout = Get-Setting -Name QBITTORRENT_TIMEOUT -Default '15'

Write-Host '[1/6] Validating Docker and containers...'
& docker version *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable.' }
Test-ContainerRunning -Name $script:HermesContainer
if (-not $SkipRestart) { Test-ContainerRunning -Name $UmbrelContainer }

Write-Host '[2/6] Installing versioned MCP assets in Hermes...'
Invoke-Docker -Arguments @('exec', $script:HermesContainer, 'mkdir', '-p',
    "$HermesDataDir/bin", "$HermesDataDir/mcp", "$HermesDataDir/skills/media/qbittorrent", "$HermesDataDir/secrets")
Invoke-Docker -Arguments @('cp', (Join-Path $RepoRoot 'hermes/bin/cua-driver-windows-mcp'),
    "${script:HermesContainer}:$HermesDataDir/bin/cua-driver-windows-mcp")
Invoke-Docker -Arguments @('cp', (Join-Path $RepoRoot 'hermes/mcp/qbittorrent_bridge.py'),
    "${script:HermesContainer}:$HermesDataDir/mcp/qbittorrent_bridge.py")
Invoke-Docker -Arguments @('cp', (Join-Path $RepoRoot 'hermes/skills/blink-qbittorrent/SKILL.md'),
    "${script:HermesContainer}:$HermesDataDir/skills/media/qbittorrent/SKILL.md")
Invoke-Docker -Arguments @('exec', $script:HermesContainer, 'chmod', '700',
    "$HermesDataDir/bin/cua-driver-windows-mcp")

Write-Host '[3/6] Preparing local-only credentials...'
if (-not [string]::IsNullOrWhiteSpace($QbtPassword)) {
    Invoke-Docker -Arguments @('exec', '-i', $script:HermesContainer, 'sh', '-c',
        "umask 077; cat > '$QbtPasswordFile'") -InputText $QbtPassword
} else {
    Invoke-Docker -Arguments @('exec', $script:HermesContainer, 'sh', '-c',
        "test -s '$QbtPasswordFile'")
    Write-Host '      Existing qBittorrent password file preserved.'
}
Invoke-Docker -Arguments @('exec', $script:HermesContainer, 'test', '-s', $CuaKey)

Write-Host '[4/6] Registering MCP servers in Hermes...'
Remove-McpIfPresent -Name 'cua-driver-windows'
Invoke-Docker -Arguments @(
    'exec', '-i', $script:HermesContainer, $script:HermesCli, 'mcp', 'add', 'cua-driver-windows',
    '--command', "$HermesDataDir/bin/cua-driver-windows-mcp",
    '--env', "CUA_SSH_HOST=$CuaHost", "CUA_SSH_PORT=$CuaPort", "CUA_SSH_USER=$CuaUser",
    "CUA_SSH_KEY=$CuaKey", "CUA_WINDOWS_EXECUTABLE=$CuaExecutable"
) -InputText 'y'

Remove-McpIfPresent -Name 'torrentclaw'
Invoke-Docker -Arguments @(
    'exec', '-i', $script:HermesContainer, $script:HermesCli, 'mcp', 'add', 'torrentclaw',
    '--command', 'npx', '--args', '-y', "@torrentclaw/mcp@$TorrentClawVersion"
) -InputText 'y'

Remove-McpIfPresent -Name 'qbittorrent'
Invoke-Docker -Arguments @(
    'exec', '-i', $script:HermesContainer, $script:HermesCli, 'mcp', 'add', 'qbittorrent',
    '--command', $HermesPython,
    '--env', "QBITTORRENT_BASE_URL=$QbtBaseUrl", "QBITTORRENT_USERNAME=$QbtUsername",
    "QBITTORRENT_PASSWORD_FILE=$QbtPasswordFile", "QBITTORRENT_TIMEOUT=$QbtTimeout",
    '--args', "$HermesDataDir/mcp/qbittorrent_bridge.py"
) -InputText 'y'

if (-not $SkipRestart) {
    Write-Host '[5/6] Restarting Hermes through Umbrel...'
    Invoke-Docker -Arguments @(
        'exec', '-e', 'UMBREL_DATA_DIR=/c/umbrel', $UmbrelContainer,
        '/opt/umbreld/node_modules/.bin/tsx', '/opt/umbreld/source/cli.ts',
        'client', 'apps.restart.mutate', '--appId', $HermesAppId
    )

    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 2
        $running = (& docker inspect -f '{{.State.Running}}' $script:HermesContainer 2>$null) -eq 'true'
    } until ($running -or (Get-Date) -gt $deadline)
    if (-not $running) { throw 'Hermes did not return after restart.' }
} else {
    Write-Host '[5/6] Restart skipped.'
}

if (-not $SkipTests) {
    Write-Host '[6/6] Testing MCP discovery...'
    foreach ($server in @('cua-driver-windows', 'torrentclaw', 'qbittorrent')) {
        Write-Host "      Testing $server..."
        $testResult = Invoke-Docker -Arguments @(
            'exec', $script:HermesContainer, $script:HermesCli, 'mcp', 'test', $server
        ) -Capture
        Write-Host $testResult
        if ($testResult -match '(?i)not found|failed|error|unable to connect' -or
            $testResult -notmatch '(?i)connected') {
            throw "MCP validation failed for '$server'."
        }
    }
} else {
    Write-Host '[6/6] Tests skipped.'
}

Write-Host ''
Write-Host 'Hermes MCP bootstrap completed successfully.'
Invoke-Docker -Arguments @('exec', $script:HermesContainer, $script:HermesCli, 'mcp', 'list')
