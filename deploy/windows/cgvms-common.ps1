# Shared helpers for the Century Gate VMS operations scripts (dot-sourced; Windows PowerShell 5.1).
# Nothing here reads or prints passwords.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$script:EventSource = 'CenturyGateVMS'

# The application runs from this repository as normal processes (start-production.bat).
# Everything comes from the project itself: backend\.env, the development MongoDB instance on 127.0.0.1:27018
# (scripts\dev_mongo.py, data in .dev\mongo), runtime files (logs, backups) in .prod\. Gate PCs use plain
# HTTP on port 3000 (no Caddy, no certificate): the health check reads readiness through the web server.
function Get-CgvmsLocalConfig {
    $app = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path.TrimEnd('\')
    $photoDir = Join-Path $app '.dev\photos'                    # the API's own default (core/config.py)
    $envFile = Join-Path $app 'backend\.env'
    if (Test-Path -LiteralPath $envFile) {
        $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*CG_PHOTO_DIR\s*=' } | Select-Object -Last 1
        if ($line) { $photoDir = ($line -replace '^\s*CG_PHOTO_DIR\s*=\s*', '').Trim().Trim('"') }
    }
    $site = if ($env:CGVMS_SITE) { $env:CGVMS_SITE } else { $env:COMPUTERNAME.ToLowerInvariant() }
    $toolsBin = Get-ChildItem 'C:\Program Files\MongoDB\Tools' -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'bin' } |
        Where-Object { Test-Path (Join-Path $_ 'mongodump.exe') } | Select-Object -First 1
    if (-not $toolsBin) {
        $onPath = Get-Command mongodump.exe -ErrorAction SilentlyContinue
        $toolsBin = if ($onPath) { Split-Path $onPath.Source } else { Join-Path $app '.prod\mongodb-database-tools\bin' }
    }
    $root = Join-Path $app '.prod'
    return @{
        AppDir = $app; Root = $root; PhotoDir = $photoDir; MongoPort = 27018
        MongoUri = 'mongodb://127.0.0.1:27018/?directConnection=true'
        MongoToolsBin = $toolsBin; SiteName = $site; HealthUrl = 'http://127.0.0.1:3000/api/v1/health/ready'
        BackupDestination = $(if ($env:CGVMS_BACKUP) { $env:CGVMS_BACKUP } else { Join-Path $root 'backups' })
        BackupKeepDays = 35; BackupKeepMonthly = 12; BackupLocalKeep = 3; BackupMaxAgeHours = 26
        DiskMinFreePercent = 15; DiskMinFreeGB = 10; StatusKeepDays = 60
    }
}

# Why the production web server must NOT listen on 0.0.0.0:3000 now, or '' when it may.
# Plain HTTP is only for a trusted LAN: every connected network (Get-NetConnectionProfile) must be Private or
# Domain. A listener on 0.0.0.0 answers on every interface, so one Public network (a hotspot, a guest Wi-Fi,
# an unidentified virtual adapter) is enough to refuse; no connected network at all is refused too (fail closed).
function Get-LanExposureProblem($Profiles) {
    $all = @($Profiles | Where-Object { $_ })
    if (-not $all) {
        return 'Production HTTP-LAN mode requires the server to be connected to a trusted Private or Domain network. ' +
               'No connected network was found, so the VMS was not started on 0.0.0.0:3000.'
    }
    $untrusted = @($all | Where-Object { "$($_.NetworkCategory)" -notin 'Private', 'DomainAuthenticated' })
    if ($untrusted) {
        $names = ($untrusted | ForEach-Object { "'$($_.Name)' on $($_.InterfaceAlias) ($($_.NetworkCategory))" }) -join ', '
        return 'Production HTTP-LAN mode requires the server to be connected to a trusted Private or Domain network. ' +
               "The active network is Public ($names), so the VMS was not started on 0.0.0.0:3000."
    }
    return ''
}

function Get-StatusDir($cfg) {
    $dir = Join-Path $cfg.Root 'status'
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    return $dir
}

# One line per event in status\<name>-yyyyMMdd.log (old files are removed by Remove-OldStatusLogs).
function Write-StatusLog($cfg, [string]$Name, [string]$Message) {
    $file = Join-Path (Get-StatusDir $cfg) ("{0}-{1:yyyyMMdd}.log" -f $Name, (Get-Date))
    Add-Content -LiteralPath $file -Value ("{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $Message) -Encoding UTF8
    Write-Host $Message
}

function Remove-OldStatusLogs($cfg) {
    $keep = if ($cfg.ContainsKey('StatusKeepDays')) { [int]$cfg.StatusKeepDays } else { 60 }
    Get-ChildItem -LiteralPath (Get-StatusDir $cfg) -Filter '*.log' -File |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$keep) } | Remove-Item -Force
}

# Windows Application event log, only if an administrator registered the source "CenturyGateVMS"
# (New-EventLog -LogName Application -Source CenturyGateVMS). Monitoring tools and Task Scheduler
# triggers can watch these IDs: 1xxx health, 2xxx backup.
function Write-CgvmsEvent([string]$Type, [int]$Id, [string]$Message) {
    try {
        if ([System.Diagnostics.EventLog]::SourceExists($script:EventSource)) {
            Write-EventLog -LogName Application -Source $script:EventSource -EntryType $Type -EventId $Id -Message $Message
        }
    } catch {
        # Not registered or no rights (e.g. a test run): the status log still has the message.
    }
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments, [string]$What) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)." }
}

function Get-FileSha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# Runs a native program, sends each output line (stdout and stderr) to the status log, returns the exit code.
# Windows PowerShell 5.1 turns stderr lines into errors under ErrorActionPreference=Stop, so it is relaxed here.
function Invoke-Logged($cfg, [string]$LogName, [string]$FilePath, [string[]]$Arguments, [string]$Prefix = '  ') {
    $ErrorActionPreference = 'Continue'
    & $FilePath @Arguments 2>&1 | ForEach-Object { Write-StatusLog $cfg $LogName "$Prefix$_" }
    return $LASTEXITCODE
}
