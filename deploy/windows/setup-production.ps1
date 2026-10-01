<#
.SYNOPSIS
  First-time production setup of Century Gate VMS on one Windows 11 PC (run as Administrator).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File setup-production.ps1
          [-SiteName <name gate PCs type>] [-PhotoDir <folder>] [-BackupDestination <folder or share>]
          [-OrganizationName "Century Gate"] [-TlsMode internal|company] [-Root C:\CenturyGateVMS] [-Rebuild]

  Runs from wherever the application is (this repository); nothing is copied. Data (database, logs,
  secrets, certificates, tools, local backups) goes under -Root (default C:\CenturyGateVMS).
  Defaults: SiteName = this PC's computer name, internal HTTPS certificate, photos in
  D:\CenturyGateVMS-Photos when a D: drive exists (otherwise Root\photos), backups in Root\backups.

     1. checks the software and tools (stops with what is missing and where to get it);
     2. API Python environment (pip install);
     3. web production build (npm ci, npm run build; skipped when a build exists, unless -Rebuild);
     4. Root\config\cgvms.psd1 (the only settings file the administrator edits);
     5. photo folder;
     6. MongoDB certificates and key file (cgvms_mongo.py prepare);
     7. Root\mongodb\mongod.conf;
     8. database accounts (cgvms_mongo.py init, with a temporary MongoDB process);
     9. backend\.env (database connection, photo folder, organisation name, new CG_SECRETS_KEY);
    10. schema (migrate.ps1) and the first administrator (asks for the password);
    11. Windows services (install-services.ps1);
    12. internal certificate: trusted on this PC, root certificate copied for the gate PCs;
    13. scheduled tasks (nightly backup, health check), health check, optional first backup.

  Safe to run again: finished steps are skipped and nothing existing is overwritten (backend\.env,
  cgvms.psd1, mongod.conf, certificates and secrets are kept as they are).
