<#
.SYNOPSIS
  Century Gate VMS restore test: restores a backup into a TEMPORARY, separate MongoDB and photo
  folder, proves the data and the access rules, then deletes the copy. The live database and the
  live photo folder are never touched.

.DESCRIPTION
  Run monthly by the scheduled task "CGVMS Restore test" (register-tasks.ps1), or by hand:
      powershell -NoProfile -ExecutionPolicy Bypass -File restore-test.ps1 [-Backup cgvms-20260927-020000] [-Keep]

  1. Picks the newest backup in <BackupDestination>\database (or -Backup) and checks its SHA-256
     against manifest.json.
  2. Starts a temporary mongod: its own data folder under Root\restore-test, port RestoreTestPort,
     loopback only, TLS required. It refuses the live port and 27017 (legacy desktop database).
  3. mongorestore of the whole dump with --oplogReplay (the point-in-time state). This includes the
     database accounts (password hashes only), exactly as a disaster recovery would; the temporary
     instance has no network access and is deleted afterwards.
  4. Copies the photo backup into a temporary photo folder.
  5. python -m app.cli restore-check against the copy: record counts, every photo file present with
     the recorded SHA-256, visit/visitor photo links, and, with the real API in-process, logins,
     roles and photo access (admin yes, guard only gate photos, anonymous no). The check adds two
     throw-away accounts to the COPY only.
  6. Stops the temporary mongod and deletes the copy (-Keep leaves it for inspection).
  Result: status\restore-test-<timestamp>.json, status\restore-<date>.log and the Windows event log
  (source CenturyGateVMS, 3000 = passed, 3001 = failed). Exit code 0 / 1.
#>
param(
    [string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1',
    [string]$Backup = '',
    [switch]$Keep,
    [switch]$OnlyFirstWeek      # used by the weekly scheduled task: run on the first Sunday of the month only
)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsConfig $ConfigPath
if ($OnlyFirstWeek -and (Get-Date).Day -gt 7) { Write-Host 'Not the first week of the month: no restore test today.'; exit 0 }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$port = [int]$cfg.RestoreTestPort
$work = Join-Path $cfg.Root "restore-test\$stamp"
$mongodProcess = $null
$savedEnv = @{}

function Set-ProcessEnv([hashtable]$Values) {
    foreach ($key in $Values.Keys) {
        $savedEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $Values[$key], 'Process')
    }
}

