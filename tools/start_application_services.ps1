param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimePython = Join-Path $projectRoot '.venv-runtime\Scripts\python.exe'
$nodeEntry = Join-Path $projectRoot 'application-mcp\dist\index.js'
$localConfig = Join-Path $projectRoot 'application-mcp\config\local.json'
$logDirectory = Join-Path $projectRoot 'data\job-applications\engine'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'The Resume Studio Python runtime is missing.' }
if (-not (Test-Path -LiteralPath $nodeEntry)) { throw 'Build application-mcp first: npm run build.' }
$config = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
if ($config.chromeExtensionId -notmatch '^[a-p]{32}$') { throw 'Configure the installed Chrome extension ID first.' }
$env:APP_CHROME_EXTENSION_ID = $config.chromeExtensionId
# Generation runs on Hermes through the local bridge on :8642. Without it every
# generate request fails, so start it with the rest of the services.
& (Join-Path $PSScriptRoot 'start_hermes_bridge.ps1')
function Test-LocalService([string]$Url) {
    try { $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2; return $response.StatusCode -eq 200 } catch { return $false }
}
if (-not (Test-LocalService 'http://127.0.0.1:8088/openapi.json')) {
    Start-Process -FilePath $runtimePython -ArgumentList @('-m','uvicorn','api.server:app','--host','127.0.0.1','--port','8088') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'studio.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'studio.stderr.log') | Out-Null
}
if (-not (Test-LocalService 'http://127.0.0.1:8091/health')) {
    $nodeExecutable = (Get-Command node -ErrorAction Stop).Source
    Start-Process -FilePath $nodeExecutable -ArgumentList @($nodeEntry) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'engine.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'engine.stderr.log') | Out-Null
}
$deadline = (Get-Date).AddSeconds(30)
do {
    $studioReady = Test-LocalService 'http://127.0.0.1:8088/openapi.json'
    $engineReady = Test-LocalService 'http://127.0.0.1:8091/health'
    if ($studioReady -and $engineReady) { break }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if (-not ($studioReady -and $engineReady)) { throw "Services did not become ready. Inspect logs in $logDirectory." }
$api = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/openapi.json' -TimeoutSec 3
if (-not $api.paths.'/application-engine/prepare') { throw 'Port 8088 is running an older Studio API. Restart it with this launcher.' }
Write-Output 'Resume Studio ready: http://127.0.0.1:8088'
Write-Output 'Chrome applications ready: http://127.0.0.1:8091'
if ($OpenBrowser) {
    $chromeExecutable = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
    Start-Process -FilePath $chromeExecutable -ArgumentList @('http://127.0.0.1:8088','http://127.0.0.1:8091') -WindowStyle Hidden
}
