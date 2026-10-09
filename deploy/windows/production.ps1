<#
.SYNOPSIS
  Starts, stops or checks Century Gate VMS in production mode on this PC (start-, stop-, restart-production.bat).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action start [-Rebuild]
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action stop
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action status

  Runs the EXISTING project from this folder as normal processes (no Windows services, no copy), the API
  and the web server each in its own console window ("CGVMS API", "CGVMS Web") as start-dev.bat does:
    MongoDB   scripts\dev_mongo.py start       the project's own instance, 127.0.0.1:27018, data in .cgvms\data\mongo
    Schema    python -m app.cli migrate         idempotent database validators and indexes
    API       python -m app.serve               production server (no reload, no API docs), 127.0.0.1:8000
    Web       node server.mjs                   production build (npm run build), 0.0.0.0:6543 (plain HTTP);
                                                sets the client address the API sees (frontend\server\forwarding.mjs)
  Gate PCs use http://<this PC's name or IP>:6543 on the organization's network: no TLS, no certificate, no
  Caddy. Only the web server listens on the network; the API and MongoDB stay on 127.0.0.1. The Windows
  network profile (Public, Private, Domain) is not a start requirement. Windows Firewall is not part of
  this deployment and is never changed. HTTP is not encrypted, and browsers allow
  the webcam fallback only on HTTPS or on this PC itself; the gate cameras (Hikvision) are read by the
  server and still work.

  Settings: backend\.env as it is, with four production values set for the API process only
  (environment variables override backend\.env, so start-dev.bat keeps working unchanged):
    CG_ENVIRONMENT=production
    CG_DEPLOYMENT_MODE=http-lan             plain HTTP on the LAN: cookies without Secure (README)
    CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true   the project's database has no login (allowed on 127.0.0.1 only)
    CG_PHOTO_DIR=<project>\.cgvms\data\photos  the existing photos (unless backend\.env sets CG_PHOTO_DIR)
  Optional: CGVMS_SITE (the name gate PCs use in messages; default: this PC's computer name).

  Output: live in the "CGVMS API" and "CGVMS Web" windows (closing one stops that server).
  All local operational data is in .cgvms\: database, photos, process state, logs and health status.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('start', 'stop', 'status')][string]$Action,
    [switch]$Rebuild
)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsLocalConfig
$app = $cfg.AppDir
$run = $cfg.RunDir
$pidFile = Join-Path $run 'processes.json'
$python = Join-Path $app 'backend\.venv\Scripts\python.exe'
$site = $cfg.SiteName

function Say([string]$Message) { Write-Host $Message }
function Fail([string]$Message) { Write-Host ''; Write-Host "ERROR: $Message" -ForegroundColor Red; exit 1 }

function Get-PortOwner([int]$Port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
}

function Read-Pids {
    if (-not (Test-Path -LiteralPath $pidFile)) { return @{} }
    $h = @{}
    (Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $h[$_.Name] = [int]$_.Value }
    return $h
}

function Save-Pids([hashtable]$Pids) { $Pids | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding ASCII }

# The process we started, if it is still the same program (process ids are reused by Windows).
function Get-Ours([string]$Name, [string]$Program) {
    $pids = Read-Pids
    if (-not $pids.ContainsKey($Name)) { return $null }
    $p = Get-Process -Id $pids[$Name] -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -eq $Program) { return $p }
    return $null
}

# A server in its own console window, as start-dev.bat does: its output shows live there. cmd /k keeps the
# window open if the server stops, so the error stays readable. Remembers the window and, once the server
# answers, the process that listens on the port (what Get-Ours and the stop below look for).
function Start-Window([string]$Name, [string]$Title, [string]$Dir, [string]$Command, [int]$Port, [string]$ReadyUrl) {
    $w = Start-Process -FilePath $env:ComSpec -WorkingDirectory $Dir -PassThru `
        -ArgumentList '/s', '/k', ('"title {0} & {1}"' -f $Title, $Command)
    $pids["$Name window"] = $w.Id; Save-Pids $pids
    Wait-Until { Test-Url $ReadyUrl } $null 60 $Name "the `"$Title`" window"
    $pids[$Name] = (Get-PortOwner $Port).Id; Save-Pids $pids
}