try {
    if ($port -eq [int]$cfg.MongoPort -or $port -eq 27017) {
        throw "RestoreTestPort $port is the live or the legacy database port; refusing."
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use; is another restore test running?"
    }
    $python = Get-CgvmsPython $cfg
    $tlsDir = Join-Path $cfg.Root 'tls\mongodb'
    $ca = Join-Path $tlsDir 'ca.pem'

    # 1. Which backup, and is it intact?
    $dbDir = Join-Path $cfg.BackupDestination 'database'
    $chosen = if ($Backup) { Get-Item -LiteralPath (Join-Path $dbDir $Backup) } else {
        Get-ChildItem -LiteralPath $dbDir -Directory | Where-Object { $_.Name -match '^cgvms-\d{8}-\d{6}$' } |
            Sort-Object Name -Descending | Select-Object -First 1 }
    if (-not $chosen) { throw "No backup found in $dbDir." }
    $manifest = Get-Content -LiteralPath (Join-Path $chosen.FullName 'manifest.json') -Raw | ConvertFrom-Json
    $archive = Join-Path $chosen.FullName 'mongodb.archive.gz'
    if ((Get-FileSha256 $archive) -ne $manifest.database.sha256) { throw "$($chosen.Name): the dump does not match its manifest (SHA-256)." }
    Write-StatusLog $cfg 'restore' "Restore test of $($chosen.Name) started (temporary instance on port $port)."

    # 2. Temporary mongod (loopback, TLS, its own folder).
    $dataDir = Join-Path $work 'data'
    $photoDir = Join-Path $work 'photos'
    New-Item -ItemType Directory -Force -Path $dataDir, $photoDir | Out-Null
    $mongod = Join-Path $cfg.MongoBin 'mongod.exe'
    $mongodArgs = @('--dbpath', "`"$dataDir`"", '--port', $port, '--bind_ip', '127.0.0.1', '--replSet', 'cgvmsrestore',
                    '--tlsMode', 'requireTLS', '--tlsCertificateKeyFile', "`"$(Join-Path $tlsDir 'server.pem')`"",
                    '--tlsCAFile', "`"$ca`"", '--tlsAllowConnectionsWithoutCertificates',
                    '--logpath', "`"$(Join-Path $work 'mongod.log')`"")
    $mongodProcess = Start-Process -FilePath $mongod -ArgumentList $mongodArgs -WindowStyle Hidden -PassThru
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Milliseconds 500
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
        if ($mongodProcess.HasExited) { break }
    }
    if (-not $ready) { throw "The temporary mongod did not start (see $work\mongod.log)." }
    $tool = Join-Path $cfg.Root 'app\deploy\mongodb\cgvms_mongo.py'
    if ((Invoke-Logged $cfg 'restore' $python @($tool, 'init-temp', '--tls-dir', $tlsDir, '--port', "$port")) -ne 0) {
        throw 'The temporary replica set could not be initiated.'
    }

    # 3. Restore the whole dump, point in time (mongorestore cannot combine --oplogReplay with a filter).
    $caUri = [Uri]::EscapeDataString(($ca -replace '\\', '/')) -replace '%3A', ':' -replace '%2F', '/'
    $uri = "mongodb://localhost:$port/?directConnection=true&tls=true&tlsCAFile=$caUri"
    $mongorestore = Join-Path $cfg.MongoToolsBin 'mongorestore.exe'
    $restored = Invoke-Logged $cfg 'restore' $mongorestore @("--uri=$uri", '--gzip', "--archive=$archive", '--oplogReplay',
                                                            '--stopOnError') '  mongorestore: '
    if ($restored -ne 0) { throw "mongorestore failed (exit code $restored)." }

    # 4. Photos from the backup.
    & robocopy.exe (Join-Path $cfg.BackupDestination 'photos') $photoDir '*.jpg' /E /R:2 /W:5 /NP /NDL /NFL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the photo backup failed (robocopy exit code $LASTEXITCODE)." }

    # 5. Check the copy with the real application code (never production settings).
    Set-ProcessEnv @{ CG_ENVIRONMENT = 'test'; CG_MONGO_URI = $uri; CG_MONGO_DB = 'century_gate_vms'; CG_PHOTO_DIR = $photoDir;
                      CG_LOG_LEVEL = 'WARNING' }
    $reportFile = Join-Path (Get-StatusDir $cfg) "restore-test-$stamp.json"
    Push-Location (Join-Path $cfg.Root 'app\backend')
    try {
        $ErrorActionPreference = 'Continue'
        $out = & $python -m app.cli restore-check 2>$null
        $checkExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    } finally { Pop-Location }
    ($out -join "`n") | Set-Content -LiteralPath $reportFile -Encoding UTF8
    $report = ($out -join "`n") | ConvertFrom-Json
    $counts = $report.data.counts
    $summary = "users $($counts.users), visitors $($counts.visitors), visits $($counts.visits), watchlist $($counts.watchlist), " +
               "audit logs $($counts.audit_logs), photos $($counts.photos) (files checked: $($report.data.photo_files_checked))"
    if ($checkExit -ne 0 -or -not $report.ok) {
        throw "Restore check FAILED for $($chosen.Name): $summary. Details: $reportFile"
    }
    $msg = "Restore test PASSED for $($chosen.Name): $summary; access rules OK. Report: $reportFile"
    Write-StatusLog $cfg 'restore' $msg
    Write-CgvmsEvent 'Information' 3000 $msg
    $exitCode = 0
} catch {
    $msg = "Restore test FAILED: $($_.Exception.Message)"
    try { Write-StatusLog $cfg 'restore' $msg } catch { Write-Host $msg }
    Write-CgvmsEvent 'Error' 3001 $msg
    $exitCode = 1
} finally {
    foreach ($key in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($key, $savedEnv[$key], 'Process') }
    if ($mongodProcess -and -not $mongodProcess.HasExited) { Stop-Process -Id $mongodProcess.Id -Force; $mongodProcess.WaitForExit(15000) | Out-Null }
    if (-not $Keep -and (Test-Path -LiteralPath $work)) {
        Start-Sleep -Seconds 1
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $work) { Write-StatusLog $cfg 'restore' "WARNING: could not delete $work; delete it by hand." }
    }
}
exit $exitCode
