# Century Gate VMS — Web Application

Web-based Visitor Management System replacing the Century Gate desktop application.

```
Browser ──HTTP :3000──> Next.js web server (frontend/) ──/api/──> FastAPI (backend/, 127.0.0.1) ──> MongoDB (127.0.0.1)
```

- The browser never connects to MongoDB; only the API holds database credentials.
- Every access decision is made by the API. The frontend only hides what a role cannot use.
- The API uses its own database, `century_gate_vms`. It refuses to start with the legacy
  desktop database name (`century_gate_system`) and refuses to migrate a database containing
  legacy collections. The legacy database is never read or modified.

## Repository layout

| Path | What |
| --- | --- |
| `backend/` | FastAPI backend (Python 3.12, Pydantic v2, PyMongo async) |
| `frontend/` | Next.js 16 frontend (App Router, React 19, TypeScript, Tailwind CSS 4) |
| `scripts/dev_mongo.py` | Starts an isolated local MongoDB replica set for development |
| `deploy/` | Production on one Windows PC: start/stop scripts, health check (see "Production on one Windows 11 PC") |
| `.dev/` | Local development data and logs (git-ignored) |

## Local development (Windows)

Requirements: Python 3.12, Node.js 24, MongoDB Community Server 8.x installed (the binary is used;
the MongoDB Windows service is not touched).

### 1. Development database

```powershell
backend\.venv\Scripts\python scripts\dev_mongo.py start     # 127.0.0.1:27018, replica set "cgvms-dev"
backend\.venv\Scripts\python scripts\dev_mongo.py status
backend\.venv\Scripts\python scripts\dev_mongo.py stop
```

This runs a **separate** `mongod` on port 27018 with its data in `.dev/mongo/`. The MongoDB Windows
service on port 27017 (which holds the legacy desktop database) is never used or reconfigured.
A replica set is required because check-in writes a visit and its audit record in one transaction.

