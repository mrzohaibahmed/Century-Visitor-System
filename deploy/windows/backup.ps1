<#
.SYNOPSIS
  Century Gate VMS nightly backup: the MongoDB database AND the private photo folder.

.DESCRIPTION
  Run by hand (or from a Task Scheduler task):
      powershell -NoProfile -ExecutionPolicy Bypass -File backup.ps1

  1. mongodump of the whole application instance (127.0.0.1:27018, no login) with --oplog: a
     consistent point-in-time copy (users, visitors, visits, watchlist, directory, audit logs, photo
     metadata, everything).
  2. Copies NEW photo files to <BackupDestination>\photos. Photos are never changed or deleted by
     the application, so existing backup copies are never overwritten (a damaged live file cannot
     replace a good backup copy). The database is dumped FIRST, so every photo record in the dump
     has its file in the backup.
  3. Writes manifest.json (SHA-256 of the dump, counts) and copies everything to
     <BackupDestination>\database\cgvms-<timestamp>, then re-checks the SHA-256 there.
     Secrets (backend\.env) are deliberately NOT in the backup, so a stolen backup does not also
     hand over the keys.
  4. Retention (only folders named cgvms-YYYYMMDD-HHMMSS in <BackupDestination>\database are ever
     deleted): every backup younger than BackupKeepDays, plus the newest backup of each of the last
     BackupKeepMonthly months. Photo backups are never deleted by this script.
  5. Records the result: status\last-backup.json, status\backup-<date>.log and the Windows event
     log (source CenturyGateVMS, 2000 = success, 2001 = failure). Exit code 0 / 1.
  BackupDestination is .prod\backups unless CGVMS_BACKUP names another folder. Copy that folder to
  another disk or PC regularly, or point CGVMS_BACKUP at one: a backup on the same disk dies with it.
#>

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsLocalConfig
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
    $mongodump = Join-Path $cfg.MongoToolsBin 'mongodump.exe'
    if (-not (Test-Path -LiteralPath $mongodump)) {
        throw "Not found: $mongodump (install MongoDB Database Tools: mongodb.com/try/download/database-tools)"
    }
    if (-not (Test-Path -LiteralPath $cfg.PhotoDir)) { throw "Not found: $($cfg.PhotoDir)" }
    Write-StatusLog $cfg 'backup' "Backup $name started."

    # 1. Database dump (consistent: --oplog) of the database on 127.0.0.1 without login.
    $staging = Join-Path $cfg.Root "backup\staging\$name"
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    $archive = Join-Path $staging 'mongodb.archive.gz'
    $dumped = Invoke-Logged $cfg 'backup' $mongodump @("--uri=$($cfg.MongoUri)", '--oplog', '--gzip', "--archive=$archive") '  mongodump: '
    if ($dumped -ne 0) { throw "mongodump failed (exit code $dumped)." }
    $archiveHash = Get-FileSha256 $archive
    $archiveSize = (Get-Item -LiteralPath $archive).Length

    # 2. Photos (after the dump): new files only, never overwrite, never delete.
    $photoTarget = Join-Path $cfg.BackupDestination 'photos'
    New-Item -ItemType Directory -Path $photoTarget -Force | Out-Null
    $robolog = Join-Path (Get-StatusDir $cfg) ("robocopy-{0}.log" -f $stamp)
    & robocopy.exe $cfg.PhotoDir $photoTarget '*.jpg' /E /XC /XN /XO /R:3 /W:10 /NP /NDL /NFL "/LOG:$robolog" | Out-Null
    $robocopyExit = $LASTEXITCODE
    if ($robocopyExit -ge 8) { throw "Copying photos failed (robocopy exit code $robocopyExit, see $robolog)." }
    $livePhotos = @(Get-ChildItem -LiteralPath $cfg.PhotoDir -Recurse -File -Filter '*.jpg').Count
    $backupPhotos = @(Get-ChildItem -LiteralPath $photoTarget -Recurse -File -Filter '*.jpg').Count
    if ($backupPhotos -lt $livePhotos) { throw "Photo backup incomplete: $backupPhotos of $livePhotos files." }

    # 3. Manifest, copy to the destination, verify the copy.
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

    # 4. Retention.
    Remove-ExpiredBackups $dbTarget
    Remove-OldStatusLogs $cfg

    # 5. Result.
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