# Closes the window and everything started in it (taskkill /T), or the server alone if its window is gone.
function Stop-Window([string]$Name, [string]$Program) {
    $w = Get-Ours "$Name window" 'cmd'
    $p = Get-Ours $Name $Program
    if ($w) { & taskkill.exe /T /F /PID $w.Id 2>&1 | Out-Null }
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    if ($w -or $p) { Say "  $Name stopped." } else { Say "  $Name was not running." }
}

function Wait-Until([scriptblock]$Ready, [Diagnostics.Process]$Process, [int]$Seconds, [string]$What, [string]$Log) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while (-not (& $Ready)) {
        if ($Process -and $Process.HasExited) {
            Say "      $What stopped at once. End of $Log :"
            if (Test-Path -LiteralPath $Log) { Get-Content -LiteralPath $Log -Tail 15 | ForEach-Object { Say "        $_" } }
            Fail "$What did not start."
        }
        if ((Get-Date) -gt $deadline) { Fail "$What did not answer within $Seconds seconds; see $Log" }
        Start-Sleep -Milliseconds 500
    }
}

function Test-Url([string]$Url, [int]$Expect = 200) {
    try { return [int](Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5 -MaximumRedirection 0).StatusCode -eq $Expect }
    catch { return $false }
}

# ================================================================================================= stop
if ($Action -eq 'stop') {
    Stop-Window 'Web' 'node'
    Stop-Window 'API' 'python'
    # A Caddy started by an earlier version of this script (the former HTTPS setup) is not part of the
    # application any more; stop it as well so it does not keep answering on 443. Nothing waits for it.
    $legacy = Get-Ours 'Caddy' 'caddy'
    if ($legacy) { Stop-Process -Id $legacy.Id -Force; Say '  Caddy (former HTTPS setup) stopped.' }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force }
    $ErrorActionPreference = 'Continue'
    & $python (Join-Path $app 'scripts\dev_mongo.py') stop
    $ErrorActionPreference = 'Stop'
    Say 'Century Gate VMS is stopped.'
    exit 0
}

# ================================================================================================= status
if ($Action -eq 'status') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1')
    exit $LASTEXITCODE
}

# ================================================================================================= start
New-Item -ItemType Directory -Force -Path $run | Out-Null
$node = Join-Path 'C:\Program Files\nodejs' 'node.exe'
if (-not (Test-Path -LiteralPath $node)) { $cmd = Get-Command node.exe -ErrorAction SilentlyContinue; if ($cmd) { $node = $cmd.Source } }
$missing = @()
if (-not (Test-Path -LiteralPath $python)) { $missing += "Python environment $python (README, Local development)" }
if (-not (Test-Path -LiteralPath $node)) { $missing += 'Node.js (nodejs.org)' }
if (-not (Test-Path (Join-Path $app 'frontend\node_modules'))) { $missing += 'frontend dependencies: cd frontend; npm ci' }
if (-not (Test-Path (Join-Path $app 'backend\.env'))) { $missing += 'backend\.env (copy backend\.env.example)' }
if ($missing) { Say 'Missing:'; $missing | ForEach-Object { Say "  - $_" }; Fail 'Install the missing parts, then start again.' }

# Connected networks: only to print the addresses gate PCs can use (below). Whatever Windows calls a network
# (Public, Private or Domain), its name or its addresses never decide whether the VMS starts.
$networks = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
$pids = Read-Pids

# Development servers hold the same ports: refuse instead of guessing.
foreach ($item in @(@('API', 'python', 8000), @('Web', 'node', 6543))) {
    $name, $program, $port = $item
    if ((Get-PortOwner $port) -and -not (Get-Ours $name $program)) {
        Fail "Port $port is already in use (a development server from start-dev.bat?). Close the 'CGVMS API' / 'CGVMS Web' windows first."
    }
}

Say ''
Say '[1/5] MongoDB (127.0.0.1:27018, data in .cgvms\data\mongo) ...'
$ErrorActionPreference = 'Continue'
& $python (Join-Path $app 'scripts\dev_mongo.py') start
$mongoExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($mongoExit -ne 0) { Fail "MongoDB did not start; see $($cfg.MongoDir)\mongod.log" }

