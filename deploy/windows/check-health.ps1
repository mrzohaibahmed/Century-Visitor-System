<#
.SYNOPSIS
  Century Gate VMS health check of the production programs started by start-production.bat.

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File check-health.ps1

  Checks, without reading any password, and prints one line per part:
    MongoDB      listening on 127.0.0.1:<MongoPort>
    API          http://127.0.0.1:8000/api/v1/health/ready answers "ready"
    Database     (from the API) database reachable, schema up to date, transactions, photo folder
    Web          http://127.0.0.1:6543/login answers
    Web to API   HealthUrl (http://127.0.0.1:6543/api/v1/health/ready) answers "ready" through the web
                 server's /api/* (plain HTTP, no certificate: the way gate PCs reach the API)
  Each part is checked directly, so a problem in one never hides the state of the others. Also:
    - every drive holding Root, PhotoDir or the database keeps DiskMinFreePercent / DiskMinFreeGB free.
  Writes status\health.json every run. Writes to the Windows event log (source CenturyGateVMS)
  only when the state changes (1000 = healthy again, 1001 = problem) and once a day while a
  problem continues, so a healthy system does not flood the log. Exit code 0 = healthy, 1 = problem.
#>
. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsLocalConfig
$problems = New-Object System.Collections.Generic.List[string]
$notes = New-Object System.Collections.Generic.List[string]

$parts = New-Object System.Collections.Generic.List[object]
function Part([string]$Name, [bool]$Ok, [string]$Detail) {
    $parts.Add([pscustomobject]@{ part = $Name; healthy = $Ok; detail = $Detail })
    if (-not $Ok) { $problems.Add("${Name}: $Detail") }
}
function Test-LocalPort([int]$Port) {
    $tcp = New-Object Net.Sockets.TcpClient
    try { $tcp.Connect('127.0.0.1', $Port); return $true } catch { return $false } finally { $tcp.Dispose() }
}
# GET a URL; returns @{ ok; status; body; error } (a 503 "not ready" still has a body).
function Get-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 15 -MaximumRedirection 0
        return @{ ok = $true; status = [int]$r.StatusCode; body = $r.Content; error = '' }
    } catch [System.Net.WebException] {
        $body = ''; $status = 0
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
        }
        return @{ ok = $false; status = $status; body = $body; error = $_.Exception.Message }
    }
}
function Read-Ready($Result) {
    if (-not $Result.body) { return $null }
    try { return $Result.body | ConvertFrom-Json } catch { return $null }
}

# MongoDB
$p = ''
if (-not (Test-LocalPort ([int]$cfg.MongoPort))) { $p = "not listening on 127.0.0.1:$($cfg.MongoPort)" }
Part 'MongoDB' (-not $p) $(if ($p) { $p } else { "running on 127.0.0.1:$($cfg.MongoPort)" })

# API, and through it the database (directly on the loopback port: no web server, no name involved).
$p = ''
$r = Get-Url 'http://127.0.0.1:8000/api/v1/health/ready'
$apiReady = Read-Ready $r
if (-not $apiReady) { $p = "http://127.0.0.1:8000 does not answer ($($r.error))" }
Part 'API' (-not $p) $(if ($p) { $p } else { 'running on 127.0.0.1:8000' })
if ($apiReady) {
    $c = $apiReady.checks
    $detail = "database $($c.database), schema $($c.schema_version), transactions $($c.transactions), photo folder $($c.photo_storage)"
    Part 'Database' ($apiReady.status -eq 'ready') $detail
}

# Web
$p = ''
$r = Get-Url 'http://127.0.0.1:6543/login'
if ($r.status -ne 200) { $p = "http://127.0.0.1:6543/login answered $($r.status) $($r.error)" }
Part 'Web' (-not $p) $(if ($p) { $p } else { 'running on 127.0.0.1:6543' })

# The way in that gate PCs use, end to end: plain HTTP through the web server's /api/* to the API and the database.
$p = ''
$r = Get-Url $cfg.HealthUrl
$viaWeb = Read-Ready $r
if (-not $viaWeb) {
    $p = "$($cfg.HealthUrl) not reachable: $($r.error)"
} elseif ($viaWeb.status -ne 'ready' -and $apiReady -and $apiReady.status -eq 'ready') {
    $p = "$($cfg.HealthUrl) answers not ready while the API itself is ready"
}
Part 'Web to API (HTTP)' (-not $p) $(if ($p) { $p } else { "$($cfg.HealthUrl) ready" })

# Disk space on every drive that holds application data.
$paths = @($cfg.Root, $cfg.PhotoDir, $cfg.MongoDir)
$drives = $paths | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object { (Get-Item -LiteralPath $_).PSDrive.Name } | Sort-Object -Unique
foreach ($d in $drives) {
    $info = Get-PSDrive -Name $d
    $total = $info.Used + $info.Free
    if ($total -le 0) { continue }
    $freeGB = [math]::Round($info.Free / 1GB, 1)
    $freePct = [math]::Round(100 * $info.Free / $total, 1)
    $notes.Add("Drive ${d}: $freeGB GB free ($freePct %).")
    if ($freePct -lt [double]$cfg.DiskMinFreePercent -or $freeGB -lt [double]$cfg.DiskMinFreeGB) {
        $problems.Add("Drive ${d}: only $freeGB GB ($freePct %) free.")
    }
}
if (-not (Test-Path -LiteralPath $cfg.PhotoDir)) { $problems.Add('The photo folder (PhotoDir) is not available.') }

# Result, state changes and a daily reminder while a problem lasts.
$healthy = $problems.Count -eq 0
$statusDir = Get-StatusDir $cfg
$state = [ordered]@{ checked = (Get-Date).ToString('o'); healthy = $healthy; parts = $parts.ToArray()
                    problems = $problems.ToArray(); notes = $notes.ToArray() }
$state | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $statusDir 'health.json') -Encoding UTF8
$stateFile = Join-Path $statusDir 'health-state.txt'
$previous = if (Test-Path -LiteralPath $stateFile) { Get-Content -LiteralPath $stateFile -Raw } else { '' }
$current = if ($healthy) { 'healthy' } else { "problem $(Get-Date -Format 'yyyy-MM-dd')" }
if ($current.Trim() -ne $previous.Trim()) {
    if ($healthy) { Write-CgvmsEvent 'Information' 1000 'Century Gate VMS is healthy again.' }
    else { Write-CgvmsEvent 'Error' 1001 ("Century Gate VMS health check found problems:`n- " + ($problems -join "`n- ")) }
    Set-Content -LiteralPath $stateFile -Value $current -Encoding UTF8
    Write-StatusLog $cfg 'health' ($(if ($healthy) { 'Healthy.' } else { 'PROBLEMS: ' + ($problems -join ' | ') }))
}
foreach ($part in $parts) {
    Write-Host ("  {0,-12} {1,-9} {2}" -f $part.part, $(if ($part.healthy) { 'healthy' } else { 'PROBLEM' }), $part.detail)
}
$other = @($problems | Where-Object { $p = $_; -not ($parts | Where-Object { $p -like "$($_.part):*" }) })
if ($healthy) { Write-Host 'Healthy.'; $notes | ForEach-Object { Write-Host "  $_" }; exit 0 }
if ($other.Count) { Write-Host 'Other problems:'; $other | ForEach-Object { Write-Host "  - $_" } }
Write-Host 'NOT HEALTHY.'
exit 1
