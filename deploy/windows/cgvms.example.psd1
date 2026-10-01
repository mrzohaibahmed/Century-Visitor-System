# Century Gate VMS - settings for the scripts in deploy\windows (one Windows 11 PC runs everything).
# setup-production.ps1 writes this file to C:\CenturyGateVMS\config\cgvms.psd1; edit it there.
# Contains NO passwords: those live in <Root>\secrets and <AppDir>\backend\.env.
# After changing SiteName or TlsMode run install-services.ps1 again (it rewrites the service settings).
@{
    # Data folder: database, logs, secrets, certificates, tools, local backups (see README for the layout).
    Root              = 'C:\CenturyGateVMS'

    # The application folder (this repository). Leave it out to use the folder these scripts are in.
    # AppDir          = 'D:\Visitor System\century-gate-vms'

    # The name gate PCs type in the browser: https://<SiteName>. The PC's own computer name works on most
    # networks without any DNS change. TlsMode: 'internal' (Caddy's own certificate; install its root
    # certificate once on each gate PC) or 'company' (cert.pem/key.pem from IT in <Root>\tls\web).
    SiteName          = 'gate-pc-name'
    TlsMode           = 'internal'

    # Private photo folder (CG_PHOTO_DIR in backend\.env must be the same path).
    PhotoDir          = 'C:\CenturyGateVMS\photos'

    # The application's MongoDB (NOT 27017: that is the legacy desktop database, never touched).
    MongoPort         = 27018
    MongoBin          = 'C:\Program Files\MongoDB\Server\8.3\bin'
    MongoToolsBin     = 'C:\CenturyGateVMS\tools\mongodb-database-tools\bin'

    # Nightly backups. A local folder works, but also copy it to another disk or PC regularly:
    # a backup on the same disk is lost together with the disk. A network share also works here.
    BackupDestination = 'C:\CenturyGateVMS\backups'
    BackupKeepDays    = 35      # every nightly backup is kept this long
    BackupKeepMonthly = 12      # plus the newest backup of each month for this many months
    BackupLocalKeep   = 3       # copies kept in Root\backup\staging
    BackupMaxAgeHours = 26      # the health check warns when the last good backup is older

    # Restore test (run by hand, or monthly with register-tasks.ps1 -IncludeRestoreTest): temporary MongoDB port.
    RestoreTestPort   = 27029

    # Disk space warnings (each drive holding Root, PhotoDir or the MongoDB data).
    DiskMinFreePercent = 15
    DiskMinFreeGB      = 10

    # Days of operations-script logs kept in Root\status.
    StatusKeepDays    = 60
}
