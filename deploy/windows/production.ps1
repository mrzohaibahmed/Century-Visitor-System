<#
.SYNOPSIS
  Starts, stops or checks Century Gate VMS in production mode on this PC (start-, stop-, restart-production.bat).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action start [-Rebuild]
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action stop
      powershell -NoProfile -ExecutionPolicy Bypass -File production.ps1 -Action status

  Runs the EXISTING project from this folder as normal processes (no Windows services, no copy):
    MongoDB   scripts\dev_mongo.py start       the project's own instance, 127.0.0.1:27018, data in .dev\mongo
    API       python -m app.serve              production server (no reload, no API docs), 127.0.0.1:8000
    Web       node server.mjs                  production build (npm run build), 0.0.0.0:3000 (plain HTTP);
                                               sets the client address the API sees (frontend\server\forwarding.mjs)
  Gate PCs use http://<this PC's name or IP>:3000 on the trusted private LAN: no TLS, no certificate, no
  Caddy. Only the web server listens on the network; the API and MongoDB stay on 127.0.0.1. Start is
  refused unless every connected network is Private or Domain (never on a Public hotspot). Windows
  Firewall is not part of this deployment and is never changed. HTTP is not encrypted, and browsers allow
  the webcam fallback only on HTTPS or on this PC itself; the gate cameras (Hikvision) are read by the
  server and still work.

  Settings: backend\.env as it is, with four production values set for the API process only
  (environment variables override backend\.env, so start-dev.bat keeps working unchanged):
    CG_ENVIRONMENT=production
    CG_DEPLOYMENT_MODE=http-lan             plain HTTP on the LAN: cookies without Secure (README)
    CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true   the project's database has no login (allowed on 127.0.0.1 only)
    CG_PHOTO_DIR=<project>\.dev\photos      the existing photos (unless backend\.env sets CG_PHOTO_DIR)
  Optional: CGVMS_SITE (the name gate PCs use in messages; default: this PC's computer name).

  Runtime files in .prod\: logs\api.log, logs\web.log (previous run: *.1.log).
  MongoDB log: .dev\mongo\mongod.log.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('start', 'stop', 'status')][string]$Action,
    [switch]$Rebuild
)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsLocalConfig
$app = $cfg.AppDir
$run = $cfg.Root                                            # .prod
$logs = Join-Path $run 'logs'
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

function New-Log([string]$Name) {
    $file = Join-Path $logs "$Name.log"
    if (Test-Path -LiteralPath $file) { Move-Item -LiteralPath $file -Destination (Join-Path $logs "$Name.1.log") -Force }
    return $file
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
    foreach ($item in @(@('Web', 'node'), @('API', 'python'))) {
        $name, $program = $item
        $p = Get-Ours $name $program
        if ($p) { Stop-Process -Id $p.Id -Force; Say "  $name stopped." } else { Say "  $name was not running." }
    }
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
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$node = Join-Path 'C:\Program Files\nodejs' 'node.exe'
if (-not (Test-Path -LiteralPath $node)) { $cmd = Get-Command node.exe -ErrorAction SilentlyContinue; if ($cmd) { $node = $cmd.Source } }
$missing = @()
if (-not (Test-Path -LiteralPath $python)) { $missing += "Python environment $python (README, Local development)" }
if (-not (Test-Path -LiteralPath $node)) { $missing += 'Node.js (nodejs.org)' }
if (-not (Test-Path (Join-Path $app 'frontend\node_modules'))) { $missing += 'frontend dependencies: cd frontend; npm ci' }
if (-not (Test-Path (Join-Path $app 'backend\.env'))) { $missing += 'backend\.env (copy backend\.env.example)' }
if ($missing) { Say 'Missing:'; $missing | ForEach-Object { Say "  - $_" }; Fail 'Install the missing parts, then start again.' }

# The web server listens on 0.0.0.0:3000 (plain HTTP): only on a trusted Private/Domain network, never on a
# Public one (hotspot, guest Wi-Fi). Checked before anything starts, so a refused start leaves nothing running.
$networks = @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)
$exposure = Get-LanExposureProblem $networks
if ($exposure) {
    Fail ($exposure + "`n       Connect this PC to the trusted gate LAN (network profile Private or Domain), then start again.")
}
$pids = Read-Pids

