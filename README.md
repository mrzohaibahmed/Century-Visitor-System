# Century Gate VMS — Web Application

Web-based Visitor Management System replacing the Century Gate desktop application.

```
Browser ──HTTPS──> Reverse proxy ──/──────> Next.js (web/)
                                 └─/api/──> FastAPI (api/) ──> MongoDB (private)
```

- The browser never connects to MongoDB; only the API holds database credentials.
- Every access decision is made by the API. The frontend only hides what a role cannot use.
- The API uses its own database, `century_gate_vms`. It refuses to start with the legacy
  desktop database name (`century_gate_system`) and refuses to migrate a database containing
  legacy collections. The legacy database is never read or modified.

## Repository layout

| Path | What |
| --- | --- |
| `api/` | FastAPI backend (Python 3.12, Pydantic v2, PyMongo async) |
| `web/` | Next.js 16 frontend (App Router, React 19, TypeScript, Tailwind CSS 4) |
| `scripts/dev_mongo.py` | Starts an isolated local MongoDB replica set for development |
| `deploy/` | Production deployment on Windows: services, HTTPS proxy, MongoDB, backups, monitoring (see "Production operations") |
| `.dev/` | Local development data and logs (git-ignored) |

## Local development (Windows)

Requirements: Python 3.12, Node.js 24, MongoDB Community Server 8.x installed (the binary is used;
the MongoDB Windows service is not touched).

### 1. Development database

```powershell
api\.venv\Scripts\python scripts\dev_mongo.py start     # 127.0.0.1:27018, replica set "cgvms-dev"
api\.venv\Scripts\python scripts\dev_mongo.py status
api\.venv\Scripts\python scripts\dev_mongo.py stop
```

This runs a **separate** `mongod` on port 27018 with its data in `.dev/mongo/`. The MongoDB Windows
service on port 27017 (which holds the legacy desktop database) is never used or reconfigured.
A replica set is required because check-in writes a visit and its audit record in one transaction.

### 2. API

```powershell
cd api
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env
.venv\Scripts\python -m app.cli migrate          # creates collections, validators, indexes (idempotent)
.venv\Scripts\python -m app.cli create-admin --username admin   # first administrator (asks for a password)
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000
```

The first administrator can only be created with `create-admin` on the server. There is no web
"first-run" page, because it would be reachable by anyone on the network.

- Health: http://127.0.0.1:8000/api/v1/health/live and `/api/v1/health/ready`
- Interactive docs (development only): http://127.0.0.1:8000/api/docs
- Tests: `.venv\Scripts\python -m pytest` (needs the development database running)
- Lint: `.venv\Scripts\ruff check app tests ..\scripts`

### 3. Web

```powershell
cd web
npm install
copy .env.example .env.local
npm run dev                       # http://localhost:3000 (forwards /api/* to the API)
npm run typecheck ; npm run lint ; npm test ; npm run build
npm run test:e2e                  # end-to-end tests in Microsoft Edge (see below)
```

Open the app via **http://localhost:3000**, not 127.0.0.1: the Next.js dev server only serves its
scripts to `localhost` by default.

**End-to-end tests** start their own isolated stack (API on :8001 with database `cgvms_e2e`, web on
:3001), reset that database and create an E2E administrator. They never touch the development database.
They need the development MongoDB running, and no other `next dev` server running for `web/`.

## Configuration

All API settings are environment variables with the `CG_` prefix (see `api/.env.example`).
Secrets live only in the server environment, never in the frontend or the repository.

## Accounts & security (Phase 2)

- Roles: **Administrator** (everything) and **Guard** (gate work). The API checks the role on every
  request; the frontend only hides what a role cannot use.
- Passwords: argon2id; at least 10 characters, not containing the username, not a common password.
  New and reset accounts must choose their own password at first login.
- Sessions: HttpOnly `__Host-` cookie (the database stores only its hash), CSRF token on every change,
  15 minutes idle / 12 hours maximum (`CG_SESSION_IDLE_MINUTES`, `CG_SESSION_MAX_HOURS`).
- Brute force: 5 wrong passwords lock the account for 15 minutes; login attempts are rate-limited per
  client IP. The login page never reveals whether a username exists.
- Admin actions that change a role, disable an account or reset a password require the admin's own
  password. The last active administrator cannot be demoted or disabled. Accounts are disabled, never
  deleted.
- Login and user-management events are recorded in `audit_logs` (append-only).

## Visitors & visits (Phase 3)

- **First-time setup (administrator):** add at least one gate, the departments and the hosts under
  *Hosts / Departments / Gates* in the menu. With one gate, every session uses it automatically; with
  several, each user picks the gate they are working at after logging in (shown in the top bar).
