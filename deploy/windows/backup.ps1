<#
.SYNOPSIS
  Century Gate VMS nightly backup: the MongoDB database AND the private photo folder.

.DESCRIPTION
  Run by the scheduled task "CGVMS Backup" (register-tasks.ps1), or by hand:
      powershell -NoProfile -ExecutionPolicy Bypass -File backup.ps1 [-ConfigPath C:\CenturyGateVMS\config\cgvms.psd1]

  1. Rotates the MongoDB log (and removes rotated logs older than 30 days).
  2. mongodump of the whole application instance with --oplog: a consistent point-in-time copy
     (users, visitors, visits, watchlist, directory, audit logs, photo metadata, everything).
     The account and password come from secrets\mongodump.yaml, never from the command line.
  3. Copies NEW photo files to <BackupDestination>\photos. Photos are never changed or deleted by
     the application, so existing backup copies are never overwritten (a damaged live file cannot
     replace a good backup copy). The database is dumped FIRST, so every photo record in the dump
     has its file in the backup.
  4. Adds the non-secret settings (config\cgvms.psd1, mongodb\mongod.conf) under config\, writes
     manifest.json (SHA-256 of the dump, counts) and copies everything to
     <BackupDestination>\database\cgvms-<timestamp>, then re-checks the SHA-256 there.
     Secrets (backend\.env, Root\secrets) are deliberately NOT in the backup: they are kept in the
     password manager, so a stolen backup does not also hand over the keys.
  5. Retention (only folders named cgvms-YYYYMMDD-HHMMSS in <BackupDestination>\database are ever
     deleted): every backup younger than BackupKeepDays, plus the newest backup of each of the last
     BackupKeepMonthly months. Photo backups are never deleted by this script.
  6. Records the result: status\last-backup.json, status\backup-<date>.log and the Windows event
     log (source CenturyGateVMS, 2000 = success, 2001 = failure). Exit code 0 / 1.
  BackupDestination (cgvms.psd1) defaults to Root\backups on this PC. Copy that folder to another
  disk or PC regularly, or point BackupDestination at one: a backup on the same disk dies with it.
