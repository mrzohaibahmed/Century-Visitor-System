# Century Gate VMS — Production commands

## Production on one Windows 11 PC (from this project folder)

The existing project runs in production mode as normal programs: no copy of the application, no Windows services.

| Part | Production command (started by `production.ps1`) | Listens on | Log |
| --- | --- | --- | --- |
| MongoDB | `scripts\dev_mongo.py start` (the project's own database, data in `.dev\mongo`) | 127.0.0.1:27018 | `.dev\mongo\mongod.log` |
| API | `backend\.venv\Scripts\python -m app.serve --host 127.0.0.1 --port 8000` (no reload, no API docs) | 127.0.0.1:8000 | `.prod\logs\api.log` (JSON lines) |
| Web | `npm run build`, then `next start --hostname 127.0.0.1 --port 3000` | 127.0.0.1:3000 | `.prod\logs\web.log` |
| HTTPS | `.prod\caddy.exe run` with `deploy\windows\caddy\Caddyfile` (internal certificate) | 0.0.0.0:443, :80 → 443 | `.prod\logs\caddy.log` |

Previous run's logs: `*.1.log`. The legacy MongoDB on 27017 is never used or touched.

**Why HTTPS (Caddy) at all:** the login cookie is `Secure` (`__Host-cg_session`) and browsers only open a webcam on
HTTPS. Over `http://<ip>:3000` gate PCs could not stay logged in, and webcam photos / QR scanning would not work.
On this PC itself `http://localhost:3000` works fully without HTTPS. Hikvision capture is server-side either way.

**Settings:** `backend\.env` as it is. For the API process only, `production.ps1` sets
`CG_ENVIRONMENT=production`, `CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true` (the project's database has no login; this is
only accepted for a database on 127.0.0.1) and `CG_PHOTO_DIR=<project>\.dev\photos` (the existing photos; a
`CG_PHOTO_DIR` in `backend\.env` wins). `start-dev.bat` keeps working unchanged. Optional: `CGVMS_SITE` = the name
gate PCs use (default: this PC's computer name), `CGVMS_BACKUP` = backup folder (default `.prod\backups`).

### Once

1. Prerequisites already used for development: `backend\.venv`, `frontend\node_modules`, `backend\.env`, MongoDB 8.x.
2. Caddy: download "Windows amd64" from caddyserver.com/download (or github.com/caddyserver/caddy/releases, check
   the SHA-512 in the checksums file) and save it as `.prod\caddy.exe`.
3. Right-click `deploy\windows\start-production.bat` → **Run as administrator** (first time only: trusts the HTTPS
   certificate on this PC and allows ports 443/80 for Caddy in Windows Firewall).
4. Windows network profile of the LAN: **Private** (Settings → Network & internet → the network). On "Public",
   Windows blocks the gate PCs.
5. Each gate PC, once: copy `.prod\gate-pc\CenturyGateVMS-root.crt`, double-click → Install Certificate → Local
   Machine → *Trusted Root Certification Authorities*. Then open `https://<this PC's name>` (e.g.
   `https://zohaib-laptop`). If the name does not resolve, add `<this PC's IP> <name>` to the gate PC's
   `C:\Windows\System32\drivers\etc\hosts`.

### Daily operations (double-click in `deploy\windows\`)

| Task | Command |
| --- | --- |
| Start | `start-production.bat` (ends with the health check) |
| Stop | `stop-production.bat` (HTTPS, web, API, then a clean MongoDB shutdown) |
| Restart | `restart-production.bat` |
| Health | `powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1` |
| Backup | `powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1` (needs MongoDB Database Tools; database + photos to `.prod\backups` or `CGVMS_BACKUP`) |
| After an update (`git pull`) | `restart-production.bat rebuild` (runs `npm run build`); if `requirements.txt` changed first `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`; if the schema changed `cd backend; .venv\Scripts\python -m app.cli migrate` |

The programs keep running when the window closes and stop at sign-out or shutdown. To start them with Windows,
add a Task Scheduler task "At log on" that runs `start-production.bat` with `CGVMS_NOPAUSE=1` (optional).

Copy `.prod\backups` to another disk or PC regularly: a backup on the same disk is lost with the disk.

---

## Alternative: Windows services installation (setup-production)

Run everything in **PowerShell as Administrator** on the server. Full explanations: `README.md` → "Production operations".
When the `CGVMS-*` services are installed, `start-`, `stop-` and `restart-production.bat` start and stop those services.

### Quick setup (steps 2–14 in one script)

1. Install Python 3.12 (**for all users**), Node.js 24 LTS and MongoDB 8.x (untick "Install MongoD as a Service").
2. Put `caddy.exe`, `WinSW-x64.exe` and the MongoDB Database Tools (`tools\mongodb-database-tools\bin\mongodump.exe`) in `C:\CenturyGateVMS\tools`.
3. Clone the application (step 1 below) to `C:\CenturyGateVMS\app`.
4. Right-click `C:\CenturyGateVMS\app\deploy\windows\setup-production.bat` → **Run as administrator**, or:
   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\CenturyGateVMS\app\deploy\windows\setup-production.ps1 -BackupDestination \\BACKUP01\CenturyGateVMS$
   ```
   Defaults: site `vms.century.local`, internal CA, photos in `D:\CenturyGateVMS-Photos`. It lists anything missing and stops; it is safe to run again.
   It asks for the first administrator's password, and ends with the steps that must be done by hand (move `ca.key` off the server, password manager, gate-PC root certificate, DNS, backup share rights).

After that, start everything with `deploy\windows\start-production.bat` (as Administrator). The steps below are the same setup done by hand.

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
