$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if ($listeners | Where-Object { $_.Port -eq 8642 }) {
    Write-Host 'Hermes bridge is already listening on port 8642.'
    exit 0
}

# Docker Desktop's host.docker.internal gateway does not always target the WSL
# adapter address. Listen on all host interfaces so that route remains stable;
# hermes_cli_bridge.py requires the shared HERMES_API_KEY from .env.
$bridgeHost = '0.0.0.0'
$env:HERMES_BRIDGE_HOST = $bridgeHost
$process = Start-Process `
    -FilePath 'python' `
    -ArgumentList 'tools\hermes_cli_bridge.py' `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2
$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
if (-not ($listeners | Where-Object { $_.Port -eq 8642 })) {
    throw "Hermes bridge process $($process.Id) did not open port 8642."
}

Write-Host "Hermes bridge started on ${bridgeHost}:8642 with API-key authentication (PID $($process.Id))."
