<#
.SYNOPSIS
  Installs Century Gate VMS as Windows services on the server (run as Administrator).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File install-services.ps1 [-ConfigPath ...] [-DryRun]
      powershell -NoProfile -ExecutionPolicy Bypass -File install-services.ps1 -Uninstall      (keeps all data)

  Normally run by setup-production.ps1. Run it again after changing SiteName, TlsMode or AppDir in
  cgvms.psd1: it rewrites the service settings and restarts the services. It:
    1. checks that everything it needs is in place (and stops with a clear message if not);
    2. creates the folders under Root;
    3. writes Root\services\<name>.xml from deploy\windows\services (filling in AppDir, SiteName, TlsMode)
       and registers four services, each running under its own virtual account (NT SERVICE\<name>),
       starting automatically and restarting after a failure:
         CGVMS-MongoDB  mongod with mongodb\mongod.conf (TLS, login, 127.0.0.1:27018)
         CGVMS-API      python -m app.serve (127.0.0.1:8000)          needs CGVMS-MongoDB
         CGVMS-Web      next start          (127.0.0.1:3000)          needs CGVMS-API
         CGVMS-Proxy    Caddy, HTTPS on 443 (80 only redirects)       the only one the network reaches
    4. sets folder permissions: application code read-only for the services; backend\.env, secrets,
       certificates and the photo folder readable only by the service that needs them (and
       Administrators/SYSTEM); nothing is writable by ordinary users;
    5. registers the event log source "CenturyGateVMS" and opens ports 443 and 80 in Windows Firewall;
    6. starts the services (restarts the ones already running, so new settings apply) and runs the health check.
  -DryRun prints every action without changing anything.
#>
param(
    [string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1',
    [switch]$DryRun,
    [switch]$Uninstall
)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsConfig $ConfigPath
$root = $cfg.Root
$app = $cfg.AppDir
$services = 'CGVMS-MongoDB', 'CGVMS-API', 'CGVMS-Web', 'CGVMS-Proxy'
$winswServices = 'CGVMS-API', 'CGVMS-Web', 'CGVMS-Proxy'
$admins = '*S-1-5-32-544'      # Administrators (by SID: works in any Windows language)
$system = '*S-1-5-18'          # SYSTEM

function Step([string]$What, [scriptblock]$Action) {
    if ($DryRun) { Write-Host "[dry run] $What"; return }
    Write-Host $What
    & $Action
}

function Acl([string]$Path, [string[]]$Grants, [switch]$Reset) {
    # /inheritance:r removes inherited rights (e.g. "Authenticated Users: Modify" from C:\).
    $icaclsArgs = @($Path)
    if ($Reset) { $icaclsArgs += '/inheritance:r', '/grant:r', "${admins}:(OI)(CI)F", "${system}:(OI)(CI)F" }
    foreach ($g in $Grants) { $icaclsArgs += '/grant', $g }
    Step "icacls $($icaclsArgs -join ' ')" {
        & icacls.exe @icaclsArgs | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls failed for $Path" }
    }.GetNewClosure()
}

if (-not $DryRun) {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this script as Administrator.'
    }
}

# ------------------------------------------------------------------------------------------ uninstall
if ($Uninstall) {
    foreach ($svc in ($services | Sort-Object -Descending)) {
        if (Get-Service -Name $svc -ErrorAction SilentlyContinue) {
            Step "Stop and remove service $svc" {
                Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
                & sc.exe delete $svc | Out-Null
            }.GetNewClosure()
        }
    }
    Write-Host 'Services removed. Data, photos, backups, certificates and secrets were NOT touched.'
    exit 0
}