$envText = Get-Content -LiteralPath (Join-Path $app 'backend\.env') -Raw
$env:CG_ENVIRONMENT = 'production'
$env:CG_DEPLOYMENT_MODE = 'http-lan'
$env:CG_MONGO_LOCALHOST_WITHOUT_LOGIN = 'true'
if ($envText -notmatch '(?m)^\s*CG_PHOTO_DIR\s*=') { $env:CG_PHOTO_DIR = $cfg.PhotoDir }
$env:PYTHONUNBUFFERED = '1'

Say ''
Say '[2/5] Database schema ...'
Push-Location (Join-Path $app 'backend')
$ErrorActionPreference = 'Continue'
& $python -m app.cli migrate
$migrationExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
Pop-Location
if ($migrationExit -ne 0) { Fail 'Database migration failed (see above).' }

Say ''
Say '[3/5] Web production build ...'
$buildId = Join-Path $app 'frontend\.next\BUILD_ID'
if ($Rebuild -or -not (Test-Path -LiteralPath $buildId)) {
    if (Get-Ours 'Web' 'node') { Fail 'The web server is running: stop-production.bat first, then start with a new build.' }
    Push-Location (Join-Path $app 'frontend')
    $ErrorActionPreference = 'Continue'
    & (Join-Path (Split-Path $node) 'npm.cmd') run build
    $buildExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Pop-Location
    if ($buildExit -ne 0) { Fail 'npm run build failed (see above).' }
} else {
    Say "      using the existing build of $((Get-Item -LiteralPath $buildId).LastWriteTime.ToString('yyyy-MM-dd HH:mm')) (restart-production.bat rebuild = build again)."
}

Say ''
Say '[4/5] API (127.0.0.1:8000, production server) ...'
if (Get-Ours 'API' 'python') {
    Say '      already running.'
} else {
    # First run only: admin / admin1234, which must be changed at the first login (does nothing once accounts exist).
    Push-Location (Join-Path $app 'backend')
    $ErrorActionPreference = 'Continue'
    & $python -m app.cli first-admin
    $adminExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    Pop-Location
    if ($adminExit -ne 0) { Fail 'Could not check for or create the first administrator (see above).' }
    Start-Window 'API' 'CGVMS API' (Join-Path $app 'backend') '.venv\Scripts\python.exe -m app.serve --host 127.0.0.1 --port 8000' `
        8000 'http://127.0.0.1:8000/api/v1/health/live'
    Say '      started in the window "CGVMS API".'
}

Say ''
Say '[5/5] Web (http://0.0.0.0:6543, server.mjs) ...'
if (Get-Ours 'Web' 'node') {
    Say '      already running.'
} else {
    $env:NODE_ENV = 'production'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    Start-Window 'Web' 'CGVMS Web' (Join-Path $app 'frontend') ('"{0}" server.mjs --hostname 0.0.0.0 --port 6543' -f $node) `
        6543 'http://127.0.0.1:6543/login'
    Say '      started in the window "CGVMS Web".'
}

if (Get-Ours 'Caddy' 'caddy') {
    Say '      NOTE: Caddy from the former HTTPS setup is still running on 443; stop-production.bat stops it.'
}
# Only the web server (6543) listens on the network; the API (8000) and MongoDB (27018) on 127.0.0.1 only.
$lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceIndex -in $networks.InterfaceIndex } | ForEach-Object { $_.IPAddress })

Say ''
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1')
$healthExit = $LASTEXITCODE
if ($healthExit -ne 0) { Fail 'The services started, but the final health check failed (see above).' }
Say ''
Say 'Century Gate VMS is running in production mode.'
foreach ($ip in $lanIps) { Say "  Gate PCs:   http://${ip}:6543   (plain HTTP on the trusted LAN)" }
Say "             http://${site}:6543   (this PC's name, if the gate PCs can resolve it)"
Say '  This PC:    http://localhost:6543'
Say "  Output:     the `"CGVMS API`" and `"CGVMS Web`" windows; MongoDB log: $($cfg.MongoDir)\mongod.log"
Say 'Closing the "CGVMS API" or "CGVMS Web" window stops that server; closing this window does not.'
Say 'They also stop at sign-out or shutdown (stop-production.bat stops everything).'
exit 0
