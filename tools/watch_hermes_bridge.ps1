$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $projectRoot 'tmp'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$env:HERMES_BRIDGE_HOST = '127.0.0.1'
while ($true) {
    try {
        & (Join-Path $PSScriptRoot 'start_hermes_bridge.ps1') | Out-Null
    } catch {
        Add-Content -LiteralPath (Join-Path $logDirectory 'hermes-watch.log') -Value "$(Get-Date -Format o) Bridge recovery failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 30
}
