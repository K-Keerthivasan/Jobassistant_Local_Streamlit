param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-p]{32}$')][string]$ExtensionId,
    [switch]$Stdio
)
$ErrorActionPreference = 'Stop'
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$entryPath = Join-Path $projectPath 'dist\index.js'
if (-not (Test-Path -LiteralPath $entryPath)) { throw 'Run scripts/install.ps1 first.' }
$env:APP_CHROME_EXTENSION_ID = $ExtensionId
if ($Stdio) { & node $entryPath --stdio } else { & node $entryPath }
