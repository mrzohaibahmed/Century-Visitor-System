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

## Status

Phase 2 (authentication & RBAC) of the implementation roadmap is complete. Next: Phase 3, visitors and visits.