#>
param(
    [string]$Root = 'C:\CenturyGateVMS',
    [string]$SiteName = '',
    [string]$PhotoDir = '',
    [string]$BackupDestination = '',
    [string]$OrganizationName = 'Century Gate',
    [ValidateSet('internal', 'company')][string]$TlsMode = 'internal',
    [string]$PythonExe = 'C:\Program Files\Python312\python.exe',
    [string]$AdminUsername = 'admin',
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$scripts = $PSScriptRoot
$app = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path.TrimEnd('\')
$configPath = Join-Path $Root 'config\cgvms.psd1'
$tlsMongo = Join-Path $Root 'tls\mongodb'
$secrets = Join-Path $Root 'secrets'
$mongoConf = Join-Path $Root 'mongodb\mongod.conf'
$venvPython = Join-Path $app 'backend\.venv\Scripts\python.exe'
$envFile = Join-Path $app 'backend\.env'
$nodeDir = 'C:\Program Files\nodejs'
$mongoPort = 27018
$script:step = 0

function Step([string]$Title) {
    $script:step++
    Write-Host ''
    Write-Host ("[{0,2}/13] {1}" -f $script:step, $Title) -ForegroundColor Cyan
}
function Done([string]$Message) { Write-Host "        $Message" }
function Warn([string]$Message) { Write-Host "        WARNING: $Message" -ForegroundColor Yellow }

# Runs a native program; Windows PowerShell 5.1 would otherwise turn its stderr warnings into errors.
function Run([string]$FilePath, [string[]]$Arguments, [string]$What) {
    $ErrorActionPreference = 'Continue'
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}
function Run-Script([string]$Name, [string[]]$Extra = @()) {
    Run 'powershell.exe' (@('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $scripts $Name), '-ConfigPath', $configPath) + $Extra) $Name
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Test-Port([int]$Port) {
    $tcp = New-Object Net.Sockets.TcpClient
    try { $tcp.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $tcp.Dispose() }
}

function Confirm-Yes([string]$Question) {
    $answer = Read-Host "        $Question [Y/n]"
    return ($answer -eq '' -or $answer -match '^[Yy]')
}

# ============================================================================================ 1. checks
Step 'Checking this PC'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script as Administrator.'
}
if ($app.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -and
    -not $app.Equals((Join-Path $Root 'app'), [StringComparison]::OrdinalIgnoreCase)) {
    throw "The application ($app) must not be inside the data folder $Root (only $Root\app is allowed)."
}

$mongoBin = Get-ChildItem 'C:\Program Files\MongoDB\Server' -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName 'bin\mongod.exe') } |
    Sort-Object { [version]($_.Name + '.0') } -Descending | Select-Object -First 1 |
    ForEach-Object { Join-Path $_.FullName 'bin' }
$mongoToolsBin = Join-Path $Root 'tools\mongodb-database-tools\bin'

$missing = New-Object System.Collections.Generic.List[string]
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $missing.Add("Python 3.12 for ALL users -> $PythonExe  (python.org installer, Customize -> 'Install Python 3.12 for all users')")
}
if (-not (Test-Path (Join-Path $nodeDir 'node.exe'))) { $missing.Add("Node.js 24 LTS -> $nodeDir  (nodejs.org MSI)") }
if (-not $mongoBin) {
    $missing.Add("MongoDB Community Server 8.x -> C:\Program Files\MongoDB\Server\8.x  (MSI; UNTICK 'Install MongoD as a Service')")
}
if (-not (Test-Path (Join-Path $mongoToolsBin 'mongodump.exe'))) {
    $missing.Add("MongoDB Database Tools 100.x -> $mongoToolsBin\mongodump.exe  (zip from mongodb.com/try/download/database-tools; unzip and rename the folder)")
}
if (-not (Test-Path (Join-Path $Root 'tools\caddy.exe'))) {
    $missing.Add("Caddy 2.x for Windows amd64 -> $Root\tools\caddy.exe  (caddyserver.com/download; rename the download to caddy.exe)")
}
if (-not (Test-Path (Join-Path $Root 'tools\WinSW-x64.exe'))) {
    $missing.Add("WinSW 2.12 -> $Root\tools\WinSW-x64.exe  (WinSW-x64.exe from github.com/winsw/winsw/releases/tag/v2.12.0)")
}
if ($missing.Count) {
    Write-Host ''
    Write-Host 'Install or download these first, then run this script again:' -ForegroundColor Yellow
    foreach ($m in $missing) { Write-Host "  - $m" }
    exit 1
}
Done "Application: $app"
Done "Python, Node.js, MongoDB ($mongoBin) and the tools in $Root\tools: OK."
if (Test-Port 27017) { Done 'Legacy MongoDB on port 27017 detected: it is not used or changed.' }

# ============================================================================================ 2. Python
Step 'API Python environment'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Run $PythonExe @('-m', 'venv', (Join-Path $app 'backend\.venv')) 'Creating the Python environment'
}
Run $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-q',
    '-r', (Join-Path $app 'backend\requirements.txt'), '-r', (Join-Path $app 'deploy\requirements-ops.txt')) 'pip install'
Done 'Packages installed.'

# ============================================================================================ 3. web build
Step 'Web production build'
$env:Path = "$nodeDir;$env:Path"
$npm = Join-Path $nodeDir 'npm.cmd'
if ($Rebuild -or -not (Test-Path (Join-Path $app 'frontend\.next\BUILD_ID'))) {
    Push-Location (Join-Path $app 'frontend')
    try {
        Run $npm @('ci', '--no-audit', '--no-fund') 'npm ci'
        Run $npm @('run', 'build') 'npm run build'
    } finally { Pop-Location }
    Done 'Built.'
} else {
    Done 'A production build exists (use -Rebuild to build again).'
}