#>
param([string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1')

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

# Without the Windows services: the single-PC local mode of start-production.bat (database without login,
# backups in .prod\backups unless CGVMS_BACKUP names another folder).
$cfg = Get-CgvmsSettings $ConfigPath
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$name = "cgvms-$stamp"
$started = Get-Date

function Remove-ExpiredBackups([string]$DatabaseDir) {
    $pattern = '^cgvms-(\d{8})-(\d{6})$'
    $all = Get-ChildItem -LiteralPath $DatabaseDir -Directory | Where-Object { $_.Name -match $pattern } | ForEach-Object {
        [pscustomobject]@{ Dir = $_; When = [datetime]::ParseExact(($_.Name -replace '^cgvms-', ''), 'yyyyMMdd-HHmmss', $null) }
    } | Sort-Object When -Descending
    $keepMonths = @{}
    foreach ($b in $all) {
        $month = $b.When.ToString('yyyy-MM')
        $young = $b.When -gt (Get-Date).AddDays(-[int]$cfg.BackupKeepDays)
        $monthly = (-not $keepMonths.ContainsKey($month)) -and ($keepMonths.Count -lt [int]$cfg.BackupKeepMonthly)
        if ($monthly) { $keepMonths[$month] = $true }
        if (-not ($young -or $monthly)) {
            Remove-Item -LiteralPath $b.Dir.FullName -Recurse -Force
            Write-StatusLog $cfg 'backup' "Retention: removed $($b.Dir.Name)"
        }
    }
}

try {
    $python = Get-CgvmsPython $cfg
    $tool = Join-Path $cfg.AppDir 'deploy\mongodb\cgvms_mongo.py'
    $dumpConfig = Join-Path $cfg.Root 'secrets\mongodump.yaml'
    $mongodump = Join-Path $cfg.MongoToolsBin 'mongodump.exe'
    if (-not (Test-Path -LiteralPath $mongodump)) {
        throw "Not found: $mongodump (install MongoDB Database Tools: mongodb.com/try/download/database-tools)"
    }
    $required = @($cfg.PhotoDir)
    if (-not $cfg.LocalMode) { $required += $dumpConfig }
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Not found: $path" }
    }
    Write-StatusLog $cfg 'backup' "Backup $name started."

    # 1. MongoDB log rotation (a failure here does not stop the backup). Local mode: dev_mongo.py's log, not rotated.
    if (-not $cfg.LocalMode) {
        $rotated = Invoke-Logged $cfg 'backup' $python @($tool, 'rotate-logs', '--dump-config', $dumpConfig,
            '--log-dir', (Join-Path $cfg.Root 'mongodb\log'), '--keep-days', '30')
        if ($rotated -ne 0) { Write-StatusLog $cfg 'backup' "  WARNING: MongoDB log rotation failed (exit code $rotated)." }
    }

    # 2. Database dump (consistent: --oplog). The connection comes from secrets\mongodump.yaml (login), or in
    #    local mode is the database on 127.0.0.1 without login.
    $staging = Join-Path $cfg.Root "backup\staging\$name"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    $archive = Join-Path $staging 'mongodb.archive.gz'
    $connection = if ($cfg.LocalMode) { "--uri=$($cfg.MongoUri)" } else { "--config=$dumpConfig" }
    $dumped = Invoke-Logged $cfg 'backup' $mongodump @($connection, '--oplog', '--gzip', "--archive=$archive") '  mongodump: '
    if ($dumped -ne 0) { throw "mongodump failed (exit code $dumped)." }
    $archiveHash = Get-FileSha256 $archive
    $archiveSize = (Get-Item -LiteralPath $archive).Length

    # 3. Photos (after the dump): new files only, never overwrite, never delete.
    $photoTarget = Join-Path $cfg.BackupDestination 'photos'
    New-Item -ItemType Directory -Path $photoTarget -Force | Out-Null
    $robolog = Join-Path (Get-StatusDir $cfg) ("robocopy-{0}.log" -f $stamp)
    & robocopy.exe $cfg.PhotoDir $photoTarget '*.jpg' /E /XC /XN /XO /R:3 /W:10 /NP /NDL /NFL "/LOG:$robolog" | Out-Null
    $robocopyExit = $LASTEXITCODE
    if ($robocopyExit -ge 8) { throw "Copying photos failed (robocopy exit code $robocopyExit, see $robolog)." }
    $livePhotos = @(Get-ChildItem -LiteralPath $cfg.PhotoDir -Recurse -File -Filter '*.jpg').Count
    $backupPhotos = @(Get-ChildItem -LiteralPath $photoTarget -Recurse -File -Filter '*.jpg').Count
    if ($backupPhotos -lt $livePhotos) { throw "Photo backup incomplete: $backupPhotos of $livePhotos files." }

    # 4. Settings (no secrets), manifest, copy to the destination, verify the copy.
    $configCopy = Join-Path $staging 'config'
    New-Item -ItemType Directory -Path $configCopy -Force | Out-Null
    foreach ($file in (Join-Path $cfg.Root 'config\cgvms.psd1'), (Join-Path $cfg.Root 'mongodb\mongod.conf')) {
        if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination $configCopy }
    }
    $manifest = [ordered]@{
        name = $name; created = $started.ToString('o'); computer = $env:COMPUTERNAME
        database = @{ file = 'mongodb.archive.gz'; sha256 = $archiveHash; bytes = $archiveSize; oplog = $true }
        photos = @{ location = 'photos (shared by all backups)'; live_files = $livePhotos; backup_files = $backupPhotos }
        tools = @{ mongodump = ((& $mongodump --version | Select-Object -First 1) -as [string]) }
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $staging 'manifest.json') -Encoding UTF8
    $dbTarget = Join-Path $cfg.BackupDestination 'database'
    New-Item -ItemType Directory -Path $dbTarget -Force | Out-Null
    $finalDir = Join-Path $dbTarget $name
    Copy-Item -LiteralPath $staging -Destination $finalDir -Recurse -Force
    if ((Get-FileSha256 (Join-Path $finalDir 'mongodb.archive.gz')) -ne $archiveHash) {
        throw 'The copy at the backup destination does not match the dump (SHA-256).'
    }

    # 5. Retention.
    Remove-ExpiredBackups $dbTarget
    Remove-OldStatusLogs $cfg

    # 6. Result.
    $summary = [ordered]@{ ok = $true; name = $name; finished = (Get-Date).ToString('o'); destination = $finalDir
                           database_bytes = $archiveSize; photos_backed_up = $backupPhotos }
    $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path (Get-StatusDir $cfg) 'last-backup.json') -Encoding UTF8
    $msg = "Backup $name completed: database $([math]::Round($archiveSize / 1MB, 1)) MB, $backupPhotos photo files at $($cfg.BackupDestination)."
    Write-StatusLog $cfg 'backup' $msg
    Write-CgvmsEvent 'Information' 2000 $msg
    exit 0
} catch {
    $msg = "Backup $name FAILED: $($_.Exception.Message)"
    try { Write-StatusLog $cfg 'backup' $msg } catch { Write-Host $msg }
    Write-CgvmsEvent 'Error' 2001 $msg
    exit 1
} finally {
    # Local staging copies (also after failures, so repeated failures cannot fill the disk).
    $stagingRoot = Join-Path $cfg.Root 'backup\staging'
    if (Test-Path -LiteralPath $stagingRoot) {
        Get-ChildItem -LiteralPath $stagingRoot -Directory | Sort-Object Name -Descending |
            Select-Object -Skip ([int]$cfg.BackupLocalKeep) | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}
