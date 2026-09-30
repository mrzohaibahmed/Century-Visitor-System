# Century Gate VMS — Production commands

Run everything in **PowerShell as Administrator** on the server. Full explanations: `README.md` → "Production operations".

## First-time installation

### 1. Get the application
```powershell
git clone <repo-url> C:\CenturyGateVMS\app
cd C:\CenturyGateVMS\app
git checkout <release-tag>
```

### 2. Backend environment
```powershell
cd C:\CenturyGateVMS\app\backend
& 'C:\Program Files\Python312\python.exe' -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r ..\deploy\requirements-ops.txt
```

### 3. Frontend build
```powershell
cd C:\CenturyGateVMS\app\frontend
npm ci
npm run build
```

### 4. Script settings
```powershell
New-Item -ItemType Directory -Force C:\CenturyGateVMS\config
Copy-Item C:\CenturyGateVMS\app\deploy\windows\cgvms.example.psd1 C:\CenturyGateVMS\config\cgvms.psd1
notepad C:\CenturyGateVMS\config\cgvms.psd1      # set SiteName, PhotoDir, MongoBin, HealthUrl, BackupDestination
```

### 5. Photo folder
```powershell
New-Item -ItemType Directory -Force D:\CenturyGateVMS-Photos
```

### 6. Database certificates
```powershell
cd C:\CenturyGateVMS\app
backend\.venv\Scripts\python deploy\mongodb\cgvms_mongo.py prepare --tls-dir C:\CenturyGateVMS\tls\mongodb
# then move C:\CenturyGateVMS\tls\mongodb\ca.key OFF the server (USB key in the safe)
```

### 7. MongoDB configuration
```powershell
New-Item -ItemType Directory -Force C:\CenturyGateVMS\mongodb\data, C:\CenturyGateVMS\mongodb\log
Copy-Item C:\CenturyGateVMS\app\deploy\mongodb\mongod.conf.template C:\CenturyGateVMS\mongodb\mongod.conf
```

### 8. Database accounts
Window 1 (leave running):
```powershell
& 'C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe' --config C:\CenturyGateVMS\mongodb\mongod.conf
```
Window 2:
```powershell
cd C:\CenturyGateVMS\app
backend\.venv\Scripts\python deploy\mongodb\cgvms_mongo.py init --tls-dir C:\CenturyGateVMS\tls\mongodb --secrets-dir C:\CenturyGateVMS\secrets
# save secrets\mongodb-root.txt in the password manager
```

### 9. API settings
```powershell
cd C:\CenturyGateVMS\app
Copy-Item deploy\windows\api.env.template backend\.env
Get-Content C:\CenturyGateVMS\secrets\cgvms_app.uri.txt       # paste into CG_MONGO_URI
backend\.venv\Scripts\python -m app.cli generate-secrets-key  # paste into CG_SECRETS_KEY
notepad backend\.env                                          # set CG_MONGO_URI, CG_PHOTO_DIR, CG_ORGANIZATION_NAME, CG_SECRETS_KEY
```

### 10. Schema and first administrator (MongoDB from step 8 still running)
```powershell
cd C:\CenturyGateVMS\app
powershell -ExecutionPolicy Bypass -File deploy\windows\migrate.ps1
cd backend
.venv\Scripts\python -m app.cli create-admin --username admin
# then press Ctrl+C in window 1 to stop MongoDB
```

### 11. HTTPS proxy settings
```powershell
New-Item -ItemType Directory -Force C:\CenturyGateVMS\services
Copy-Item C:\CenturyGateVMS\app\deploy\windows\services\CGVMS-Proxy.xml C:\CenturyGateVMS\services\
notepad C:\CenturyGateVMS\services\CGVMS-Proxy.xml   # set CGVMS_SITE and CGVMS_TLS_MODE (company | internal)
# company mode: put the certificate in C:\CenturyGateVMS\tls\web\cert.pem and the key in tls\web\key.pem
```

### 12. Install the services
```powershell
cd C:\CenturyGateVMS\app
powershell -ExecutionPolicy Bypass -File deploy\windows\install-services.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File deploy\windows\install-services.ps1
```

### 13. Scheduled tasks (backup, restore test)
```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\register-tasks.ps1
```

### 14. Verify
```powershell
Get-Service CGVMS-*
powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1
powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1
powershell -ExecutionPolicy Bypass -File deploy\windows\restore-test.ps1
# from a gate PC: open https://<SiteName>
```

## Daily operations

```powershell
Get-Service CGVMS-*                                                   # status
Restart-Service CGVMS-API                                             # after editing backend\.env
Restart-Service CGVMS-Proxy                                           # after changing certificate / Caddyfile
Stop-Service CGVMS-Proxy, CGVMS-Web, CGVMS-API, CGVMS-MongoDB         # full stop (this order)
Start-Service CGVMS-MongoDB, CGVMS-API, CGVMS-Web, CGVMS-Proxy        # full start (this order)
powershell -ExecutionPolicy Bypass -File C:\CenturyGateVMS\app\deploy\windows\check-health.ps1
```

## Updating to a new version

```powershell
cd C:\CenturyGateVMS\app
powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1
Stop-Service CGVMS-Proxy, CGVMS-Web, CGVMS-API
git fetch --tags
git checkout <new-release-tag>                                        # backend\.env is kept
cd backend
.venv\Scripts\python -m pip install -r requirements.txt
cd ..\frontend
npm ci
npm run build
cd ..
powershell -ExecutionPolicy Bypass -File deploy\windows\migrate.ps1
Start-Service CGVMS-API, CGVMS-Web, CGVMS-Proxy
powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1
```