# ============================================================================================ 4. settings
Step 'Settings (config\cgvms.psd1)'
if (Test-Path -LiteralPath $configPath) {
    Done "$configPath exists; kept as it is."
} else {
    if (-not $SiteName) { $SiteName = $env:COMPUTERNAME.ToLowerInvariant() }
    if (-not $PhotoDir) {
        $dDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='D:' AND DriveType=3" -ErrorAction SilentlyContinue
        $PhotoDir = if ($dDrive) { 'D:\CenturyGateVMS-Photos' } else { Join-Path $Root 'photos' }
    }
    if (-not $BackupDestination) { $BackupDestination = Join-Path $Root 'backups' }
    New-Item -ItemType Directory -Force -Path (Split-Path $configPath) | Out-Null
    $text = (Get-Content -LiteralPath (Join-Path $scripts 'cgvms.example.psd1') -Raw).Replace('C:\CenturyGateVMS', $Root)
    $set = [ordered]@{ AppDir = $app; SiteName = $SiteName; TlsMode = $TlsMode; PhotoDir = $PhotoDir; MongoBin = $mongoBin
                       BackupDestination = $BackupDestination }
    foreach ($key in $set.Keys) {
        $value = ([string]$set[$key]).Replace("'", "''")
        $text = [regex]::Replace($text, "(?m)^(\s*)(#\s*)?($key\s*=\s*)'[^']*'", { param($m) $m.Groups[1].Value + $m.Groups[3].Value + "'" + $value + "'" })
    }
    Write-Utf8NoBom $configPath $text
    Done "Written: $configPath (site https://$SiteName, photos $PhotoDir, backups $BackupDestination)"
}
$cfg = Import-PowerShellDataFile -LiteralPath $configPath
$PhotoDir = $cfg.PhotoDir
$SiteName = if ($cfg.ContainsKey('SiteName') -and $cfg.SiteName) { $cfg.SiteName } else { $env:COMPUTERNAME.ToLowerInvariant() }
$TlsMode = if ($cfg.ContainsKey('TlsMode') -and $cfg.TlsMode) { $cfg.TlsMode } else { 'internal' }
if ($cfg.ContainsKey('AppDir') -and $cfg.AppDir -and $cfg.AppDir.TrimEnd('\') -ne $app) {
    throw "cgvms.psd1 says AppDir = $($cfg.AppDir), but this script runs from $app. Run the script in AppDir, or fix AppDir."
}

# ============================================================================================ 5. photos
Step 'Photo folder'
New-Item -ItemType Directory -Force -Path $PhotoDir | Out-Null
Done $PhotoDir

# ============================================================================================ 6. certificates
Step 'Database certificates and key file'
Push-Location $app
try {
    Run $venvPython @('deploy\mongodb\cgvms_mongo.py', 'prepare', '--tls-dir', $tlsMongo) 'cgvms_mongo.py prepare'
} finally { Pop-Location }

# ============================================================================================ 7. mongod.conf
Step 'MongoDB configuration'
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'mongodb\data'), (Join-Path $Root 'mongodb\log') | Out-Null
if (Test-Path -LiteralPath $mongoConf) {
    Done "$mongoConf exists; kept as it is."
} else {
    $text = (Get-Content -LiteralPath (Join-Path $app 'deploy\mongodb\mongod.conf.template') -Raw).Replace('C:\CenturyGateVMS', $Root)
    Write-Utf8NoBom $mongoConf $text
    Done "Written: $mongoConf"
}

