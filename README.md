# 🏢 Century Gate VMS — Visitor Management System

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.3.6-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.2.8-61dafb.svg)](https://react.dev/)
[![SQL Server](https://img.shields.io/badge/SQL_Server-2022_Express-CC2927.svg)](https://www.microsoft.com/sql-server)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4.0-38B2AC.svg)](https://tailwindcss.com/)

**Century Gate VMS** is a high-security, web-based enterprise Visitor Management System built to replace legacy desktop installations. Powered by FastAPI, Next.js 16, and Microsoft SQL Server, it delivers rapid visitor check-in/check-out workflows, CR80 badge printing with cryptographically secure QR passes, watchlist ban enforcement, Hikvision IP gate camera integration, real-time host notifications, and audit logging.

---

## 📋 Table of Contents

- [System Architecture](#-system-architecture)
- [Key Security & System Principles](#-key-security--system-principles)
- [Core Feature Modules](#-core-feature-modules)
- [Technology Stack](#-technology-stack)
- [Repository Layout](#-repository-layout)
- [Local Development Setup](#-local-development-setup)
- [Configuration Reference](#-configuration-reference)
- [Production Deployment (Windows)](#-production-deployment-windows)
- [CLI Tool Reference](#-cli-tool-reference)
- [Monitoring, Health & Recovery](#-monitoring-health--recovery)
- [Testing & Quality Assurance](#-testing--quality-assurance)

---

## 🏗️ System Architecture

```
                                          +---------------------------------------------+
                                          |             Organization LAN                |
                                          +---------------------------------------------+
                                                                 |
                                                                 v
+------------------------+      HTTP      +---------------------------------------------+
|    Gate PC Browsers    | -------------> |     Next.js Web Server (server.mjs)         |
| (Edge / Chrome @ 6543) |                |               [0.0.0.0:6543]                |
+------------------------+                +---------------------------------------------+
                                                                 |
                                                            /api/* proxy
                                                                 v
+------------------------+      HTTP      +---------------------------------------------+
| Hikvision Gate Cameras | <------------- |           FastAPI Backend API               |
| (ISAPI Snapshot Engine)|                |              [127.0.0.1:8000]               |
+------------------------+                +---------------------------------------------+
                                                                 |
                                              SQLAlchemy Core + ODBC Driver 18 (encrypted)
                                                                 v
                                          +---------------------------------------------+
                                          |       Microsoft SQL Server (.\SQLEXPRESS)   |
                                          |         database century_gate_vms           |
                                          +---------------------------------------------+
```

### Architectural Highlights
- **Zero Direct Database Exposure**: Browsers communicate exclusively with the API layer over HTTP/REST. Database connection credentials remain isolated within backend services.
- **Strict Legacy Isolation**: Operates exclusively on its dedicated database (`century_gate_vms`). The application explicitly refuses to launch or migrate legacy database names (`century_gate_system`).
- **Transaction Safety**: Visits, audit logs and notifications are written in one SQL Server transaction (read-committed snapshot isolation; a deadlock victim is retried). Filtered unique indexes enforce the business rules (one active visit per visitor, one active ban per identifier), and foreign keys connect the records.

---

## 🔒 Key Security & System Principles

### 1. Pass Security & QR Token Architecture
- **256-Bit Cryptographic Token**: QR codes hold only `CGP1:` followed by 64 random hexadecimal digits (256 bits of entropy).
- **Protected Database Storage**: The database stores a SHA-256 hash for token lookup. When `CG_SECRETS_KEY` is configured, it also stores an AES-256-GCM encrypted copy so the same QR can be printed on the visitor's belongings slip. A database copy without the server key has no usable pass token.
- **Token Invalidation Lifecycle**: Passes automatically invalidate upon check-out, badge reprint (`pass_replaced`), manual admin revocation (`pass_revoked`), or daily gate closing time (`CG_PASS_DAY_END_HOUR/MINUTE`, default 16:30 local).

### 2. Visitor Photo Storage Security
- **Re-Encoding & Sanitization Pipeline**: Photos uploaded via webcam or gate cameras are validated (JPEG/PNG/WebP, 160×120 to 4096×4096, max 12M pixels, max 2MB), stripped of all EXIF/GPS metadata, and re-encoded as standardized JPEGs (max 1024px).
- **Isolated Private Directory**: Stored in a private server folder (`CG_PHOTO_DIR`) with random 128-bit UUID filenames. Photos are never served directly as static files.
- **Session & Role Gated Access**: Reachable only via `GET /api/v1/photos/{id}`. Guards can only access photos for visitors currently on-site; administrators have full audit access.

### 3. Role-Based Access Control (RBAC) & Authentication
- **Roles**: `Administrator` (System configuration, user accounts, watchlist, audit logs, settings, reports) and `Guard` (Gate operations, check-in, check-out, lookups).
- **Password Policies**: Argon2id hashing, minimum 8 characters, non-username matching. Initial admin and reset accounts require password changes on first login.
- **Session Hardening**: HttpOnly `__Host-` cookies, per-request CSRF tokens, 15-minute idle / 12-hour maximum limits (`CG_SESSION_IDLE_MINUTES`, `CG_SESSION_MAX_HOURS`).
- **Brute-Force Lockout**: 5 consecutive wrong password attempts lock the account for 15 minutes. IP-based rate limiting prevents endpoint abuse.

---

## 🎯 Core Feature Modules

### 🎫 1. Visitor Check-In & Check-Out Workflow
- **Fast ID Lookup**: Check-in searches existing visitors by CNIC/ID number or phone number.
- **Watchlist & On-Site Checks**: Automated real-time checks ensure watchlist-banned individuals cannot enter and visitors cannot double check-in while inside.
- **Sequential Visit Numbers**: Generates daily gap-free visit numbers (`V-YY-MON-DD-NNN`, e.g., `V-26-OCT-02-001`).
- **Flexible Check-Out Options**: Check-out by scanning CR80 badge QR code (via webcam or USB scanner), typing the visit number/ID, or picking from active on-site visitors.

### 📇 2. CR80 Visitor Pass & Badge Printing
- **Standard Card Dimensions**: Formatted for standard portrait CR80 cards (**54 × 85.6 mm**).
- **Clean Print Layout**: Displays organization name, site address, visitor name, visit number, host, department, entry time, gate, and QR token. Sensitive ID/CNIC numbers and phone numbers are excluded from printed badges.
- **Instant Badge Reprint**: Supports secure badge reprinting which automatically revokes previous QR tokens.
- **Matching Belongings Slip**: Once the badge is issued, the Personal Material Returnable form prints the same visit number and QR. Older badges can be scanned into the form; printing the slip does not reissue the badge.

### ⛔ 3. Watchlist & Entry Denial Tracking
- **Normalized Matching**: ID numbers are normalized server-side to guarantee matches regardless of dash formatting during gate lookup.
- **Audit-Driven Refusal Logs**: Watchlist hits create immutable entries in `entry_denials` and `audit_logs` (`WATCHLIST_MATCH`).
- **CLI Backfill Utility**: CLI includes idempotent `backfill-entry-denials` to parse historical audit logs and reconstruct refusal records.

### 🔔 4. Host Arrival Notifications (Phase 6A)
- **In-App Bell Alerts**: Linked employee accounts receive real-time bell alerts upon visitor arrival.
- **SMTP Email Notifications**: Automated background email dispatcher with exponential retries (1, 5, 15, 60 minutes) and strict deduplication locks (`HOST_VISITOR_ARRIVAL:<visit_id>`).
- **Departmental Email Distribution**: Department-wide notification emails alert department teams of incoming visits.

### 🎥 5. Gate Camera Integration (Hikvision)
- **Direct Server Snapshotting**: Server directly communicates with IP cameras via ISAPI over HTTP/HTTPS with Digest Authentication. Gate PCs never interface directly with camera network IPs.
- **Encrypted Password Storage**: Camera credentials stored in database encrypted via AES-256-GCM using `CG_SECRETS_KEY`.
- **Diagnostic Testing Endpoints**: Dedicated admin endpoints allow connectivity testing and live snapshot validation.

### 📊 6. Auditing & Report Exports
- **Immutable Audit Trail**: Append-only `audit_logs` record login attempts, password updates, visitor lookups, watchlist alterations, pass scans, and photo views.
- **Multi-Format Export Engine**: Exports detailed visit and audit histories to **Excel (.xlsx)** via XlsxWriter and **PDF (.pdf)** via ReportLab (with `uharfbuzz` font shaping for Urdu/Arabic RTL compatibility).

---

## 🛠️ Technology Stack

| Domain | Technology | Description |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI `0.141.1` | High-performance Python 3.12 async web framework |
| **Database** | Microsoft SQL Server `2022` (Express) | SQLAlchemy Core (no ORM) over aioodbc / pyodbc and ODBC Driver 18; Alembic migrations |
| **Auth & Security** | Argon2id & Cryptography | `argon2-cffi` for password hashing; AES-256-GCM for hardware credential encryption |
| **PDF & Excel** | ReportLab & XlsxWriter | Direct canvas rendering with `uharfbuzz` for Urdu/Arabic RTL text shaping |
| **Frontend Framework**| Next.js `16.3.6` | React 19 App Router with TypeScript |
| **UI Components** | Tailwind CSS 4 & Lucide Icons | Responsive styling and modern UI icons |
| **QR Code Engine** | `qrcode` & `jsQR` | Server-side QR generation and browser-side video QR scanner |
| **Testing** | Pytest, Vitest, Playwright | Backend async unit tests, React unit tests, and Playwright Edge E2E tests |

---

## 📁 Repository Layout

```
century-gate-vms/
├── backend/                  # FastAPI backend application
│   ├── app/                  # Application source code
│   │   ├── api/v1/           # REST API routes (auth, visitors, visits, watchlist, etc.)
│   │   ├── core/             # Configuration, security, cryptography, logging
│   │   ├── db/               # SQL Server connection, transactions, migrations (db/sql)
│   │   ├── repositories/     # Data access layer
│   │   ├── schemas/          # Pydantic v2 request/response schemas
│   │   ├── services/         # Business logic (check-in, passes, photos, emails)
│   │   ├── cli.py            # Command Line Interface (migrations, admin setup)
│   │   └── main.py           # FastAPI application factory
│   ├── tests/                # Backend test suite (Pytest)
│   ├── pyproject.toml        # Ruff & Pytest configuration
│   └── requirements.txt      # Pinned runtime Python dependencies
├── frontend/                 # Next.js frontend application
│   ├── src/                  # Next.js App Router source code
│   │   ├── app/              # App Router pages ((admin), check-in, check-out, etc.)
│   │   ├── components/       # Reusable React components & badge layouts
│   │   ├── hooks/            # Custom React hooks (camera, scanner, notifications)
│   │   └── lib/              # API client & utility functions
│   ├── e2e/                  # Playwright end-to-end test suite
│   └── package.json          # Frontend dependencies & scripts
├── deploy/                   # Windows single-PC deployment scripts & runbooks
│   ├── windows/              # PowerShell management & health diagnostic scripts
│   └── PRODUCTION-COMMANDS.md# Step-by-step production runbook
├── scripts/                  # Development utility scripts (e2e_reset_db.py)
├── start-production.bat      # One-click Windows production startup batch script
├── stop-production.bat       # Production shutdown batch script
└── README.md                 # Project documentation
```

---

## 🚀 Local Development Setup

### Prerequisites
- **Python**: `3.12+`
- **Node.js**: `24+` & `npm`
- **SQL Server**: SQL Server 2022 Express (or any edition) on this PC, instance `.\SQLEXPRESS` by default, with the Windows service **"SQL Server (SQLEXPRESS)"** running.
- **ODBC Driver 18 for SQL Server** (Microsoft download; the Python packages use it).

---

### Step 1: The Development Database

The API uses its own database, `century_gate_vms`, on the SQL Server instance named in `CG_MSSQL_SERVER` (default `.\SQLEXPRESS`). Other databases on that instance are never touched, and the legacy desktop database `century_gate_system` is refused by name. By default the API signs in with **Windows authentication** (the account that runs it); `CG_MSSQL_USERNAME` / `CG_MSSQL_PASSWORD` select a SQL login instead. The connection is always encrypted; `CG_MSSQL_TRUST_SERVER_CERTIFICATE=true` (in `.env.example`) accepts the self-signed certificate of an instance **on this PC** and is refused for a server on the network.

The database is created and migrated in Step 2 (`create-database`, `migrate`). Machine-local operational data (photos, process state, logs) lives under `.cgvms/`.

---

### Step 2: Backend Setup & API Server

```powershell
cd backend

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt

# Copy environment configuration
copy .env.example .env

# Create the database if it is missing, then bring its tables to the current revision (both idempotent)
.venv\Scripts\python -m app.cli create-database
.venv\Scripts\python -m app.cli migrate

# Option A: Create default first administrator (admin / admin1234)
.venv\Scripts\python -m app.cli first-admin

# Option B: Create administrator with custom password
.venv\Scripts\python -m app.cli create-admin --username admin

# Start FastAPI development server with hot-reload (Port 8000)
.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000
```

- **Live Health Endpoint**: `http://127.0.0.1:8000/api/v1/health/live`
- **Interactive Swagger OpenAPI Docs**: `http://127.0.0.1:8000/api/docs`

---

### Step 3: Frontend Web Application Setup

```powershell
cd frontend

# Install Node dependencies
npm install

# Copy environment configuration
copy .env.example .env.local

# Start Next.js development server (Port 6543)
npm run dev
```

> **Note**: Open the frontend in your browser via **`http://localhost:6543`** (Next.js dev server restricts script loading strictly to `localhost`).

---

## ⚙️ Configuration Reference

All backend API settings are managed via environment variables prefixed with `CG_` (defined in `backend/.env`).

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `CG_ENVIRONMENT` | `development` | Environment mode (`development`, `test`, `production`) |
| `CG_DEPLOYMENT_MODE` | `https` | Deployment mode (`https` or `http-lan` for private trusted LANs) |
| `CG_MSSQL_SERVER` | `.\SQLEXPRESS` | SQL Server instance (`host\instance` or `host,port`) |
| `CG_MSSQL_DATABASE` | `century_gate_vms` | Database name (letters, digits, `_`; refuses legacy `century_gate_system`) |
| `CG_MSSQL_USERNAME` / `CG_MSSQL_PASSWORD` | *(empty)* | Empty: Windows authentication. Both set: a SQL login |
| `CG_MSSQL_TRUST_SERVER_CERTIFICATE` | `false` | `true` accepts a self-signed certificate; only allowed for an instance on this PC |
| `CG_MSSQL_DRIVER` | `ODBC Driver 18 for SQL Server` | ODBC driver name |
| `CG_MSSQL_TIMEOUT_SECONDS` | `5` | Connection timeout |
| `CG_PHOTO_DIR` | `.cgvms/data/photos` | Private filesystem directory for visitor photos |
| `CG_PHOTO_MAX_BYTES` | `2097152` (2 MB) | Maximum permitted photo file upload size |
| `CG_COOKIE_SECURE` | `true` | Requires HTTPS secure cookies (`false` automatically in `http-lan`) |
| `CG_SECRETS_KEY` | *(Secret)* | AES-256-GCM 32-byte key for camera credentials and retrieval of the current badge QR for belongings slips. Keep and back up the key; changing it makes stored encrypted values unreadable. |
| `CG_ORGANIZATION_NAME` | `"Century Gate"` | Organization header printed on visitor CR80 badges |
| `CG_SESSION_IDLE_MINUTES` | `15` | Session inactivity timeout limit |
| `CG_SESSION_MAX_HOURS` | `12` | Absolute maximum session duration |
| `CG_PASS_DAY_END_HOUR` | `16` | Hour (24h) when daily visitor passes expire |
| `CG_PASS_DAY_END_MINUTE` | `30` | Minute when daily visitor passes expire |
| `CG_SMTP_HOST` | `""` | Outgoing SMTP server hostname |
| `CG_SMTP_PORT` | `587` | Outgoing SMTP server port |
| `CG_SMTP_SECURITY` | `starttls` | Security mode (`starttls`, `ssl`, `none`) |
| `CG_SMTP_USERNAME` | `""` | SMTP authentication username |
| `CG_SMTP_PASSWORD` | `""` | SMTP authentication password |
| `CG_SMTP_FROM` | `""` | Sender email address for notifications |
| `CG_TIMEZONE` | `Asia/Karachi` | Server timezone identifier |

---

## 💻 Production Deployment (Windows)

The system supports single-machine production deployment on Windows 11 PC for enterprise trusted LAN networks using automated PowerShell lifecycle scripts.

```
                          +------------------------------------------+
                          |   Production Server PC (Windows 11)     |
                          |                                          |
Gate PC Browsers -------> | Node Server (server.mjs) @ 0.0.0.0:6543   |
 (HTTP LAN Access)        |   ├──> FastAPI (uvicorn) @ 127.0.0.1:8000|
                          |   └──> SQL Server        @ .\SQLEXPRESS   |
                          +------------------------------------------+
```

### Production Lifecycle Commands

Production batch files are located in the project root folder:

| Batch / Script File | Purpose |
| :--- | :--- |
| `start-production.bat` | Checks SQL Server and creates the database if missing, runs migrations, verifies admin, builds Next.js frontend, and launches services |
| `stop-production.bat` | Gracefully shuts down the Node web server and the FastAPI backend (SQL Server keeps running: it is a Windows service shared with other databases) |
| `deploy\windows\check-health.ps1` | Comprehensive health check diagnostic script |

To start production:
```cmd
start-production.bat
```

Gate PCs on the network can immediately connect via: `http://<SERVER_IP>:6543`.

---

## 🖥️ CLI Tool Reference

The backend CLI utility (`backend/app/cli.py`) manages database migrations, administrative accounts, security keys, and maintenance tasks.

```powershell
cd backend

# 1. Create the database if it is missing, migrate its tables, check readiness
.venv\Scripts\python -m app.cli create-database
.venv\Scripts\python -m app.cli migrate
.venv\Scripts\python -m app.cli check

# 2. Seed default admin account (admin / admin1234) if no accounts exist
.venv\Scripts\python -m app.cli first-admin

# 3. Create a custom administrator account interactively
.venv\Scripts\python -m app.cli create-admin --username john_admin

# 4. Generate a cryptographically secure 32-byte AES key for camera password encryption
.venv\Scripts\python -m app.cli generate-secrets-key

# 5. Backfill historical entry denial records from audit log WATCHLIST_MATCH entries
.venv\Scripts\python -m app.cli backfill-entry-denials

# 6. Back up the database (a verified full .bak file; see Backups below)
.venv\Scripts\python -m app.cli backup --to D:\CenturyGateVMS\backups
```

`create-database` and `migrate` need a login that may create the database and change tables. The application itself only needs to read and write data, so a separate, smaller login can be used for the API.

### Backups

A complete backup is **the database plus the photo folder**: photos are files in `CG_PHOTO_DIR`, and the database holds only their names. Keep `CG_SECRETS_KEY` safe too, because the encrypted camera passwords and badge data cannot be read without it.

1. `python -m app.cli backup [--to <folder>]` writes `<folder>\century_gate_vms-<date>-<time>.bak`: a full **COPY_ONLY** backup with page checksums, read back once with `RESTORE VERIFYONLY`. COPY_ONLY means it never disturbs another backup plan on the instance. **The SQL Server service writes the file**, so the folder must exist on the database server and its service account (`NT SERVICE\MSSQL$SQLEXPRESS`) must be allowed to write there. Without `--to`, the file goes to the instance's own backup folder.
2. Copy the photo folder (`CG_PHOTO_DIR`) at the same time.
3. Keep copies off this PC (another disk or a network share), and test a restore now and then (SQL Server Management Studio: *Restore Database* from the `.bak` file).

SQL Server Express has no SQL Agent, so schedule the backup with **Windows Task Scheduler**, for example daily: `backend\.venv\Scripts\python.exe -m app.cli backup --to D:\CenturyGateVMS\backups`, started in `backend\`.

---

## 🩺 Monitoring, Health & Recovery

### 1. Automated Health Diagnostics
Run `deploy\windows\check-health.ps1` to inspect system integrity. It evaluates:
- FastAPI backend readiness (`/api/v1/health/ready`).
- SQL Server connectivity and the database's schema revision (through the API).
- Photo directory availability and disk space (alerts if <15% or <10GB free).
- Windows Event Log logging (`CenturyGateVMS` event source, Event IDs `1000`/`1001`).

### 2. Recovery Runbook

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| **Gate PCs cannot reach server** | Network issue or Web service offline | Run `check-health.ps1`. If services are down, execute `stop-production.bat` then `start-production.bat`. Verify gate PCs use `http://<SERVER_IP>:6543`. |
| **API fails to start** | Environment variable configuration invalid | Inspect **CGVMS API** terminal window for exact validation error. Update `backend\.env` and run `start-production.bat`. |
| **Photo upload failure** | `CG_PHOTO_DIR` folder unavailable or disk full | Verify path in `CG_PHOTO_DIR`. Check disk space on server. Restart services once path is mounted. |
| **SQL Server not reachable** | The "SQL Server (SQLEXPRESS)" service stopped, or the disk is full | `start-production.bat` stops at step 1 with this message. Start the service in `services.msc` (Windows Event Viewer / the SQL Server error log shows why it stopped), free disk space, then run `start-production.bat`. |

---

## 🧪 Testing & Quality Assurance

The project enforces quality assurance across both backend and frontend codebases.

### Backend Testing & Code Quality
```powershell
cd backend

# Run pytest suite (needs SQL Server on this PC, .\SQLEXPRESS or CG_TEST_MSSQL_SERVER, with the Windows
# login; the run creates a throw-away cgvms_test_* database and drops it at the end)
.venv\Scripts\python -m pytest

# Run Ruff linter & static code analysis
.venv\Scripts\ruff check app tests ..\scripts
```

### Frontend Testing & Linting
```powershell
cd frontend

# Run TypeScript type check
npm run typecheck

# Run ESLint check
npm run lint

# Run Vitest unit & component tests
npm run test

# Build production bundle
npm run build

# Run Playwright End-to-End browser tests (in Microsoft Edge)
npm run test:e2e
```