- **Check-in:** ID lookup → register the visitor if new → watchlist and "already inside" checks → host,
  department, reason, vehicle, belongings → review → confirm. The visit number (`V-YYYY-NNNNNN`) is
  shown on success. A host who is not in the directory can be typed in; that visit is flagged.
- **Check-out:** by visit number or ID number (Enter), or from the list of visitors inside. Repeating a
  check-out is harmless.
- **Visitors / Visit history:** search by name, ID or phone; history filters by date, status, gate and
  department. Opening a visitor's record and every ID lookup is audited (ID numbers are masked in the
  audit log). Only administrators can edit a visitor's details.
- The database guarantees one active visit per visitor, gap-free visit numbers per year and
  idempotent check-out, even with several gates working at once.

## Watchlist, photos, passes & badges (Phase 4)

- **Watchlist (administrators, menu *Watchlist*):** add, edit, expire now, disable, search by ID number (any
  format) or name, filter by status. The server normalises ID numbers, so a ban matches however the number is
  typed at the gate. Entries are never deleted; disabling needs a reason. The ID number of an entry cannot be
  changed (disable it and add a correct one). Adding someone who is inside right now is flagged at once.
  Every change is audited (`WATCHLIST_ADDED/UPDATED/EXPIRED/DISABLED`) with a masked ID number.
- **Photo (check-in step 3):** start camera → take photo → retake or use it → upload. The previous photo can be
  kept. A gate without a working camera can continue without a photo. The camera is switched off as soon as the
  picture is taken or the step is left.
