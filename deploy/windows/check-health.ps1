<#
.SYNOPSIS
  Century Gate VMS health check (scheduled task "CGVMS Health check", every 5 minutes).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File check-health.ps1 [-ConfigPath ...]

  Checks, without reading any password:
    - the Windows services CGVMS-MongoDB, CGVMS-API, CGVMS-Web and CGVMS-Proxy are running;
    - HealthUrl (normally https://<site>/api/v1/health/ready) answers "ready": the HTTPS certificate,
      the proxy, the API, MongoDB, the schema version, transactions and the photo folder are all OK;
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

# Services
foreach ($svc in 'CGVMS-MongoDB', 'CGVMS-API', 'CGVMS-Web', 'CGVMS-Proxy') {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if (-not $s) { $problems.Add("Service $svc is not installed.") }
    elseif ($s.Status -ne 'Running') { $problems.Add("Service $svc is $($s.Status).") }
}

# Application readiness through the real entry point (certificate validated by Windows).
try {
    $response = Invoke-WebRequest -Uri $cfg.HealthUrl -UseBasicParsing -TimeoutSec 15
    $ready = $response.Content | ConvertFrom-Json
    if ($ready.status -ne 'ready') { $problems.Add("Application not ready: $($response.Content)") }
} catch [System.Net.WebException] {
    $body = ''
    if ($_.Exception.Response) {
        try { $body = (New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch { }
    }
    if ($body) { $problems.Add("Application not ready: $body") }
    else { $problems.Add("Health URL $($cfg.HealthUrl) not reachable: $($_.Exception.Message)") }
}

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
    $tool = Join-Path $cfg.Root 'app\deploy\mongodb\cgvms_mongo.py'
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
$state = [ordered]@{ checked = (Get-Date).ToString('o'); healthy = $healthy; problems = @($problems); notes = @($notes) }
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
if ($healthy) { Write-Host 'Healthy.'; $notes | ForEach-Object { Write-Host "  $_" }; exit 0 }
Write-Host 'PROBLEMS:'; $problems | ForEach-Object { Write-Host "  - $_" }
exit 1