# ------------------------------------------------------------------------------------------ 1. checks
$python = Join-Path $app 'backend\.venv\Scripts\python.exe'
$node = 'C:\Program Files\nodejs\node.exe'
$mongod = Join-Path $cfg.MongoBin 'mongod.exe'
$envFile = Join-Path $app 'backend\.env'
$required = [ordered]@{
    'Application folder (AppDir)'                 = (Join-Path $app 'deploy\windows\services')
    'API Python environment (README step 3)'      = $python
    'Node.js (installed for all users)'           = $node
    'Next.js production build (npm run build)'    = (Join-Path $app 'frontend\.next\BUILD_ID')
    'MongoDB server'                              = $mongod
    'mongod.conf (from deploy\mongodb)'           = (Join-Path $root 'mongodb\mongod.conf')
    'MongoDB server certificate (prepare)'        = (Join-Path $root 'tls\mongodb\server.pem')
    'MongoDB CA certificate (prepare)'            = (Join-Path $root 'tls\mongodb\ca.pem')
    'MongoDB replica-set key file (prepare)'      = (Join-Path $root 'tls\mongodb\mongodb.keyfile')
    'API settings backend\.env (api.env.template)'    = $envFile
    'Photo folder (PhotoDir)'                     = $cfg.PhotoDir
    'Caddy (tools\caddy.exe)'                     = (Join-Path $root 'tools\caddy.exe')
    'WinSW (tools\WinSW-x64.exe)'                 = (Join-Path $root 'tools\WinSW-x64.exe')
    'MongoDB Database Tools (mongodump)'          = (Join-Path $cfg.MongoToolsBin 'mongodump.exe')
}
if ($cfg.TlsMode -eq 'company') {
    $required['HTTPS certificate (tls\web\cert.pem)'] = (Join-Path $root 'tls\web\cert.pem')
    $required['HTTPS certificate key (tls\web\key.pem)'] = (Join-Path $root 'tls\web\key.pem')
}
$missing = @($required.GetEnumerator() | Where-Object { -not (Test-Path -LiteralPath $_.Value) })
foreach ($m in $missing) { Write-Host "MISSING: $($m.Key): $($m.Value)" }
if ($missing.Count -and -not $DryRun) { throw "$($missing.Count) prerequisite(s) missing; see README 'Production operations'." }
if (Test-Path -LiteralPath $envFile) {
    $envText = Get-Content -LiteralPath $envFile -Raw
    if ($envText -notmatch '(?m)^CG_ENVIRONMENT=production\s*$') { throw 'backend\.env must contain CG_ENVIRONMENT=production.' }
    if ($envText -match 'PASTE-FROM') { throw 'backend\.env still contains the placeholder for CG_MONGO_URI.' }
}
Write-Host "Application: $app   Data: $root   Site: https://$($cfg.SiteName) ($($cfg.TlsMode) certificate)"

# ------------------------------------------------------------------------------------------ 2. folders
foreach ($dir in 'services', 'logs\api', 'logs\web', 'logs\proxy', 'mongodb\data', 'mongodb\log', 'caddy-data',
                 'tls\web', 'secrets', 'status', 'backup\staging', 'restore-test', 'config') {
    $path = Join-Path $root $dir
    if (-not (Test-Path -LiteralPath $path)) { Step "Create $path" { New-Item -ItemType Directory -Path $path | Out-Null }.GetNewClosure() }
}

