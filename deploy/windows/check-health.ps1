<#
.SYNOPSIS
  Century Gate VMS health check (scheduled task "CGVMS Health check", every 5 minutes).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File check-health.ps1 [-ConfigPath ...]

  Checks, without reading any password, and prints one line per part:
    MongoDB      service CGVMS-MongoDB running and listening on 127.0.0.1:<MongoPort>
    API          service CGVMS-API running; http://127.0.0.1:8000/api/v1/health/ready answers "ready"
    Database     (from the API) database reachable, schema up to date, transactions, photo folder
    Web          service CGVMS-Web running; http://127.0.0.1:3000/login answers
    HTTPS proxy  service CGVMS-Proxy running; HealthUrl (https://<SiteName>/api/v1/health/ready) answers
                 "ready" with a certificate this PC trusts (exactly what a gate PC sees)
  Each part is checked directly, so a proxy or name problem never hides the state of the others. Also:
    - the HTTPS certificate and the MongoDB certificates are valid for more than 30 days;
    - every drive holding Root, PhotoDir or the database keeps DiskMinFreePercent / DiskMinFreeGB free;
    - the last successful backup is younger than BackupMaxAgeHours.
  Writes status\health.json every run. Writes to the Windows event log (source CenturyGateVMS)
  only when the state changes (1000 = healthy again, 1001 = problem) and once a day while a
  problem continues, so a healthy system does not flood the log. Exit code 0 = healthy, 1 = problem.
#>
param([string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1', [int]$CertWarnDays = 30)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')

$cfg = Get-CgvmsConfig $ConfigPath
$problems = New-Object System.Collections.Generic.List[string]
$notes = New-Object System.Collections.Generic.List[string]
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$parts = New-Object System.Collections.Generic.List[object]
function Part([string]$Name, [bool]$Ok, [string]$Detail) {
    $parts.Add([pscustomobject]@{ part = $Name; healthy = $Ok; detail = $Detail })
    if (-not $Ok) { $problems.Add("${Name}: $Detail") }
}
function Get-ServiceProblem([string]$Name) {
    $s = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $s) { return "service $Name is not installed" }
    if ($s.Status -ne 'Running') { return "service $Name is $($s.Status)" }
    return ''
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
$p = Get-ServiceProblem 'CGVMS-MongoDB'
if (-not $p -and -not (Test-LocalPort ([int]$cfg.MongoPort))) { $p = "not listening on 127.0.0.1:$($cfg.MongoPort)" }
Part 'MongoDB' (-not $p) $(if ($p) { $p } else { "running on 127.0.0.1:$($cfg.MongoPort)" })

# API, and through it the database (directly on the loopback port: no proxy, no certificate, no name involved).
$p = Get-ServiceProblem 'CGVMS-API'
$apiReady = $null
if (-not $p) {
    $r = Get-Url 'http://127.0.0.1:8000/api/v1/health/ready'
    $apiReady = Read-Ready $r
    if (-not $apiReady) { $p = "http://127.0.0.1:8000 does not answer ($($r.error))" }
}
Part 'API' (-not $p) $(if ($p) { $p } else { 'running on 127.0.0.1:8000' })
if ($apiReady) {
    $c = $apiReady.checks
    $detail = "database $($c.database), schema $($c.schema_version), transactions $($c.transactions), photo folder $($c.photo_storage)"
    Part 'Database' ($apiReady.status -eq 'ready') $detail
}

# Web
$p = Get-ServiceProblem 'CGVMS-Web'
if (-not $p) {
    $r = Get-Url 'http://127.0.0.1:3000/login'
    if ($r.status -ne 200) { $p = "http://127.0.0.1:3000/login answered $($r.status) $($r.error)" }
}
Part 'Web' (-not $p) $(if ($p) { $p } else { 'running on 127.0.0.1:3000' })

# HTTPS proxy: the real address gate PCs use (certificate validated by Windows, as in a browser).
$p = Get-ServiceProblem 'CGVMS-Proxy'
if (-not $p) {
    $r = Get-Url $cfg.HealthUrl
    $viaProxy = Read-Ready $r
    if (-not $viaProxy) {
        $p = "$($cfg.HealthUrl) not reachable: $($r.error)"
        if ($r.error -match 'trust|SSL|TLS|certificate') { $p += ' (is the internal CA root certificate installed on this PC? README "HTTPS")' }
        if ($r.error -match 'remote name|resolve') { $p += " ($($cfg.SiteName) does not resolve on this PC)" }
    } elseif ($viaProxy.status -ne 'ready' -and $apiReady -and $apiReady.status -eq 'ready') {
        $p = "$($cfg.HealthUrl) answers not ready while the API itself is ready"
    }
}
Part 'HTTPS proxy' (-not $p) $(if ($p) { $p } else { "https://$($cfg.SiteName) OK" })

# HTTPS certificate expiry (as served to the gate PCs).
$healthUri = [Uri]$cfg.HealthUrl
if ($healthUri.Scheme -eq 'https') {
    try {
        $tcp = New-Object Net.Sockets.TcpClient($healthUri.Host, $healthUri.Port)
        $ssl = New-Object Net.Security.SslStream($tcp.GetStream(), $false)
        $ssl.AuthenticateAsClient($healthUri.Host)
        $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($ssl.RemoteCertificate)
        $days = [int]($cert.NotAfter - (Get-Date)).TotalDays
        $notes.Add("HTTPS certificate valid until $($cert.NotAfter.ToString('yyyy-MM-dd')) ($days days).")
        if ($days -lt $CertWarnDays) { $problems.Add("The HTTPS certificate expires in $days days ($($cert.NotAfter.ToString('yyyy-MM-dd'))). Renew it.") }
        $ssl.Dispose(); $tcp.Dispose()
    } catch { $problems.Add("Could not check the HTTPS certificate: $($_.Exception.Message)") }
}

# MongoDB certificates.
try {
    $python = Get-CgvmsPython $cfg
    $tool = Join-Path $cfg.AppDir 'deploy\mongodb\cgvms_mongo.py'
    $ErrorActionPreference = 'Continue'
    $out = & $python $tool cert-status --tls-dir (Join-Path $cfg.Root 'tls\mongodb') --warn-days $CertWarnDays 2>&1
    $certExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $notes.Add("Database certificates: $($out -join '; ')")
    if ($certExit -ne 0) { $problems.Add("A MongoDB certificate expires within $CertWarnDays days: $($out -join '; '). Renew it (README).") }
} catch { $problems.Add("Could not check the MongoDB certificates: $($_.Exception.Message)") }

# Disk space on every drive that holds application data.
$paths = @($cfg.Root, $cfg.PhotoDir, (Join-Path $cfg.Root 'mongodb'))
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

# Backups.
$last = Join-Path (Get-StatusDir $cfg) 'last-backup.json'
if (-not (Test-Path -LiteralPath $last)) { $problems.Add('No successful backup has been recorded yet.') }
else {
    $lb = Get-Content -LiteralPath $last -Raw | ConvertFrom-Json
    $age = (Get-Date) - [datetime]$lb.finished
    $notes.Add("Last good backup: $($lb.name), $([math]::Round($age.TotalHours, 1)) hours ago.")
    if ($age.TotalHours -gt [double]$cfg.BackupMaxAgeHours) {
        $problems.Add("The last successful backup ($($lb.name)) is $([math]::Round($age.TotalHours)) hours old.")
    }
}

# Result, state changes and a daily reminder while a problem lasts.
$healthy = $problems.Count -eq 0
$statusDir = Get-StatusDir $cfg
$state = [ordered]@{ checked = (Get-Date).ToString('o'); healthy = $healthy; parts = @($parts); problems = @($problems)
                    notes = @($notes) }
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
