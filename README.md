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

The automated tests use Edge's fake webcam and check the print layout as a PDF. On each real gate PC, over
**HTTPS**, check the following. Browsers only allow the camera on HTTPS or on `localhost`, so plain `http://`
to the server gives no camera.

1. **Webcam:** check in a visitor, start the camera, allow it, take/retake/use a photo; the face is recognisable.
   Deny the permission once and check the message. Unplug the webcam and check "No camera was found". With the
   camera open in another program (e.g. Teams), check "being used by another program". After the photo step the
   webcam light goes off.
2. **Badge printer:** in the print dialog choose the badge printer, paper size 54 × 86 mm (or the configured
   stock), margins none, scale 100 %, "Headers and footers" off. Print; the card is filled, nothing is cut off,
   and the text is readable. Set these once per gate PC (the browser remembers them).
3. **QR scanning:** scan a printed badge (a) with the webcam via *Scan badge with camera* and (b) with the USB
   scanner into the check-out box; both show the confirmation with photo; confirm. Scan the same badge again:
   "already checked out". Reprint a badge and scan the old one: "replaced". Scan a crumpled or laminated badge.

## Status

Phase 4 (watchlist management, photos, QR passes, badges, scan-to-check-out) is complete. Next: see the roadmap.