# ------------------------------------------------------------------------------------------ 3. services
$mongodBin = "`"$mongod`" --config `"$(Join-Path $root 'mongodb\mongod.conf')`" --service"
if (-not (Get-Service -Name 'CGVMS-MongoDB' -ErrorAction SilentlyContinue)) {
    Step 'Register service CGVMS-MongoDB' {
        & sc.exe create CGVMS-MongoDB binPath= $mongodBin start= delayed-auto obj= 'NT SERVICE\CGVMS-MongoDB' `
            DisplayName= 'Century Gate VMS - MongoDB' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Registering CGVMS-MongoDB failed.' }
        & sc.exe description CGVMS-MongoDB 'Century Gate visitor management database (127.0.0.1:27018, TLS, login required).' | Out-Null
        & sc.exe failure CGVMS-MongoDB reset= 3600 actions= restart/10000/restart/30000/restart/120000 | Out-Null
    }.GetNewClosure()
}
$placeholders = @{ '__APP_DIR__' = $app; '__SITE__' = $cfg.SiteName; '__TLS_MODE__' = $cfg.TlsMode }
foreach ($svc in $winswServices) {
    $exe = Join-Path $root "services\$svc.exe"
    $xml = Join-Path $root "services\$svc.xml"
    $text = Get-Content -LiteralPath (Join-Path $app "deploy\windows\services\$svc.xml") -Raw
    foreach ($key in $placeholders.Keys) { $text = $text.Replace($key, [Security.SecurityElement]::Escape([string]$placeholders[$key])) }
    Step "Write $xml" {
        [IO.File]::WriteAllText($xml, $text, (New-Object Text.UTF8Encoding($false)))
        # The running service locks its copy of WinSW: copy it only when it is not there yet.
        if (-not (Test-Path -LiteralPath $exe)) { Copy-Item -LiteralPath (Join-Path $root 'tools\WinSW-x64.exe') -Destination $exe }
    }.GetNewClosure()
    if (-not (Get-Service -Name $svc -ErrorAction SilentlyContinue)) {
        Step "Register service $svc (virtual account NT SERVICE\$svc)" {
            & $exe install | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Registering $svc failed." }
            & sc.exe config $svc obj= "NT SERVICE\$svc" | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Setting the account of $svc failed." }
        }.GetNewClosure()
    }
}

# ------------------------------------------------------------------------------------------ 4. permissions
$api = 'NT SERVICE\CGVMS-API'; $web = 'NT SERVICE\CGVMS-Web'; $proxy = 'NT SERVICE\CGVMS-Proxy'; $db = 'NT SERVICE\CGVMS-MongoDB'
Acl $root -Reset -Grants @("${api}:(RX)", "${web}:(RX)", "${proxy}:(RX)", "${db}:(RX)")        # traverse the top folder only
# Application code: read-only for the services, not changeable by ordinary users; the administrator who
# installs keeps the right to update it (git pull, npm run build) without an elevated prompt.
$installer = "$env:USERDOMAIN\$env:USERNAME"
Acl $app -Reset -Grants @("${installer}:(OI)(CI)M", "${api}:(OI)(CI)RX", "${web}:(OI)(CI)RX", "${proxy}:(OI)(CI)RX")
Acl (Join-Path $root 'services') -Grants @("${api}:(OI)(CI)RX", "${web}:(OI)(CI)RX", "${proxy}:(OI)(CI)RX")
Acl (Join-Path $root 'tools') -Grants @("${proxy}:(OI)(CI)RX")
Acl $envFile -Reset -Grants @("${api}:(R)")
Acl (Join-Path $app 'frontend\.next') -Grants @("${web}:(OI)(CI)M")                                      # Next.js runtime cache
Acl (Join-Path $root 'logs\api') -Grants @("${api}:(OI)(CI)M")
Acl (Join-Path $root 'logs\web') -Grants @("${web}:(OI)(CI)M")
Acl (Join-Path $root 'logs\proxy') -Grants @("${proxy}:(OI)(CI)M")
Acl (Join-Path $root 'mongodb') -Reset -Grants @("${db}:(OI)(CI)M")
Acl (Join-Path $root 'tls\mongodb') -Reset -Grants @("${db}:(OI)(CI)R")
Acl (Join-Path $root 'tls\mongodb\ca.pem') -Grants @("${api}:(R)")                                  # the API validates the database
Acl (Join-Path $root 'tls\web') -Reset -Grants @("${proxy}:(OI)(CI)R")
Acl (Join-Path $root 'caddy-data') -Reset -Grants @("${proxy}:(OI)(CI)M")
Acl (Join-Path $root 'secrets') -Reset
Acl (Join-Path $root 'status') -Reset
Acl (Join-Path $root 'backup') -Reset
Acl (Join-Path $root 'restore-test') -Reset
Acl $cfg.PhotoDir -Reset -Grants @("${api}:(OI)(CI)M")

# ------------------------------------------------------------------------------------------ 5. event log, firewall
Step 'Register event log source CenturyGateVMS' {
    if (-not [Diagnostics.EventLog]::SourceExists('CenturyGateVMS')) { New-EventLog -LogName Application -Source 'CenturyGateVMS' }
}
Step 'Allow HTTPS (443) and HTTP redirect (80) to Caddy in Windows Firewall' {
    Get-NetFirewallRule -DisplayName 'Century Gate VMS (HTTPS)' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName 'Century Gate VMS (HTTPS)' -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort 443, 80 -Program (Join-Path $root 'tools\caddy.exe') -Profile Domain, Private | Out-Null
}

# ------------------------------------------------------------------------------------------ 6. start
# MongoDB is only started; the other three are restarted when already running, so rewritten settings apply.
foreach ($svc in $services) {
    $running = $false
    if (-not $DryRun) { $running = (Get-Service -Name $svc).Status -eq 'Running' }
    if ($running -and $svc -ne 'CGVMS-MongoDB') { Step "Restart $svc" { Restart-Service -Name $svc }.GetNewClosure() }
    else { Step "Start $svc" { Start-Service -Name $svc }.GetNewClosure() }
}
if (-not $DryRun) {
    Start-Sleep -Seconds 10
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'check-health.ps1') -ConfigPath $ConfigPath
}
Write-Host 'Done. Next: register-tasks.ps1 (nightly backup, health check), then open the site from a gate PC.'