# ============================================================================================ 8-10. database
# The database must run for the accounts, the migration and the first administrator. Before the services
# exist, a temporary mongod is started here and shut down cleanly afterwards.
$tempMongod = $null
$serviceInstalled = [bool](Get-Service -Name 'CGVMS-MongoDB' -ErrorAction SilentlyContinue)
try {
    Step 'Database accounts'
    if (Test-Port $mongoPort) {
        Done "MongoDB already answers on port $mongoPort."
    } elseif ($serviceInstalled) {
        Start-Service -Name 'CGVMS-MongoDB'
        Done 'Started the service CGVMS-MongoDB.'
    } else {
        $tempMongod = Start-Process -FilePath (Join-Path $mongoBin 'mongod.exe') -ArgumentList '--config', "`"$mongoConf`"" `
            -WindowStyle Hidden -PassThru
        Done "Started a temporary MongoDB (process $($tempMongod.Id))."
    }
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Port $mongoPort)) {
        if ($tempMongod -and $tempMongod.HasExited) { throw "MongoDB stopped at once; see $Root\mongodb\log\mongod.log" }
        if ((Get-Date) -gt $deadline) { throw "MongoDB did not answer on port $mongoPort; see $Root\mongodb\log\mongod.log" }
        Start-Sleep -Seconds 1
    }
    Push-Location $app
    try {
        Run $venvPython @('deploy\mongodb\cgvms_mongo.py', 'init', '--tls-dir', $tlsMongo, '--secrets-dir', $secrets, '--port', "$mongoPort") 'cgvms_mongo.py init'
    } finally { Pop-Location }

    Step 'API settings (backend\.env)'
    $appUri = (Get-Content -LiteralPath (Join-Path $secrets 'cgvms_app.uri.txt') -Raw).Trim()
    if (Test-Path -LiteralPath $envFile) {
        $text = Get-Content -LiteralPath $envFile -Raw
        if ($text -match 'PASTE-FROM') {
            $text = [regex]::Replace($text, '(?m)^CG_MONGO_URI=.*$', { param($m) "CG_MONGO_URI=$appUri" })
            Write-Utf8NoBom $envFile $text
            Done 'Filled in CG_MONGO_URI; everything else kept.'
        } else {
            Done "$envFile exists; kept as it is."
        }
    } else {
        Push-Location (Join-Path $app 'backend')
        try {
            $ErrorActionPreference = 'Continue'
            $key = (& $venvPython -m app.cli generate-secrets-key | Select-Object -Last 1)
            $ErrorActionPreference = 'Stop'
        } finally { Pop-Location }
        if (-not $key) { throw 'Generating CG_SECRETS_KEY failed.' }
        $values = [ordered]@{ CG_MONGO_URI = $appUri; CG_PHOTO_DIR = $PhotoDir; CG_ORGANIZATION_NAME = $OrganizationName
                              CG_SECRETS_KEY = $key.Trim() }
        $text = Get-Content -LiteralPath (Join-Path $scripts 'api.env.template') -Raw
        foreach ($name in $values.Keys) {
            $line = "$name=$($values[$name])"
            $text = [regex]::Replace($text, "(?m)^$name=.*$", { param($m) $line })
        }
        Write-Utf8NoBom $envFile $text
        Done "Written: $envFile"
        Warn "Copy the CG_SECRETS_KEY line from $envFile into the password manager (saved camera passwords cannot be read without it)."
    }

    Step 'Database schema and first administrator'
    Run-Script 'migrate.ps1'
    $adminMarker = Join-Path $Root 'config\first-admin-created.txt'
    if (Test-Path -LiteralPath $adminMarker) {
        Done 'The first administrator was created earlier.'
    } else {
        Write-Host "        Create the first administrator '$AdminUsername'. Type a strong password (it is not shown)."
        Push-Location (Join-Path $app 'backend')
        try {
            while ($true) {
                $ErrorActionPreference = 'Continue'
                & $venvPython -m app.cli create-admin --username $AdminUsername
                $code = $LASTEXITCODE
                $ErrorActionPreference = 'Stop'
                if ($code -eq 0) { break }
                if (-not (Confirm-Yes 'Creating the administrator failed (see above). Try again?')) {
                    throw "No administrator created. Later: cd `"$app\backend`"; .venv\Scripts\python -m app.cli create-admin --username $AdminUsername"
                }
            }
        } finally { Pop-Location }
        Set-Content -LiteralPath $adminMarker -Value "First administrator '$AdminUsername' created $(Get-Date -Format s)." -Encoding ASCII
    }
} finally {
    if ($tempMongod -and -not $tempMongod.HasExited) {
        Write-Host '        Stopping the temporary MongoDB ...'
        $shutdown = @'
import sys
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ConnectionFailure
password = open(sys.argv[1], encoding="utf-8").read().strip()
client = MongoClient(host="localhost", port=int(sys.argv[3]), tls=True, tlsCAFile=sys.argv[2], directConnection=True,
                     username="cgvms_root", password=password, authSource="admin", serverSelectionTimeoutMS=5000)
try:
    client.admin.command("shutdown")
except (AutoReconnect, ConnectionFailure):
    pass
'@
        $ErrorActionPreference = 'Continue'
        $shutdown | & $venvPython - (Join-Path $secrets 'mongodb-root.txt') (Join-Path $tlsMongo 'ca.pem') "$mongoPort"
        $ErrorActionPreference = 'Stop'
        if (-not $tempMongod.WaitForExit(60000)) {
            Warn 'The temporary MongoDB did not stop by itself; ending the process.'
            Stop-Process -Id $tempMongod.Id -Force
        }
    }
}

# ============================================================================================ 11. services
Step 'Windows services'
if ($TlsMode -eq 'company' -and -not (Test-Path (Join-Path $Root 'tls\web\cert.pem'))) {
    throw "TlsMode company: put the certificate in $Root\tls\web\cert.pem and its key in key.pem, then run again."
}
# This PC must reach its own site name for the health check (a computer name always resolves locally).
$resolves = $true
try { [Net.Dns]::GetHostAddresses($SiteName) | Out-Null } catch { $resolves = $false }
if (-not $resolves) {
    $hosts = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
    Add-Content -LiteralPath $hosts -Value "`r`n127.0.0.1`t$SiteName`t# Century Gate VMS (setup-production.ps1)" -Encoding ASCII
    Warn "$SiteName does not resolve: added it to this PC's hosts file. Gate PCs need it too (DNS record or their hosts file)."
}
if ($TlsMode -eq 'internal') { Done 'The first health check below may report the HTTPS proxy until step 12 trusts the certificate.' }
Run-Script 'install-services.ps1'

# ============================================================================================ 12. internal CA
Step 'HTTPS certificate'
if ($TlsMode -eq 'internal') {
    $rootCrt = Join-Path $Root 'caddy-data\pki\authorities\local\root.crt'
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Test-Path -LiteralPath $rootCrt) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (-not (Test-Path -LiteralPath $rootCrt)) { throw "Caddy did not create $rootCrt; see $Root\logs\proxy." }
    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($rootCrt)
    if (-not (Get-ChildItem Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $cert.Thumbprint)) {
        Import-Certificate -FilePath $rootCrt -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
        Done 'Trusted the internal certificate on this PC.'
    }
    $gateDir = Join-Path $Root 'gate-pc'
    New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
    Copy-Item -LiteralPath $rootCrt -Destination (Join-Path $gateDir 'CenturyGateVMS-root.crt') -Force
    Done "Root certificate for the gate PCs: $gateDir\CenturyGateVMS-root.crt (valid until $($cert.NotAfter.ToString('yyyy-MM-dd')))."
} else {
    Done "Company certificate from $Root\tls\web."
}

# ============================================================================================ 13. tasks, checks
Step 'Scheduled tasks, health check, first backup'
Run-Script 'register-tasks.ps1'
$healthy = $false
$deadline = (Get-Date).AddMinutes(2)
do {
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts 'check-health.ps1') -ConfigPath $configPath *> $null
    $healthy = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = 'Stop'
    if (-not $healthy) { Start-Sleep -Seconds 5 }
} while (-not $healthy -and (Get-Date) -lt $deadline)
if (-not $healthy) {
    Write-Host '        Health check (on a new installation "no successful backup" is expected until the first backup):'
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts 'check-health.ps1') -ConfigPath $configPath
    $ErrorActionPreference = 'Stop'
}
if (Confirm-Yes 'Run the first backup now (takes a minute)?') {
    $ErrorActionPreference = 'Continue'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts 'backup.ps1') -ConfigPath $configPath
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scripts 'check-health.ps1') -ConfigPath $configPath
    $ErrorActionPreference = 'Stop'
}

# ============================================================================================ summary
$cfg = Import-PowerShellDataFile -LiteralPath $configPath
$backupDir = if ($cfg.ContainsKey('BackupDestination') -and $cfg.BackupDestination) { $cfg.BackupDestination } else { Join-Path $Root 'backups' }
Write-Host ''
Write-Host "Setup finished. Gate PCs open:  https://$SiteName" -ForegroundColor Green
Write-Host 'Still to do by hand:'
$todo = New-Object System.Collections.Generic.List[string]
if (Test-Path -LiteralPath (Join-Path $tlsMongo 'ca.key')) {
    $todo.Add("Move $tlsMongo\ca.key OFF this PC (USB key in the safe). It is only needed to renew the database certificate.")
}
$todo.Add("Put the contents of $secrets\mongodb-root.txt and the CG_SECRETS_KEY line of backend\.env into the password manager.")
if ($TlsMode -eq 'internal') {
    $todo.Add("On every gate PC install $Root\gate-pc\CenturyGateVMS-root.crt once: double-click -> Install Certificate -> Local Machine -> 'Trusted Root Certification Authorities'.")
}
$todo.Add("Check a gate PC can reach https://$SiteName (if not: a DNS record, or '<this PC's IP> $SiteName' in the gate PC's hosts file).")
$todo.Add("Backups go to $backupDir. Copy that folder to another disk or PC regularly.")
$todo.Add("Log in as '$AdminUsername' from a gate PC; there must be no certificate warning.")
$i = 0
foreach ($t in $todo) { $i++; Write-Host "  $i. $t" }
Write-Host ''
Write-Host "Start / stop / restart: start-production.bat, stop-production.bat, restart-production.bat in $scripts (as Administrator)."