### 2. API

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env
.venv\Scripts\python -m app.cli migrate          # creates collections, validators, indexes (idempotent)
.venv\Scripts\python -m app.cli create-admin --username admin   # first administrator (asks for a password)
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000
```

The first administrator is created on the server: `start-dev.bat` and `start-production.bat` run
`python -m app.cli first-admin`, which creates **admin / admin1234** when the database has no account yet
(a new password must be chosen at the first login; it does nothing once any account exists). `create-admin`
creates one with your own password instead. There is no web "first-run" page, because it would be reachable by
anyone on the network.

**Refused entries (reports).** Every entry refused because of the watchlist (at check-in, or at the check-in
lookup) is recorded in `entry_denials`, after its audit entries and never instead of them: if that reporting
write fails, the visitor is still refused and the failure is logged. `python -m app.cli backfill-entry-denials`
creates the missing records from the `WATCHLIST_MATCH` audit entries: run it once after upgrading to schema
version 6 (for refusals recorded before), and again whenever the log reports "Entry denial not recorded". It is
safe to run repeatedly and concurrently, never changes an existing record, and prints what it did (scanned,
created, already present, incomplete). Older refusals keep only what the audit recorded: names and purpose are
empty, and refusals at the lookup before version 6 were not recorded at all.

- Health: http://127.0.0.1:8000/api/v1/health/live and `/api/v1/health/ready`
- Interactive docs (development only): http://127.0.0.1:8000/api/docs
- Tests: `.venv\Scripts\python -m pytest` (needs the development database running)
- Lint: `.venv\Scripts\ruff check app tests ..\scripts`

### 3. Web

```powershell
cd frontend
npm install
copy .env.example .env.local
npm run dev                       # http://localhost:6543 (forwards /api/* to the API)
npm run typecheck ; npm run lint ; npm test ; npm run build
npm run test:e2e                  # end-to-end tests in Microsoft Edge (see below)
```

Open the app via **http://localhost:6543**, not 127.0.0.1: the Next.js dev server only serves its
scripts to `localhost` by default.

**End-to-end tests** start their own isolated stack (API on :8001 with database `cgvms_e2e`, web on
:3001), reset that database and create an E2E administrator. They never touch the development database.
They need the development MongoDB running, and no other `next dev` server running for `frontend/`.

## Configuration

All API settings are environment variables with the `CG_` prefix (see `backend/.env.example`).
Secrets live only in the server environment, never in the frontend or the repository.

## Accounts & security (Phase 2)

- Roles: **Administrator** (everything) and **Guard** (gate work). The API checks the role on every
  request; the frontend only hides what a role cannot use.
- Passwords: argon2id; at least 8 characters, not containing the username, not a common password.
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
  department, reason, vehicle, belongings → review → confirm. The visit number (`V-YY-MON-DD-NNN`, e.g. `V-26-OCT-02-001`:
  the first visit on 2 October 2026; counted per day at the gate) is shown on success. A host who is not in the directory can be typed in; that visit is flagged.
- **Check-out:** by visit number or ID number (Enter), or from the list of visitors inside. Repeating a
  check-out is harmless.
- **Visitors / Visit history:** search by name, ID or phone; history filters by date, status, gate and
  department. Opening a visitor's record and every ID lookup is audited (ID numbers are masked in the
  audit log). Only administrators can edit a visitor's details.
- The database guarantees one active visit per visitor, gap-free visit numbers per day and
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
default `.dev/photos`). They are never served directly and never under `frontend/`. Each upload is decoded, checked
(JPEG/PNG/WebP, 160×120 to 4096×4096, at most 12 M pixels, at most `CG_PHOTO_MAX_BYTES`, default 2 MB) and
**re-encoded** as a fresh JPEG of at most 1024 px. That removes EXIF/GPS metadata and anything hidden in the
file. Files get random 128-bit names (never the CNIC). The `photos` collection holds the name and metadata.
The API never returns the name, path or folder: images are only reachable through `GET /api/v1/photos/{id}`,
which checks the session on every request and is never cached. Administrators may see any photo. Guards may see
only a visitor's current photo or the photo of a visit still inside (the photos needed at the gate); anything
else is refused and audited. Nothing is
deleted automatically yet: retention is decided in production hardening (`photos.captured_at` is indexed for it).

### Pass security

The QR holds only `CGP1:` + 64 random hex digits (256 bits): no name, ID number, phone or visit number. The
database stores only the SHA-256 of the token, so a copy of the database cannot print working badges. The server
looks the token up on every scan; nothing in it can be edited to point at another visit, and no signature is
needed because the QR carries no claims. A pass stops working when the visitor is checked out (a replayed scan
only shows "already checked out"), when a badge is reprinted (`pass_replaced`), when revoked (`pass_revoked`)
or after gate closing (`CG_PASS_DAY_END_HOUR`/`MINUTE`, default 16:30 local, `pass_expired`). Check-in never accepts a pass. Rejected scans are
audited (`PASS_REJECTED`). Scans are sent in the request body, never in a URL (proxy logs).

### Badge printing

The badge is a browser print layout: a CR80 card, **54 × 85.6 mm portrait** (standard ID-card size), printed through the normal print
dialog (only the badge is printed). It shows the organisation (`CG_ORGANIZATION_NAME`) and site address at the top, visitor name, visit
number, host, department, check-in time and gate, the QR and its validity. It never shows the ID number or
phone. For other label stock, change the sizes in `frontend/src/app/globals.css` (section "Visitor badge").

### Manual acceptance test (real hardware, not automated)

See **Production operations → Hardware acceptance tests** below. The automated tests use Edge's fake webcam
and check the print layout as a PDF; real webcams, badge printers and QR scanners are tested by hand on each
gate PC.

## Host arrival notifications (Phase 6A)

When a visitor checks in for a **registered host** (a host from the directory):

- **In-app:** if the host has a **Linked app account**, that app user gets a notification under the bell
  in the top bar ("Ali Khan has arrived to visit Sara Ahmed", gate, department, time). Administrators set the
  link on the **Hosts** page. It is an optional relationship between a host directory entry and an existing
  Admin or Guard user; hosts themselves never log in. Every user sees only their own notifications (the
  server takes the recipient from the session, never from the request). *Notifications* in the bell opens
  the full list; items are marked read by clicking them or with *Mark all as read*.
- **E-mail:** if the host has an e-mail address and the server has an SMTP server configured, the host
  receives a short e-mail (visitor name, arrival time, gate, department, reason; never the ID number, phone,
  visit number or any internal id).
- A host without a linked account and without an e-mail address, and a host typed in by hand at the gate
  (not in the directory), get nothing. Those visits stay flagged as "host not listed" for review.
- **Department e-mail:** if the visited department has a **Notification email** (set on the **Departments**
  page), that address also receives an arrival e-mail ("Dear HR team, Ali Khan has arrived at the gate to
  visit Sara Ahmed"), for every check-in to that department, including hosts typed in by hand. It is a
  separate e-mail, not a copy, and is skipped when the address is the host's own. It never appears under
  the bell.

**Reliability.** The notification is written in the same database transaction as the check-in, so it
exists exactly when the visit does and is never created for a failed check-in. The check-in never waits for
e-mail: a background sender inside the API service sends it right afterwards. A mail server that is down,
slow or refusing only affects the e-mail's delivery state, never the gate.

| E-mail state | Meaning |
| --- | --- |
| `NONE` | nothing to send: the host has no address, or e-mail is switched off (no `CG_SMTP_HOST`) |
| `PENDING` | waiting to be sent, or to be retried |
| `SENDING` | being sent right now |
| `SENT` | accepted by the mail server |
| `FAILED` | refused permanently (e.g. unknown address, 550), after 5 attempts, or interrupted |

Retries after a temporary problem: 1, 5, 15 and 60 minutes later (5 attempts in about 81 minutes), then
`FAILED`. Only a short error code is kept (e.g. `SMTPRecipientsRefused 550`, `ConnectionRefusedError`).
**No duplicates:** each visit has at most one host notification and one department e-mail (unique keys
`HOST_VISITOR_ARRIVAL:<visit id>` and `DEPARTMENT_VISITOR_ARRIVAL:<visit id>` in the database), and each e-mail is claimed by one sender at a time. If the service stops in the middle of
sending, that e-mail is marked `FAILED` ("interrupted") rather than sent a second time.

**Configuration.** Generic SMTP, for any provider (Gmail / Google Workspace, Microsoft 365, Yahoo, Zoho,
cPanel webmail, a company mail server...): host, port, security, user name, password, sender. Only these
values decide how mail is sent; there is no provider-specific code. Which settings are used, decided at
every e-mail (no restart needed):

1. **Settings saved by an administrator** (API `GET/PUT/DELETE /api/v1/settings/email`; the screen comes
   in a later step). They win over the environment, even when switched off (then no e-mail is sent).
   The SMTP password is encrypted with `CG_SECRETS_KEY` (AES-256-GCM, like camera passwords) and never
   returned, logged or audited; changing the host, port, security or user name requires entering it again.
   `DELETE` removes the saved settings and password, so the environment applies again.
   `POST /api/v1/settings/email/test` sends one test e-mail with the settings in use (administrators only,
   one at a time) and returns a safe reason on failure (e.g. `EMAIL_AUTHENTICATION_FAILED`, `EMAIL_TLS_FAILED`).
2. Otherwise the **server environment** (`backend\.env`), as before: `CG_SMTP_HOST`, `CG_SMTP_PORT` (587),
   `CG_SMTP_SECURITY` (`starttls`, `ssl` or `none`), `CG_SMTP_USERNAME`, `CG_SMTP_PASSWORD`, `CG_SMTP_FROM`.
   The API refuses to start with a sender address missing, a username without a password, or (in
   production) a login over an unencrypted connection.
3. Otherwise e-mail is off.

Security `starttls` upgrades a plain connection (usually port 587); `ssl` is TLS from the start (usually
465); `none` is for an internal relay without login only (refused with a login in production). The
certificate of the mail server is always checked. `CG_SMTP_TIMEOUT_SECONDS` applies to both. The SMTP
password never appears in logs, and never unencrypted in the database. Providers that need an app password
(e.g. Gmail with 2-step verification) work by entering that app password; the VMS does no OAuth.

**Retention:** notifications are kept, like visits; nothing is deleted automatically. A retention period is
to be decided together with the other retention rules (proposal: 12 months).

## Gate cameras (Hikvision, in progress)

A Hikvision IP camera per gate can take the visitor's photo instead of the webcam. The **server** talks to
the camera (ISAPI over HTTP/HTTPS, Digest login, one still JPEG); gate PCs never do. Done so far: the camera
client and the administrators' settings API. Not yet: the admin screen and the check-in photo step (the
webcam works as before).

- **Settings:** `GET/PUT/DELETE /api/v1/gate-cameras[/{gate id}]`, administrators only: address, HTTP or
  HTTPS, port, channel (e.g. `101`), camera user name and password, timeout (1–30 s, default 5). Stored per
  gate in the `settings` collection (`gate_camera:<gate id>`); the gate itself is unchanged.
- **Password:** encrypted with AES-256-GCM before it is stored; the key is `CG_SECRETS_KEY` in the server
  environment (`python -m app.cli generate-secrets-key`). It is never returned, logged or audited (the audit
  only records that it changed). Without `CG_SECRETS_KEY` camera passwords cannot be saved; with a different
  key, saved passwords show as unreadable and must be entered again. **Back the key up separately from the
  database.** Changing the address, connection, port or user name requires entering the password again.
- **Tests:** `POST .../{gate id}/test` (reachable, login accepted, model and firmware) and
  `POST .../{gate id}/test-photo` (one picture, checked and scaled like a visitor photo, returned and never
  stored). One test per camera at a time: Hikvision locks the account after repeated failed logins, and a
  wrong password costs exactly one attempt.
- **Camera account:** create a dedicated camera user that may only view live video / take snapshots; do
  not use the camera's `admin` account.
- **HTTPS:** the certificate is always checked. A camera with its factory self-signed certificate is refused
  (`CAMERA_CERTIFICATE_UNTRUSTED`); until trusting a camera certificate is supported, use HTTP on a camera
  network that only the server can reach.
- **Not yet verified on a real camera.** The paths `/ISAPI/System/deviceInfo` and
  `/ISAPI/Streaming/channels/<channel>/picture` must be confirmed on the installed model.

## Production on one Windows 11 PC

The simplest production setup runs this project folder in production mode on one PC, as normal programs, for
gate PCs on the **organization's trusted network over plain HTTP**:

```
Gate PC browser ──HTTP :3000──> web server (node server.mjs, 0.0.0.0:6543) ──/api/*──> API (127.0.0.1:8000) ──> MongoDB (127.0.0.1:27018)
                                                                                        API ──> gate cameras (Hikvision)
```

- Gate PCs open `http://<this PC's name or IP>:6543`. No TLS, no certificate, no Caddy.
- Only the web server listens on the network. The API (8000) and MongoDB (27018, the project's own database in
  `.dev\mongo`) listen on 127.0.0.1 only and are never exposed; the browser reaches the API only through `/api/*`.
- The API runs with `CG_ENVIRONMENT=production` and `CG_DEPLOYMENT_MODE=http-lan`: the session cookies lose only
  their `Secure` flag (see *Configuration reference*). HTTP is **not encrypted**: passwords, session cookies and
  visitor data cross the LAN in clear text. Use it only on a network you trust; never expose port 6543 to the
  internet.
- Gate cameras (Hikvision) are read by the server and work over HTTP. Browsers allow the **webcam fallback** (and
  webcam QR scanning) only on HTTPS or on this PC itself, so a gate without a working gate camera has no photo
  capture or QR scanning on HTTP.
- A browser that opened the former HTTPS address (`https://<name>`) remembers HSTS for that name for up to a
  year and will refuse `http://<name>:6543`: use the IP address on that PC, or clear the HSTS entry for the name
  (Edge: `edge://net-internals/#hsts`, Chrome: `chrome://net-internals/#hsts`).
- **Windows Firewall is not part of this deployment**: no script changes it, and nothing needs to be configured
  in it. The API and MongoDB stay private because they listen on 127.0.0.1 only, not because of firewall rules.
  No subnet is configured anywhere.
- **Any organization network works.** The VMS is meant for the organization's own trusted network, and it does
  not check which one: the Windows network profile (Public, Private or Domain), the network or Wi-Fi name and
  the IP addresses are not start requirements. Node listens on `0.0.0.0:6543` on purpose (every interface);
  the API and MongoDB stay loopback-only whatever the network. Connect the server to the organization network,
  start production, and give the gate PCs the `http://<IP>:6543` address it prints. A new network needs no
  configuration change.

Start with `deploy\windows\start-production.bat`, stop with `stop-production.bat`, restart with
`restart-production.bat`, check with `check-health.ps1` (it reads `http://127.0.0.1:6543/api/v1/health/ready`
through the web server). Step by step: `deploy\PRODUCTION-COMMANDS.md`.

In this mode the database has no login: production allows that only with `CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true`
and only for a database on 127.0.0.1 (set by `production.ps1`). MongoDB listens on 127.0.0.1 only, so gate PCs
cannot reach it, but any program or user on this PC can.

## Production operations

This part is for the administrator who runs the system on the server PC with `start-production.bat` (see
"Production on one Windows 11 PC" above and `deploy\PRODUCTION-COMMANDS.md`). It assumes no knowledge of the
code. Everything named `*.ps1` or `*.bat` is in `deploy\windows\`. This is the only supported production
deployment: there are no Windows services, no Caddy, no HTTPS certificates and no firewall scripts. Backup and
restore are not part of this VMS.

- Gate PCs need **only a browser** (Edge or Chrome) and the `http://<server IP>:6543` address. They never get
  Python, Node.js, MongoDB, source code, `.env` or passwords.
- The **legacy desktop MongoDB service (port 27017, database `century_gate_system`) is not used, changed or
  stopped**. The web application runs its own MongoDB instance on port 27018. The scripts never use port 27017,
  and the API refuses the legacy database name.

### Configuration reference

Gate cameras: `CG_SECRETS_KEY` (see "Gate cameras" above) is a secret like `CG_MONGO_URI`; keep a copy of it
with the other secrets.

`backend\.env` holds the secrets the application uses at runtime. The API **refuses to start in production** if:
- `CG_MONGO_URI` has no user/password, no `tls=true`, or any of `tlsAllowInvalidCertificates`,
  `tlsAllowInvalidHostnames`, `tlsInsecure`; the only exception is `CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true`
  (set by `production.ps1`) for a database on 127.0.0.1;
- `CG_PHOTO_DIR` is not set, does not exist, is not a folder or is not writable;
- `CG_COOKIE_SECURE` is false; or `CG_MONGO_DB` is the legacy database name;
- `CG_DEPLOYMENT_MODE` is anything but `https` (default) or `http-lan`. `http-lan` is an intentional,
  production-only mode for plain HTTP on a trusted private LAN: the session cookie becomes `cg_session` and
  both cookies lose only `Secure` (HttpOnly, SameSite=Strict, CSRF and sessions are unchanged). HTTP gives no
  transport confidentiality. Development and test refuse `http-lan`. `production.ps1` sets it for the API.
It prints only the reason, never the value. E-mail to hosts: see *Host arrival notifications*. Other settings: `CG_ORGANIZATION_NAME` (badges), `CG_SESSION_IDLE_MINUTES`
(15), `CG_SESSION_MAX_HOURS` (12), `CG_PASS_DAY_END_HOUR`/`MINUTE` (16:30), `CG_LOG_LEVEL` (INFO), `CG_TIMEZONE`
(Asia/Karachi), `CG_TRUSTED_PROXIES` (the local web server). There is no separate "public origin" or CSRF
setting: session cookies are host-only and SameSite=Strict, and every change needs the CSRF token.

The web server has no secrets; no `NEXT_PUBLIC_*` variables exist.

Health in a browser: `http://<server IP>:6543/api/v1/health/ready` answers `{"status":"ready", ...}` with the
state of the database, schema, transactions and photo storage. It never shows host names, paths or errors. The
dashboard's *System status* card shows the same.

### Photos

- `CG_PHOTO_DIR` (default `.dev\photos` in this project): a private folder, preferably on a data drive. Neither
  the web server nor Next.js serves it. The only way to see a photo is `GET /api/v1/photos/{id}`, which checks
  the login and role every time (Phase 4 rules). File names are random; no path or file name ever reaches a
  browser.
- The API refuses to start if the folder is missing or not writable. It never re-creates a vanished folder: if
  the drive disappears while running, photo uploads fail with a clear message ("continue without a photo"),
  and the health check reports `photo_storage: unavailable`.

### Monitoring

`check-health.ps1` runs at the end of every `start-production.bat` and can be run at any time (or from a Task
Scheduler task). It checks MongoDB, the API, the database (schema, transactions, photo folder), the web server,
the way gate PCs reach the API (`http://127.0.0.1:6543/api/v1/health/ready` through the web server), free space
on every drive holding application data (below 15 % or 10 GB).
The result is written to `.prod\status\health.json`. If an administrator registered the event source once
(`New-EventLog -LogName Application -Source CenturyGateVMS`), problems also go to the **Windows Application
event log**:

| Event ID | Meaning |
| --- | --- |
| 1001 / 1000 | health problem found / healthy again (only on a change, and once a day while it lasts) |

**Logs** (no passwords, tokens, QR codes, ID numbers or query strings are written; request IDs stay intact for
correlation):

| Log | Where |
| --- | --- |
| API (JSON lines, one per request) | the **CGVMS API** window (live; not saved to a file) |
| Web | the **CGVMS Web** window (live; not saved to a file) |
| MongoDB | `.dev\mongo\mongod.log` |
| Health | `.prod\status\*.log`, `.prod\status\*.json` |

### Recovery runbook

| Symptom | What to do |
| --- | --- |
| Gate PCs show "cannot reach the server" | Run `check-health.ps1` on the server. If something is stopped, `restart-production.bat`. Check the gate PC uses `http://<server IP>:6543` (not `https://`; see the HSTS note above). |
| `start-production.bat` refuses to start | It names the reason: a port in use (close the development windows), or a missing part. |
| **API stopped** | Read the **CGVMS API** window (it stays open when the API stops): a configuration problem prints `ERROR: configuration is not valid: <reason>` (no secrets). Fix `backend\.env`, `restart-production.bat`. |
| **Web stopped** | Read the **CGVMS Web** window. Usually a missing build: `restart-production.bat rebuild`. If the window was closed, `start-production.bat` starts it again. |
| **MongoDB stopped** | `.dev\mongo\mongod.log` (look for `"s":"F"` / `"s":"E"`). Common: disk full, a newer MongoDB version. `restart-production.bat`. |
| **Disk full** | Photos and the database grow. Free space or extend the drive. MongoDB stops writing when the disk is full: check it afterwards. |
| **Photo folder unavailable** | Health shows `photo_storage: unavailable`; gates can still check visitors in without photos. Reconnect the drive (same path), `restart-production.bat`. Never create an empty folder in its place. |

### Hardware acceptance tests (real devices, not yet done)

Do these on **each gate PC**, at `http://<server IP>:6543`, with the real badge printer and scanner. Nothing
here has been tested on real hardware yet.

**Webcam** (browsers allow it only on HTTPS or on the server itself, so on a gate PC over plain HTTP the
webcam fallback and webcam QR scanning are not available; the gate cameras work). On the server PC at
`http://localhost:6543`, check in a visitor and at the photo step:
- first use: the browser asks for camera permission; allow it (and check the permission is remembered);
- the photo is sharp and the face recognisable in the gate's lighting;
- deny the permission once: the page explains how to allow it;
- with the camera open in another program (e.g. Teams): "being used by another program";
- with the webcam unplugged: "No camera was found";
- unplug it while the preview runs: the preview stops (the page does not detect this by itself; known
  limitation). "Back" and "Review" again restart the camera step; record what the guard sees;
- the webcam light goes off after "Take photo", and also when leaving the step without a photo.

**Badge printer**:
- in the print dialog: the badge printer, paper 54 × 86 mm (or the configured card), margins *None*, scale
  100 %, *Headers and footers* off; save these settings once per gate PC;
- only the badge is printed (no menu, no other page), nothing is cut off, one card per badge;
- text readable; the QR code scans from the printed card (USB scanner).

**QR scanning**:
- USB scanner into the check-out box: it opens the confirmation with the photo;
- printed, laminated, and worn/creased badges;
- scan the same badge after check-out: "already checked out", nothing changes;
- *Badge* (reprint) on a visitor inside, then scan the OLD badge: "replaced"; the new badge works;
- a badge past gate closing (`CG_PASS_DAY_END_HOUR`/`MINUTE`, default 16:30): "expired", check-out by visit number still works;
  the host and department are e-mailed about the overstay.

A failing hardware test is a reason to adjust the device or its settings (print dialog, focus, lighting), not
the pass security.

### Pending decisions (not implemented on purpose)

- **Photo policy**: a photo is still optional ("Continue without a photo"). Whether every visitor must have one
  is decided after the hardware tests.
- **Retention**: how long ID numbers, photos and visit records are kept, and automatic clean-up, are decided
  later; nothing is deleted automatically yet.
- **Old desktop history**: not imported; the legacy database stays untouched.

## Status

Phase 4 (watchlist management, photos, QR passes, badges, scan-to-check-out), production on one Windows PC
(plain HTTP on the trusted LAN, `start-production.bat`, health check; the former HTTPS/Windows-services
setup was removed) and Phase 6A (host arrival notifications: in-app and e-mail) are complete. Next: real deployment and hardware
testing (see *Hardware acceptance tests*), and a test of the e-mails with the company mail server.
