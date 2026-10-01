# Shared helpers for the Century Gate VMS operations scripts (dot-sourced; Windows PowerShell 5.1).
# Nothing here reads or prints passwords.

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 3

$script:EventSource = 'CenturyGateVMS'

function Get-CgvmsConfig([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Configuration file not found: $Path (copy deploy\windows\cgvms.example.psd1 there and adjust it)."
    }
    $cfg = Import-PowerShellDataFile -LiteralPath $Path
    foreach ($key in 'Root', 'PhotoDir', 'MongoBin') {
        if (-not $cfg.ContainsKey($key) -or -not $cfg[$key]) { throw "Setting '$key' is missing in $Path." }
    }
    # Optional settings. AppDir: the application folder (this repository); by default the one these scripts are in.
    $defaults = [ordered]@{
        AppDir             = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
        SiteName           = $env:COMPUTERNAME.ToLowerInvariant()
        TlsMode            = 'internal'
        MongoPort          = 27018
        MongoToolsBin      = (Join-Path $cfg.Root 'tools\mongodb-database-tools\bin')
        BackupDestination  = (Join-Path $cfg.Root 'backups')
        BackupKeepDays     = 35
        BackupKeepMonthly  = 12
        BackupLocalKeep    = 3
        BackupMaxAgeHours  = 26
        RestoreTestPort    = 27029
        DiskMinFreePercent = 15
        DiskMinFreeGB      = 10
        StatusKeepDays     = 60
    }
    foreach ($key in $defaults.Keys) {
        if (-not $cfg.ContainsKey($key) -or -not $cfg[$key]) { $cfg[$key] = $defaults[$key] }
    }
    $cfg.AppDir = $cfg.AppDir.TrimEnd('\')
    if (-not $cfg.ContainsKey('HealthUrl') -or -not $cfg.HealthUrl) { $cfg.HealthUrl = "https://$($cfg.SiteName)/api/v1/health/ready" }
    if ($cfg.TlsMode -notin 'internal', 'company') { throw "TlsMode must be 'internal' or 'company' in $Path." }
    if ([int]$cfg.MongoPort -eq 27017) { throw 'MongoPort 27017 is the legacy desktop database service; refusing.' }
    return $cfg
}

function Get-CgvmsPython($cfg) {
    $python = Join-Path $cfg.AppDir 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw "Python environment not found: $python" }
    return $python
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

# Windows Application event log (source registered by install-services.ps1). Monitoring tools and
# Task Scheduler triggers can watch these IDs: 1xxx health, 2xxx backup, 3xxx restore test.
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
