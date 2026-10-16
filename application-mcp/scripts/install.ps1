param([switch]$WithTestBrowser)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $projectPath
try {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Install Node.js 22 or newer first.' }
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Check network access and native module installation.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
    if ($WithTestBrowser) {
        $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectPath 'node_modules\.cache\ms-playwright'
        & npx.cmd playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Test-browser download failed.' }
    }
    Write-Host "Built successfully. Load unpacked extension from: $(Join-Path $projectPath 'extension')"
    Write-Host 'Then run scripts/start.ps1 -ExtensionId <the ID shown by Chrome>.'
} finally { Pop-Location }
