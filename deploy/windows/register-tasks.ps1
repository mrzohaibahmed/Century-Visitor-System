<#
.SYNOPSIS
  Registers the scheduled tasks for backups, health checks and restore tests (run as Administrator).

.DESCRIPTION
      powershell -NoProfile -ExecutionPolicy Bypass -File register-tasks.ps1 [-ConfigPath ...] [-BackupAt 02:00] [-DryRun]

  Tasks (folder "\Century Gate VMS\" in Task Scheduler), all run as SYSTEM, whether or not anyone is
  logged in:
    CGVMS Backup        daily at -BackupAt (default 02:00)          backup.ps1
    CGVMS Health check  every 5 minutes                             check-health.ps1
    CGVMS Restore test  monthly, first Sunday at 04:00              restore-test.ps1
  SYSTEM reaches a network share as the server's computer account (DOMAIN\SERVERNAME$): give that
  account write access to the backup share, or use -BackupUser for a dedicated domain account.
  Re-running the script replaces the tasks.
#>
param(
    [string]$ConfigPath = 'C:\CenturyGateVMS\config\cgvms.psd1',
    [string]$BackupAt = '02:00',
    [string]$BackupUser = '',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'cgvms-common.ps1')
$cfg = Get-CgvmsConfig $ConfigPath
$folder = '\Century Gate VMS\'
$scripts = Join-Path $cfg.Root 'app\deploy\windows'

function Register([string]$Name, [string]$Script, $Trigger, [string]$User, [TimeSpan]$Limit, [string]$Extra = '') {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scripts\$Script`" -ConfigPath `"$ConfigPath`" $Extra"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit $Limit -MultipleInstances IgnoreNew
    if ($DryRun) { Write-Host "[dry run] $folder$Name -> $Script as $($(if ($User) { $User } else { 'SYSTEM' }))"; return }
    if ($User) {
        $credential = Get-Credential -UserName $User -Message "Password of $User (for the task $Name)"
        Register-ScheduledTask -TaskPath $folder -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings `
            -User $User -Password $credential.GetNetworkCredential().Password -RunLevel Highest -Force | Out-Null
    } else {
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskPath $folder -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings `
            -Principal $principal -Force | Out-Null
    }
    Write-Host "Registered $folder$Name"
}

$daily = New-ScheduledTaskTrigger -Daily -At $BackupAt
$every5 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
# Monthly "first Sunday" is not offered by New-ScheduledTaskTrigger: weekly on Sunday, restore-test only acts in the first week.
$sundays = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '04:00'

Register 'CGVMS Backup' 'backup.ps1' $daily $BackupUser (New-TimeSpan -Hours 3)
Register 'CGVMS Health check' 'check-health.ps1' $every5 '' (New-TimeSpan -Minutes 4)
Register 'CGVMS Restore test' 'restore-test.ps1' $sundays '' (New-TimeSpan -Hours 2) '-OnlyFirstWeek'
Write-Host 'The restore test runs on the first Sunday of each month (the weekly trigger skips the other Sundays).'
