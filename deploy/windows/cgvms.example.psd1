# Century Gate VMS - server settings for the operations scripts in deploy\windows.
# Copy to C:\CenturyGateVMS\config\cgvms.psd1 and adjust. Contains NO passwords:
# secrets live in C:\CenturyGateVMS\secrets (see README, "Production operations").
@{
    # Everything the application needs on this server lives under Root (see README for the layout).
    Root              = 'C:\CenturyGateVMS'

    # The name gate PCs type in the browser. Must match the HTTPS certificate.
    SiteName          = 'vms.century.local'

    # Private photo folder (CG_PHOTO_DIR in api\.env must be the same path). Preferably a data drive.
    PhotoDir          = 'D:\CenturyGateVMS-Photos'

    # The application's MongoDB instance (NOT 27017: that is the legacy desktop database service).
    MongoPort         = 27018
    MongoBin          = 'C:\Program Files\MongoDB\Server\8.3\bin'
    MongoToolsBin     = 'C:\CenturyGateVMS\tools\mongodb-database-tools\bin'

    # Health check address. Uses the real HTTPS name, so the certificate is checked as the gate PCs see it.
    HealthUrl         = 'https://vms.century.local/api/v1/health/ready'

    # Backups: a folder on ANOTHER machine or disk (network share or backup drive), never only on this server.
    BackupDestination = '\\BACKUP01\CenturyGateVMS$'
    BackupKeepDays    = 35      # every nightly backup is kept this long
    BackupKeepMonthly = 12      # plus the newest backup of each month for this many months
    BackupLocalKeep   = 3       # copies kept in Root\backup\staging (fast restore, not a real backup)
    BackupMaxAgeHours = 26      # the health check warns when the last good backup is older

    # Restore test: a temporary MongoDB on this port (loopback only), deleted afterwards.
    RestoreTestPort   = 27029

    # Disk space warnings (each drive holding Root, PhotoDir or the MongoDB data).
    DiskMinFreePercent = 15
    DiskMinFreeGB      = 10

    # Days of operations-script logs kept in Root\status.
    StatusKeepDays    = 60
}