- **Pass and badge:** after check-in a pass is issued and the badge is shown for printing. *Check out → Badge*
  reprints it (the old badge's QR stops working at once).
- **Check-out by QR:** *Scan badge with camera*, or scan with a USB scanner into the check-out box. The guard sees
  the visitor, photo and belongings and confirms; scanning alone never checks anyone out.

### Photo storage (decision)

Photos are files in a **private folder on the API server** (`CG_PHOTO_DIR`, required in production; development
default `.dev/photos`). They are never served directly and never under `web/`. Each upload is decoded, checked
(JPEG/PNG/WebP, 160×120 to 4096×4096, at most 12 M pixels, at most `CG_PHOTO_MAX_BYTES`, default 2 MB) and
**re-encoded** as a fresh JPEG of at most 1024 px. That removes EXIF/GPS metadata and anything hidden in the
file. Files get random 128-bit names (never the CNIC). The `photos` collection holds the name and metadata.
The API never returns the name, path or folder: images are only reachable through `GET /api/v1/photos/{id}`,
which checks the session on every request and is never cached. Administrators may see any photo. Guards may see
only a visitor's current photo or the photo of a visit still inside (the photos needed at the gate); anything
else is refused and audited. **Backups must include `CG_PHOTO_DIR` together with the database.** Nothing is
deleted automatically yet: retention is decided in production hardening (`photos.captured_at` is indexed for it).

### Pass security

The QR holds only `CGP1:` + 64 random hex digits (256 bits): no name, ID number, phone or visit number. The
database stores only the SHA-256 of the token, so a copy of the database cannot print working badges. The server
looks the token up on every scan; nothing in it can be edited to point at another visit, and no signature is
needed because the QR carries no claims. A pass stops working when the visitor is checked out (a replayed scan
only shows "already checked out"), when a badge is reprinted (`pass_replaced`), when revoked (`pass_revoked`)
or after `CG_PASS_VALID_HOURS` (default 24, `pass_expired`). Check-in never accepts a pass. Rejected scans are
audited (`PASS_REJECTED`). Scans are sent in the request body, never in a URL (proxy logs).

### Badge printing

The badge is a browser print layout: a CR80 card, **54 × 86 mm portrait**, printed through the normal print
dialog (only the badge is printed). It shows the organisation (`CG_ORGANIZATION_NAME`), visitor name, visit
number, host, department, check-in time and gate, the QR and its validity. It never shows the ID number or
phone. For other label stock, change the sizes in `web/src/app/globals.css` (section "Visitor badge").

### Manual acceptance test (real hardware, not automated)

See **Production operations → Hardware acceptance tests** below. The automated tests use Edge's fake webcam
and check the print layout as a PDF; real webcams, badge printers and QR scanners are tested by hand on each
gate PC, over HTTPS.

## Production operations (Phase 7A)

This part is for the administrator who installs and runs the system on the gate server. It assumes no
knowledge of the code. Everything named `*.ps1` is in `deploy\windows\`; run PowerShell **as Administrator**.

### Architecture

```
Gate PC (browser only) ──HTTPS 443──> CGVMS-Proxy (Caddy) ──/api/*──> CGVMS-API (FastAPI, 127.0.0.1:8000) ──TLS + login──> CGVMS-MongoDB (127.0.0.1:27018)
                         (80 → 443)                       └─else────> CGVMS-Web (Next.js, 127.0.0.1:3000)
                                                          CGVMS-API ──> private photo folder (CG_PHOTO_DIR)
```

- Gate PCs need **only a browser** (Edge or Chrome), the site name in DNS, and (if the internal CA is used)
  the CA's root certificate. They never get Python, Node.js, MongoDB, source code, `.env` or passwords.
- Only the proxy listens on the network (443, and 80 which only redirects to HTTPS). The API, the web server
  and MongoDB listen on `127.0.0.1` only: nothing outside the server can reach them.
- The **legacy desktop MongoDB service (port 27017, database `century_gate_system`) is not used, changed or
  stopped**. The web application runs its own MongoDB instance on port 27018. Every script refuses port 27017,
  and the API refuses the legacy database name.

| Service | Program | Listens on | Runs as | Logs |
| --- | --- | --- | --- | --- |
| `CGVMS-MongoDB` | `mongod --config C:\CenturyGateVMS\mongodb\mongod.conf` | 127.0.0.1:27018 (TLS only) | `NT SERVICE\CGVMS-MongoDB` | `mongodb\log\mongod.log` |
| `CGVMS-API` | `python -m app.serve` (production server, no reload, no API docs) | 127.0.0.1:8000 | `NT SERVICE\CGVMS-API` | `logs\api\` |
| `CGVMS-Web` | `next start` of the production build | 127.0.0.1:3000 | `NT SERVICE\CGVMS-Web` | `logs\web\` |
| `CGVMS-Proxy` | Caddy (`deploy\windows\caddy\Caddyfile`) | 0.0.0.0:443 and :80 | `NT SERVICE\CGVMS-Proxy` | `logs\proxy\` |

All four start automatically at boot and restart themselves after a crash (10 s, 30 s, then 2 min).
`CGVMS-API` waits for `CGVMS-MongoDB`; `CGVMS-Web` waits for `CGVMS-API`.

### Server requirements

- Windows Server 2019 or later (or Windows 10/11 Pro for a small site), 4 CPU cores, 8 GB RAM.
- Disk: 20 GB for the system and the application, plus the photo folder (about 100 KB per visitor photo,
  roughly 4 GB per 100 visitors a day for a year) on a data drive if possible.
- A DNS name for the server that the gate PCs use, e.g. `vms.century.local`.
- A backup destination on **another machine or disk** (a network share or a backup drive).
- Software (install for **all users**, so the service accounts can run it):
  - Python 3.12 (python.org installer, "Install for all users") → `C:\Program Files\Python312`
  - Node.js 24 LTS → `C:\Program Files\nodejs`
  - MongoDB Community Server 8.x (the MSI; **untick "Install MongoD as a Service"**, the installer's own
    service is not used; the legacy 27017 service, if present, stays as it is)
  - MongoDB Database Tools 100.x (zip, for `mongodump`/`mongorestore`) → `C:\CenturyGateVMS\tools\mongodb-database-tools`
  - Caddy 2.x for Windows (caddyserver.com, verify the checksum) → `C:\CenturyGateVMS\tools\caddy.exe`
  - WinSW 2.12 (`WinSW-x64.exe` from github.com/winsw/winsw releases) → `C:\CenturyGateVMS\tools\WinSW-x64.exe`

### Folder layout on the server

| Folder | Contents | Who may read it |
| --- | --- | --- |
| `C:\CenturyGateVMS\app` | This repository (a release), incl. `api\.env` | services (read); `api\.env`: CGVMS-API only |
| `...\config\cgvms.psd1` | Settings for the operations scripts (no passwords) | Administrators |
| `...\secrets\` | Database connection files and the MongoDB admin password | Administrators, SYSTEM |
| `...\tls\mongodb\` | Database certificate, CA, replica-set key file | CGVMS-MongoDB (the API: `ca.pem` only) |
| `...\tls\web\` | HTTPS certificate and key (company CA) | CGVMS-Proxy |
| `...\mongodb\` | `mongod.conf`, `data\`, `log\` | CGVMS-MongoDB |
| `...\logs\api|web|proxy` | Service logs (rotated) | the service, Administrators |
| `...\status\` | Backup, restore-test and health results | Administrators, SYSTEM |
| `...\backup\staging\` | Last 3 local dumps (not a real backup) | Administrators, SYSTEM |
| `D:\CenturyGateVMS-Photos` | Visitor photos (`CG_PHOTO_DIR`) | CGVMS-API (modify), SYSTEM (backup) |

`install-services.ps1` sets these permissions and removes the default "Authenticated Users" rights, so an
ordinary user logged on to the server can neither read the data nor change the application.

### Installation (first time)

1. **Software**: install everything listed under *Server requirements*.
2. **Application**: copy the release to `C:\CenturyGateVMS\app` (e.g. `git clone` then `git checkout <tag>`).
3. **API environment** (PowerShell in `C:\CenturyGateVMS\app\api`):
   ```powershell
   & 'C:\Program Files\Python312\python.exe' -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt -r ..\deploy\requirements-ops.txt
   ```
4. **Web build** (in `C:\CenturyGateVMS\app\web`): `npm ci` then `npm run build`. Never run `npm run dev` on the server.
5. **Settings for the scripts**: copy `deploy\windows\cgvms.example.psd1` to `C:\CenturyGateVMS\config\cgvms.psd1`
   and set `SiteName`, `PhotoDir`, `MongoBin`, `HealthUrl` and `BackupDestination`.
6. **Photo folder**: create it (e.g. `D:\CenturyGateVMS-Photos`). The API refuses to start if it is missing.
7. **Database certificates and key file** (in `C:\CenturyGateVMS\app`):
   ```powershell
   api\.venv\Scripts\python deploy\mongodb\cgvms_mongo.py prepare --tls-dir C:\CenturyGateVMS\tls\mongodb
   ```
   Then **move `C:\CenturyGateVMS\tls\mongodb\ca.key` off the server** (e.g. to a USB key in the safe). It is
   only needed to renew the database certificate.
8. **MongoDB configuration**: copy `deploy\mongodb\mongod.conf.template` to `C:\CenturyGateVMS\mongodb\mongod.conf`
   (adjust paths if you use other folders) and create `mongodb\data` and `mongodb\log`.
9. **Database accounts** (once): start MongoDB in a console window, create the accounts, stop it again:
   ```powershell
   & 'C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe' --config C:\CenturyGateVMS\mongodb\mongod.conf
   # in a SECOND window:
   api\.venv\Scripts\python deploy\mongodb\cgvms_mongo.py init --tls-dir C:\CenturyGateVMS\tls\mongodb --secrets-dir C:\CenturyGateVMS\secrets
   ```
   This creates the replica set and the accounts and writes their connection files into `secrets\`. Put the
   `cgvms_root` password (`secrets\mongodb-root.txt`) into the company password manager.
10. **API settings**: copy `deploy\windows\api.env.template` to `C:\CenturyGateVMS\app\api\.env`. Paste the line
    from `secrets\cgvms_app.uri.txt` into `CG_MONGO_URI`, and set `CG_PHOTO_DIR` and `CG_ORGANIZATION_NAME`.
11. **Schema and first administrator** (MongoDB still running in the console):
    ```powershell
    powershell -ExecutionPolicy Bypass -File deploy\windows\migrate.ps1
    cd api; .venv\Scripts\python -m app.cli create-admin --username admin
    ```
    Then stop the console MongoDB (Ctrl+C).
12. **HTTPS certificate**: see *HTTPS* below. Copy `deploy\windows\services\CGVMS-Proxy.xml` to
    `C:\CenturyGateVMS\services\` and set `CGVMS_SITE` (and `CGVMS_TLS_MODE`) there.
13. **Services**: `powershell -ExecutionPolicy Bypass -File deploy\windows\install-services.ps1`
    (use `-DryRun` first to see what it will do). It ends with a health check.
14. **Scheduled tasks**: `powershell -ExecutionPolicy Bypass -File deploy\windows\register-tasks.ps1`.
15. **DNS**: point `SiteName` at the server. From a gate PC, open `https://<SiteName>`: no certificate warning.
16. **Prove the backups**: run `backup.ps1` and then `restore-test.ps1` by hand once and check both say PASSED.

### Configuration reference

`C:\CenturyGateVMS\app\api\.env` (template: `deploy\windows\api.env.template`) holds the only secret the
application uses at runtime (`CG_MONGO_URI`). The API **refuses to start in production** if:
- `CG_MONGO_URI` has no user/password, no `tls=true`, or any of `tlsAllowInvalidCertificates`,
  `tlsAllowInvalidHostnames`, `tlsInsecure`;
- `CG_PHOTO_DIR` is not set, does not exist, is not a folder or is not writable;
- `CG_COOKIE_SECURE` is false; or `CG_MONGO_DB` is the legacy database name.
It prints only the reason, never the value. Other settings: `CG_ORGANIZATION_NAME` (badges), `CG_SESSION_IDLE_MINUTES`
(15), `CG_SESSION_MAX_HOURS` (12), `CG_PASS_VALID_HOURS` (24), `CG_LOG_LEVEL` (INFO), `CG_TIMEZONE`
(Asia/Karachi), `CG_TRUSTED_PROXIES` (the local proxy). There is no separate "public origin" or CSRF
setting: session cookies are host-only (`__Host-`), HTTPS-only and SameSite=Strict, and every change needs the
CSRF token.

The web service has no secrets (only `API_INTERNAL_URL=http://127.0.0.1:8000`); no `NEXT_PUBLIC_*` variables
exist. The proxy's settings are in `services\CGVMS-Proxy.xml` (`CGVMS_SITE`, `CGVMS_TLS_MODE`, certificate paths).

### Starting, stopping, restarting

```powershell
Get-Service CGVMS-*                                   # status of all four
Restart-Service CGVMS-API                             # after changing api\.env
Restart-Service CGVMS-Proxy                           # after changing the certificate or Caddyfile
Stop-Service CGVMS-Proxy, CGVMS-Web, CGVMS-API, CGVMS-MongoDB      # full stop (this order)
Start-Service CGVMS-MongoDB, CGVMS-API, CGVMS-Web, CGVMS-Proxy     # full start (this order)
powershell -ExecutionPolicy Bypass -File C:\CenturyGateVMS\app\deploy\windows\check-health.ps1   # verify
```

Health in a browser (from any gate PC): `https://<SiteName>/api/v1/health/ready` answers
`{"status":"ready", ...}` with the state of the database, schema, transactions and photo storage. It never
shows host names, paths or errors. The dashboard's *System status* card shows the same.

### Updating to a new version

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\backup.ps1        # 1. fresh backup
Stop-Service CGVMS-Proxy, CGVMS-Web, CGVMS-API                            # 2. stop (MongoDB keeps running)
# 3. replace C:\CenturyGateVMS\app with the new release (keep api\.env!), then:
cd C:\CenturyGateVMS\app\api; .venv\Scripts\python -m pip install -r requirements.txt
cd ..\web; npm ci; npm run build
powershell -ExecutionPolicy Bypass -File ..\deploy\windows\migrate.ps1  # 4. schema (with the migration account)
Start-Service CGVMS-API, CGVMS-Web, CGVMS-Proxy                           # 5. start and check
powershell -ExecutionPolicy Bypass -File ..\deploy\windows\check-health.ps1
```

### HTTPS

The camera only works on HTTPS (or on the server itself as `localhost`), so gate PCs **must** use HTTPS. Plain
`http://` requests are answered only with a redirect to HTTPS, and browsers are told to use HTTPS only (HSTS).
TLS certificate validation is never switched off anywhere.

Choose one (`CGVMS_TLS_MODE` in `services\CGVMS-Proxy.xml`):

- **`company` (recommended)**: a certificate from the company's certificate authority (e.g. Active Directory
  Certificate Services) for `SiteName`. Put the certificate (PEM, with intermediates) in
  `C:\CenturyGateVMS\tls\web\cert.pem` and its key in `tls\web\key.pem`. Gate PCs in the domain already trust
  the company CA. **Renewal**: before it expires (the health check warns 30 days ahead), replace both files and
  `Restart-Service CGVMS-Proxy`.
- **`internal`**: only if the company has no CA. Caddy runs its own small CA and renews the server certificate
  automatically. Its root certificate (`C:\CenturyGateVMS\caddy-data\pki\authorities\local\root.crt`, valid
  10 years) must be installed as a *Trusted Root Certification Authority* on every gate PC (Group Policy) and on
  the server itself (for the health check). Never click through a certificate warning instead.

A public certificate (e.g. Let's Encrypt) is only possible for a public DNS name and is not needed on an
internal network.

### MongoDB security

- **Separate instance**: service `CGVMS-MongoDB`, port **27018**, data in `C:\CenturyGateVMS\mongodb\data`.
- **Network**: `bindIp: 127.0.0.1`: only programs on the server can connect; the firewall is not even needed for it.
- **TLS required** (`requireTLS`, TLS 1.2+) with a private database CA. The API checks the database certificate
  (`tlsCAFile`) and its name (`localhost`).
- **Login required** (`authorization: enabled`) and a replica-set key file.
- **Single-node replica set** (`cgvms`): the application needs transactions (check-in, check-out). One server
  is enough; there is no cluster to run.
- **Accounts** (created by `cgvms_mongo.py init`, passwords are random):

| Account | Rights | Used by | Connection file |
| --- | --- | --- | --- |
| `cgvms_app` | read/write on `century_gate_vms` only | the API (`api\.env`) | `secrets\cgvms_app.uri.txt` |
| `cgvms_migrate` | + database admin on `century_gate_vms` only | `migrate.ps1` | `secrets\cgvms_migrate.uri.txt` |
| `cgvms_backup` | `backup` + log rotation | `backup.ps1` | `secrets\mongodump.yaml` |
| `cgvms_root` | administrator (break glass) | people, rarely | `secrets\mongodb-root.txt` → password manager |

  The application account cannot change the schema, read any other database (including the legacy one),
  manage accounts or shut the server down (all checked).
- **Certificate renewal**: the server certificate lasts 27 months (the health check warns 30 days ahead). Bring
  `ca.key` back, run `cgvms_mongo.py prepare --tls-dir C:\CenturyGateVMS\tls\mongodb --renew`,
  `Restart-Service CGVMS-MongoDB` (the API reconnects by itself), then remove `ca.key` again.

### Photos

- `CG_PHOTO_DIR` (and `PhotoDir` in `cgvms.psd1`, the same path): a private folder, preferably on a data drive.
  Only `CGVMS-API` (and SYSTEM for backups) can read it. Neither the proxy nor Next.js serves it. The only way
  to see a photo is `GET /api/v1/photos/{id}`, which checks the login and role every time (Phase 4 rules).
  File names are random; no path or file name ever reaches a browser.
- The API refuses to start if the folder is missing or not writable. It never re-creates a vanished folder: if
  the drive disappears while running, photo uploads fail with a clear message ("continue without a photo"),
  and the health check reports `photo_storage: unavailable`.
- Photos are part of the data: the backup copies them, and a restore needs them.

### Backups

`CGVMS Backup` runs `backup.ps1` every night (02:00) as SYSTEM:

1. **Database**: `mongodump --oplog` of the whole instance: a consistent point-in-time copy of all
   collections (users, visitors, visits, watchlist, hosts, departments, gates, audit logs, photo metadata,
   sessions, settings, counters) and the database accounts.
2. **Photos**: new photo files are copied to `<BackupDestination>\photos` (after the dump, so every photo in the
   dump has its file). Existing backup copies are never overwritten or deleted, so a damaged live file cannot
   spoil the backup.
3. **Verification**: SHA-256 of the dump recorded in `manifest.json`, re-checked after copying to
   `<BackupDestination>\database\cgvms-YYYYMMDD-HHMMSS\`. The photo count in the backup must not be lower than
   the live count.
4. **Retention** (only folders named `cgvms-YYYYMMDD-HHMMSS` are ever deleted): every backup of the last
   `BackupKeepDays` (35) days, plus the newest backup of each of the last `BackupKeepMonthly` (12) months. Photo
   backups are kept indefinitely (photos are never deleted by the application; a retention policy for visitor
   photos is still to be decided, see *Pending decisions*). The last 3 dumps also stay in `backup\staging`.
5. **Failure detection**: exit code, event log (2000 success, 2001 failure), `status\backup-<date>.log`,
   `status\last-backup.json`. The health check raises an alarm when the last good backup is older than
   26 hours.

Backups contain personal data **and** the database accounts' password hashes: give the backup share access only
to the server's computer account (or the backup account) and the administrators. The secrets folder is not
part of the backup: keep the `cgvms_root` password and a copy of `secrets\` in the password manager / safe.

### Restore test (monthly, automatic)

`CGVMS Restore test` runs `restore-test.ps1` on the first Sunday of each month (or run it by hand). It never
touches the live database or photo folder:

1. picks the newest backup and checks its SHA-256;
2. starts a **temporary** MongoDB (own folder under `restore-test\`, port 27029, loopback, TLS);
3. restores the dump point-in-time, and copies the photo backup into a temporary folder;
4. runs `python -m app.cli restore-check`: record counts (users, visitors, visits, watchlist, audit logs,
   photos), every photo file present with its recorded SHA-256, visit/visitor photo links intact, and, with the
   real API against the copy, logins, roles, the watchlist rules and the photo rules (admin sees photos, a guard
   only the ones needed at the gate, anonymous nobody);
5. deletes the copy. Result: event 3000 (passed) / 3001 (failed) and `status\restore-test-<time>.json`.

### Disaster recovery (the server or the database is lost)

1. Rebuild the server with *Installation* steps 1–8. Reuse the `tls\mongodb` files and `ca.key` from the safe if
   you have them, otherwise `prepare` new ones.
2. Restore the database into the new, empty instance. It starts **without** login for this step, loopback only:
   copy `mongod.conf` to `mongod-restore.conf` and delete its `security:` section, then:
   ```powershell
   & 'C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe' --config C:\CenturyGateVMS\mongodb\mongod-restore.conf
   # second window:
   api\.venv\Scripts\python deploy\mongodb\cgvms_mongo.py init-temp --tls-dir C:\CenturyGateVMS\tls\mongodb --port 27018 --replica-set cgvms
   C:\CenturyGateVMS\tools\mongodb-database-tools\bin\mongorestore.exe "--uri=mongodb://localhost:27018/?directConnection=true&tls=true&tlsCAFile=C:/CenturyGateVMS/tls/mongodb/ca.pem" --gzip "--archive=<BackupDestination>\database\<newest>\mongodb.archive.gz" --oplogReplay
   ```
   Stop that MongoDB (Ctrl+C) and delete `mongod-restore.conf`. The dump contains the database accounts, so the
   connection files from the password manager work again. (Rehearsed on 27 Sept 2026: 34 documents restored;
   after restarting with login, the application account connected with its original password; anonymous
   access was refused.)
3. Copy the photos back: `robocopy <BackupDestination>\photos D:\CenturyGateVMS-Photos *.jpg /E`.
4. Continue with *Installation* steps 10 and 12–16 (`api\.env` from the saved connection files), then run
   `cd C:\CenturyGateVMS\app\api; .venv\Scripts\python -m app.cli verify-data`: it must say `"ok": true`.

### Monitoring

`CGVMS Health check` runs `check-health.ps1` every 5 minutes and checks: the four services; `HealthUrl`
(through the real HTTPS name and certificate: proxy, API, database, schema, transactions, photo folder); the
HTTPS and database certificates (warning 30 days before expiry); free space on every drive holding
application data (below 15 % or 10 GB); the age of the last good backup (26 hours). The result is written to
`status\health.json`. Problems go to the **Windows Application event log**, source `CenturyGateVMS`:

| Event ID | Meaning |
| --- | --- |
| 1001 / 1000 | health problem found / healthy again (only on a change, and once a day while it lasts) |
| 2001 / 2000 | backup failed / succeeded |
| 3001 / 3000 | restore test failed / passed |

Point the company's monitoring at these events, or attach an e-mail action to them in Task Scheduler.

**Logs** (no passwords, tokens, QR codes, ID numbers or query strings are written; request IDs stay intact for
correlation):

| Log | Where | Rotation |
| --- | --- | --- |
| API (JSON lines, one per request) | `logs\api\CGVMS-API.err.log` | 10 files × 10 MB, oldest deleted |
| Web | `logs\web\` | 10 × 10 MB |
| Proxy (errors only; no access log on purpose) | `logs\proxy\` | 10 × 10 MB |
| MongoDB | `mongodb\log\mongod.log` | rotated nightly by the backup job, kept 30 days |
| Backups, restore tests, health | `status\*.log`, `status\*.json` | kept 60 days (`StatusKeepDays`) |
| Service start/stop | `logs\*\*.wrapper.log`, Windows *System* event log | Windows |

### Recovery runbook

| Symptom | What to do |
| --- | --- |
| Gate PCs show "cannot reach the server" | `Get-Service CGVMS-*`. Start what is stopped (in the order above). Check the firewall allows 443. |
| **API stopped** / keeps restarting | Read the end of `logs\api\CGVMS-API.err.log`: a configuration problem prints `ERROR: configuration is not valid: <reason>` (no secrets). Fix `api\.env`, `Restart-Service CGVMS-API`. |
| **Web stopped** | `logs\web\`. Usually a missing build: `cd app\web; npm run build`, `Start-Service CGVMS-Web`. |
| **MongoDB stopped** | `mongodb\log\mongod.log` (look for `"s":"F"` / `"s":"E"`). Common: disk full, a certificate or the key file unreadable, a newer MongoDB version. `Start-Service CGVMS-MongoDB`; the API reconnects by itself. |
| **Certificate expired** (browser warning) | HTTPS: replace `tls\web\cert.pem`/`key.pem` (company CA) and `Restart-Service CGVMS-Proxy`. Database: see *MongoDB → Certificate renewal*. |
| **Disk full** | Photos and the database grow; logs are bounded. Free space or extend the drive; move old `backup\staging` copies away. MongoDB stops writing when the disk is full: check it afterwards. |
| **Backup failed** (event 2001) | `status\backup-<date>.log` names the step. Usual causes: backup share unreachable or no rights, disk full. Fix, then run `backup.ps1` by hand and check event 2000. |
| **Restore test failed** (event 3001) | `status\restore-test-<time>.json` lists what did not match. Treat it as "the backups may be unusable" until solved. |
| **Photo folder unavailable** | Health shows `photo_storage: unavailable`; gates can still check visitors in without photos. Reconnect the drive or share (same path), check the CGVMS-API account can write, `Restart-Service CGVMS-API`. Never create an empty folder in its place. |

### Deployment security review (Phase 7A)

| Check | Result |
| --- | --- |
| MongoDB not reachable from the network | `bindIp: 127.0.0.1` (verified: listening on 127.0.0.1 only) |
| MongoDB requires login | `authorization: enabled`; anonymous access refused (verified) |
| MongoDB TLS validated | `requireTLS`; plain connections dropped; a client without the database CA is refused; the API refuses URIs that disable checks (tested) |
| Least-privilege application account | `readWrite` on `century_gate_vms` only; no schema changes, no other databases, no accounts, no shutdown (verified) |
| Backend secrets server-only | only in `api\.env` (readable by CGVMS-API only) and `secrets\`; nothing in service definitions, Next.js or the browser; no `NEXT_PUBLIC_*` |
| Photo folder private | outside `web\`; not served by the proxy or Next.js (verified 404); API-authorised access only |
| No HTTP for gate PCs | port 80 only redirects to HTTPS (to the configured name); HSTS one year |
| HTTPS validation | company or internal CA; never disabled |
| Debug / reload off | `app.serve` refuses non-production settings and never reloads; API docs 404 in production (verified); `next start`, never `next dev` |
| Safe errors | unchanged from Phase 1: `{"error": {...}}`, no stack traces, no paths |
| Logs | no credentials, tokens, QR codes, ID numbers or query strings (verified on a production-mode run); proxy access log off |
| Backups not web-accessible | on another machine/disk; nothing under the proxy's or Next.js's reach |
| `.env` not served | `/.env`, `/api/.env`, `/web/.env.local` → 404 (verified) |
| Admin surfaces | Caddy admin endpoint off; MongoDB admin only via `cgvms_root` on the server |

### Hardware acceptance tests (real devices, not yet done)

Do these on **each gate PC**, over **HTTPS** (`https://<SiteName>`), with the real webcam, badge printer and
scanner. Nothing here has been tested on real hardware yet.

**Webcam**: check in a visitor and at the photo step:
- first use: the browser asks for camera permission; allow it (and check the permission is remembered);
- the photo is sharp and the face recognisable in the gate's lighting;
- deny the permission once: the page explains how to allow it;
- with the camera open in another program (e.g. Teams): "being used by another program";
- with the webcam unplugged: "No camera was found";
- unplug it while the preview runs: the preview stops (the page does not detect this by itself; known
  limitation). "Back" and "Review" again restart the camera step; record what the guard sees;
- the webcam light goes off after "Take photo", and also when leaving the step without a photo;
- on `http://` (if someone types it) the browser is redirected to HTTPS, and the camera works there.

**Badge printer**:
- in the print dialog: the badge printer, paper 54 × 86 mm (or the configured card), margins *None*, scale
  100 %, *Headers and footers* off; save these settings once per gate PC;
- only the badge is printed (no menu, no other page), nothing is cut off, one card per badge;
- text readable; the QR code scans from the printed card (webcam and USB scanner).

**QR scanning**:
- USB scanner into the check-out box, and *Scan badge with camera*: both open the confirmation with the photo;
- printed, laminated, and worn/creased badges;
- scan the same badge after check-out: "already checked out", nothing changes;
- *Badge* (reprint) on a visitor inside, then scan the OLD badge: "replaced"; the new badge works;
- a badge older than `CG_PASS_VALID_HOURS`: "expired", check-out by visit number still works.

A failing hardware test is a reason to adjust the device or its settings (print dialog, focus, lighting), not
the pass security.

### Pending decisions (not implemented on purpose)

- **Photo policy**: a photo is still optional ("Continue without a photo"). Whether every visitor must have one
  is decided after the hardware tests.
- **Retention**: how long ID numbers, photos and visit records are kept, and automatic clean-up, are decided
  later; nothing is deleted automatically yet (the backups keep photos indefinitely until then).
- **Old desktop history**: not imported; the legacy database stays untouched.

## Status

Phase 4 (watchlist management, photos, QR passes, badges, scan-to-check-out) and Phase 7A (production
infrastructure: HTTPS, MongoDB login + TLS, Windows services, backups with restore tests, monitoring) are
complete. Next: real deployment and hardware testing (see *Hardware acceptance tests*), then Phase 5.
