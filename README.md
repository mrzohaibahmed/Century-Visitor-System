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
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000
```

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
```

## Configuration

All API settings are environment variables with the `CG_` prefix (see `api/.env.example`).
Secrets live only in the server environment, never in the frontend or the repository.

## Status

Phase 1 (foundation) of the implementation roadmap. Login and roles arrive in Phase 2; until then
every protected endpoint answers 401.