# Development servers hold the same ports: refuse instead of guessing.
foreach ($item in @(@('API', 'python', 8000), @('Web', 'node', 3000))) {
    $name, $program, $port = $item
    if ((Get-PortOwner $port) -and -not (Get-Ours $name $program)) {
        Fail "Port $port is already in use (a development server from start-dev.bat?). Close the 'CGVMS API' / 'CGVMS Web' windows first."
    }
}

Say ''
Say '[1/4] MongoDB (127.0.0.1:27018, data in .dev\mongo) ...'
$ErrorActionPreference = 'Continue'
& $python (Join-Path $app 'scripts\dev_mongo.py') start
$mongoExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($mongoExit -ne 0) { Fail "MongoDB did not start; see $app\.dev\mongo\mongod.log" }

Say ''
Say '[2/4] Web production build ...'
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
Say '[3/4] API (127.0.0.1:8000, production server) ...'
if (Get-Ours 'API' 'python') {
    Say '      already running.'
} else {
    $envText = Get-Content -LiteralPath (Join-Path $app 'backend\.env') -Raw
    $env:CG_ENVIRONMENT = 'production'
    $env:CG_DEPLOYMENT_MODE = 'http-lan'
    $env:CG_MONGO_LOCALHOST_WITHOUT_LOGIN = 'true'
    if ($envText -notmatch '(?m)^\s*CG_PHOTO_DIR\s*=') { $env:CG_PHOTO_DIR = $cfg.PhotoDir }
    $env:PYTHONUNBUFFERED = '1'
    $apiLog = New-Log 'api'
    $p = Start-Process -FilePath $python -ArgumentList '-m', 'app.serve', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory (Join-Path $app 'backend') -WindowStyle Hidden -PassThru `
        -RedirectStandardError $apiLog -RedirectStandardOutput (Join-Path $logs 'api.out.log')
    $pids['API'] = $p.Id; Save-Pids $pids
    Wait-Until { Test-Url 'http://127.0.0.1:8000/api/v1/health/live' } $p 60 'The API' $apiLog
    Say "      started (log: $apiLog)."
}

Say ''
Say '[4/4] Web (http://0.0.0.0:3000, server.mjs) ...'
if (Get-Ours 'Web' 'node') {
    Say '      already running.'
} else {
    $env:NODE_ENV = 'production'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $webLog = New-Log 'web'
    $p = Start-Process -FilePath $node `
        -ArgumentList 'server.mjs', '--hostname', '0.0.0.0', '--port', '3000' `
        -WorkingDirectory (Join-Path $app 'frontend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $webLog -RedirectStandardError (Join-Path $logs 'web.err.log')
    $pids['Web'] = $p.Id; Save-Pids $pids
    Wait-Until { Test-Url 'http://127.0.0.1:3000/login' } $p 60 'The web server' $webLog
    Say "      started (log: $webLog)."
}

if (Get-Ours 'Caddy' 'caddy') {
    Say '      NOTE: Caddy from the former HTTPS setup is still running on 443; stop-production.bat stops it.'
}
# Only the web server (3000) listens on the network; the API (8000) and MongoDB (27018) on 127.0.0.1 only.
$lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceIndex -in $networks.InterfaceIndex } | ForEach-Object { $_.IPAddress })

Say ''
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1')
Say ''
Say 'Century Gate VMS is running in production mode.'
foreach ($ip in $lanIps) { Say "  Gate PCs:   http://${ip}:3000   (plain HTTP on the trusted LAN)" }
Say "             http://${site}:3000   (this PC's name, if the gate PCs can resolve it)"
Say '  This PC:    http://localhost:3000'
Say "  Logs:       $logs   and   $app\.dev\mongo\mongod.log"
Say 'The programs keep running when this window closes; they stop at sign-out or shutdown (stop-production.bat stops them).'
exit 0
