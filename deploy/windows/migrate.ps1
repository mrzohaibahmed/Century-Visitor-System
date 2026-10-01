<#
.SYNOPSIS
  Applies the database schema (collections, validators, indexes) with the cgvms_migrate account.

.DESCRIPTION
  Run after installing and after every application update, BEFORE starting CGVMS-API:
      powershell -NoProfile -ExecutionPolicy Bypass -File migrate.ps1 [-ConfigPath ...]
  The application's own account (cgvms_app) may not change the schema, on purpose. The migration
  account's connection string is read from secrets\cgvms_migrate.uri.txt and handed to the command
  only through this process's environment (never on a command line, never in a file of the app).
  Safe to repeat. Never touches the legacy database (the API refuses its name).
#>
param([string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1')

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsConfig $ConfigPath
$python = Get-CgvmsPython $cfg
$uriFile = Join-Path $cfg.Root 'secrets\cgvms_migrate.uri.txt'
if (-not (Test-Path -LiteralPath $uriFile)) { throw "Not found: $uriFile (created by cgvms_mongo.py init)." }

$previous = $env:CG_MONGO_URI
try {
    $env:CG_MONGO_URI = (Get-Content -LiteralPath $uriFile -Raw).Trim()
    Push-Location (Join-Path $cfg.AppDir 'backend')
    & $python -m app.cli migrate
    $code = $LASTEXITCODE
    $env:CG_MONGO_URI = $previous                  # the readiness check uses the application's own account
    $checkCode = 0
    if ($code -eq 0) { & $python -m app.cli check; $checkCode = $LASTEXITCODE }
} finally {
    Pop-Location
    $env:CG_MONGO_URI = $previous
}
if ($code -ne 0) { Write-Host "Migration FAILED (exit code $code)."; exit $code }
if ($checkCode -ne 0) { Write-Host 'Migration applied, but the readiness check (with backend\.env) is not ready: see the output above.'; exit 1 }
Write-Host 'Migration done. Start (or restart) the service CGVMS-API.'
exit 0
