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
    Web       next start                       production build (npm run build), 127.0.0.1:3000
    HTTPS     caddy run (deploy\windows\caddy\Caddyfile, internal certificate)   0.0.0.0:443, 80 -> 443
  Gate PCs use https://<this PC's name>: login cookies and the webcam need HTTPS (README).

  Settings: backend\.env as it is, with three production values set for the API process only
  (environment variables override backend\.env, so start-dev.bat keeps working unchanged):
    CG_ENVIRONMENT=production
    CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true   the project's database has no login (allowed on 127.0.0.1 only)
    CG_PHOTO_DIR=<project>\.dev\photos      the existing photos (unless backend\.env sets CG_PHOTO_DIR)
  Optional: CGVMS_SITE (the name gate PCs use; default: this PC's computer name).

  Runtime files in .prod\: logs\api.log, logs\web.log, logs\caddy.log (previous run: *.1.log),
  caddy-data\ (internal certificate), gate-pc\CenturyGateVMS-root.crt (install on every gate PC).
  MongoDB log: .dev\mongo\mongod.log.

  If the Windows services of setup-production.ps1 are installed (CGVMS-*), this script starts and stops
  those services instead.
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
$services = 'CGVMS-MongoDB', 'CGVMS-API', 'CGVMS-Web', 'CGVMS-Proxy'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Say([string]$Message) { Write-Host $Message }
function Fail([string]$Message) { Write-Host ''; Write-Host "ERROR: $Message" -ForegroundColor Red; exit 1 }

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-LocalPort([int]$Port) {
    $tcp = New-Object Net.Sockets.TcpClient
    try { $tcp.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $tcp.Dispose() }
}

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

function Find-Caddy {
    foreach ($candidate in @($env:CGVMS_CADDY, (Join-Path $run 'caddy.exe'), 'C:\CenturyGateVMS\tools\caddy.exe')) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return (Resolve-Path -LiteralPath $candidate).Path }
    }
    $onPath = Get-Command caddy.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
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

function Use-Services { return [bool](Get-Service -Name 'CGVMS-API' -ErrorAction SilentlyContinue) }

# ================================================================================================= services
if (Use-Services) {
    Say 'The Windows services of setup-production.ps1 are installed: using them.'
    if ($Action -eq 'start') {
        foreach ($svc in $services) { Say "  start $svc"; Start-Service -Name $svc }
    } elseif ($Action -eq 'stop') {
        foreach ($svc in ($services[($services.Count - 1)..0])) { Say "  stop $svc"; Stop-Service -Name $svc -ErrorAction SilentlyContinue }
        exit 0
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1')
    exit $LASTEXITCODE
}

# ================================================================================================= stop
if ($Action -eq 'stop') {
    foreach ($item in @(@('Caddy', 'caddy', 443), @('Web', 'node', 3000), @('API', 'python', 8000))) {
        $name, $program, $port = $item
        $p = Get-Ours $name $program
        if (-not $p) {
            # Started by an earlier run without a process file: only a matching program on the port.
            $owner = Get-PortOwner $port
            if ($owner -and $owner.ProcessName -eq $program -and $port -ne 3000 -and $port -ne 8000) { $p = $owner }
        }
        if ($p) { Stop-Process -Id $p.Id -Force; Say "  $name stopped." } else { Say "  $name was not running." }
    }
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
$caddy = Find-Caddy
$missing = @()
if (-not (Test-Path -LiteralPath $python)) { $missing += "Python environment $python (README, Local development)" }
if (-not (Test-Path -LiteralPath $node)) { $missing += 'Node.js (nodejs.org)' }
if (-not (Test-Path (Join-Path $app 'frontend\node_modules'))) { $missing += 'frontend dependencies: cd frontend; npm ci' }
if (-not (Test-Path (Join-Path $app 'backend\.env'))) { $missing += 'backend\.env (copy backend\.env.example)' }
if (-not $caddy) { $missing += "caddy.exe: download Caddy for Windows amd64 from caddyserver.com/download and save it as $run\caddy.exe" }
if ($missing) { Say 'Missing:'; $missing | ForEach-Object { Say "  - $_" }; Fail 'Install the missing parts, then start again.' }
$pids = Read-Pids

# Development servers hold the same ports: refuse instead of guessing.
foreach ($item in @(@('API', 'python', 8000), @('Web', 'node', 3000))) {
    $name, $program, $port = $item
    if ((Get-PortOwner $port) -and -not (Get-Ours $name $program)) {
        Fail "Port $port is already in use (a development server from start-dev.bat?). Close the 'CGVMS API' / 'CGVMS Web' windows first."
    }
}

Say ''
Say '[1/5] MongoDB (127.0.0.1:27018, data in .dev\mongo) ...'
$ErrorActionPreference = 'Continue'
& $python (Join-Path $app 'scripts\dev_mongo.py') start
$mongoExit = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($mongoExit -ne 0) { Fail "MongoDB did not start; see $app\.dev\mongo\mongod.log" }

Say ''
Say '[2/5] Web production build ...'
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
Say '[3/5] API (127.0.0.1:8000, production server) ...'
if (Get-Ours 'API' 'python') {
    Say '      already running.'
} else {
    $envText = Get-Content -LiteralPath (Join-Path $app 'backend\.env') -Raw
    $env:CG_ENVIRONMENT = 'production'
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
Say '[4/5] Web (127.0.0.1:3000, next start) ...'
if (Get-Ours 'Web' 'node') {
    Say '      already running.'
} else {
    $env:NODE_ENV = 'production'
    $env:NEXT_TELEMETRY_DISABLED = '1'
    $webLog = New-Log 'web'
    $p = Start-Process -FilePath $node `
        -ArgumentList 'node_modules\next\dist\bin\next', 'start', '--hostname', '127.0.0.1', '--port', '3000' `
        -WorkingDirectory (Join-Path $app 'frontend') -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $webLog -RedirectStandardError (Join-Path $logs 'web.err.log')
    $pids['Web'] = $p.Id; Save-Pids $pids
    Wait-Until { Test-Url 'http://127.0.0.1:3000/login' } $p 60 'The web server' $webLog
    Say "      started (log: $webLog)."
}

Say ''
Say "[5/5] HTTPS for the gate PCs (https://$site, Caddy) ..."
$caddyDir = Join-Path $app 'deploy\windows\caddy'
if (Get-Ours 'Caddy' 'caddy') {
    Say '      already running.'
} else {
    if (Get-PortOwner 443) { Fail "Port 443 is used by another program ($((Get-PortOwner 443).ProcessName))." }
    $env:CGVMS_SITE = $site
    $env:CGVMS_TLS_MODE = 'internal'
    $env:CGVMS_CADDY_DATA = Join-Path $run 'caddy-data'
    $caddyLog = New-Log 'caddy'
    $p = Start-Process -FilePath $caddy -ArgumentList 'run', '--config', 'Caddyfile' -WorkingDirectory $caddyDir `
        -WindowStyle Hidden -PassThru -RedirectStandardError $caddyLog -RedirectStandardOutput (Join-Path $logs 'caddy.out.log')
    $pids['Caddy'] = $p.Id; Save-Pids $pids
    Wait-Until { Test-LocalPort 443 } $p 30 'Caddy' $caddyLog
    Say "      started (log: $caddyLog)."
}

# Internal certificate: trusted on this PC (health check, browser here), copied for the gate PCs.
$rootCrt = Join-Path $run 'caddy-data\pki\authorities\local\root.crt'
$deadline = (Get-Date).AddSeconds(30)
while (-not (Test-Path -LiteralPath $rootCrt) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
$admin = Test-Admin
if (Test-Path -LiteralPath $rootCrt) {
    $gateDir = Join-Path $run 'gate-pc'
    New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
    Copy-Item -LiteralPath $rootCrt -Destination (Join-Path $gateDir 'CenturyGateVMS-root.crt') -Force
    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($rootCrt)
    if (-not (Get-ChildItem Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $cert.Thumbprint)) {
        if ($admin) {
            Import-Certificate -FilePath $rootCrt -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
            Say '      the internal certificate is now trusted on this PC.'
        } else {
            Say '      NOTE: run start-production.bat once as Administrator to trust the internal certificate on this PC.'
        }
    }
}
# Firewall: only Caddy (80/443) is reachable from the network; 3000, 8000 and 27018 listen on 127.0.0.1 only.
$rule = Get-NetFirewallRule -DisplayName 'Century Gate VMS (HTTPS)' -ErrorAction SilentlyContinue
if (-not $rule) {
    if ($admin) {
        New-NetFirewallRule -DisplayName 'Century Gate VMS (HTTPS)' -Direction Inbound -Action Allow -Protocol TCP `
            -LocalPort 443, 80 -Program $caddy -Profile Domain, Private | Out-Null
        Say '      Windows Firewall: HTTPS (443) and the HTTP redirect (80) are allowed for Caddy (Domain/Private networks).'
    } else {
        Say '      NOTE: run start-production.bat once as Administrator to allow HTTPS in Windows Firewall.'
    }
}
if (Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public') {
    Say '      NOTE: a network of this PC is set to "Public": Windows blocks gate PCs there.'
    Say '            Settings > Network & internet > (the network) > Network profile type: Private.'
}

Say ''
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1')
Say ''
Say 'Century Gate VMS is running in production mode.'
Say "  Gate PCs:   https://$site     (install $run\gate-pc\CenturyGateVMS-root.crt on each once)"
Say '  This PC:    http://localhost:3000'
Say "  Logs:       $logs   and   $app\.dev\mongo\mongod.log"
Say 'The programs keep running when this window closes; they stop at sign-out or shutdown (stop-production.bat stops them).'
exit 0
