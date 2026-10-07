# 🏢 Century Gate VMS — Visitor Management System

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141.1-009688.svg)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16.3.6-black.svg)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.2.8-61dafb.svg)](https://react.dev/)
[![MongoDB](https://img.shields.io/badge/MongoDB-8.x-47A248.svg)](https://www.mongodb.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4.0-38B2AC.svg)](https://tailwindcss.com/)

**Century Gate VMS** is a high-security, web-based enterprise Visitor Management System built to replace legacy desktop installations. Powered by FastAPI, Next.js 16, and MongoDB, it delivers rapid visitor check-in/check-out workflows, CR80 badge printing with cryptographically secure QR passes, watchlist ban enforcement, Hikvision IP gate camera integration, real-time host notifications, and audit logging.

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
                                                          PyMongo Async
                                                                 v
                                          +---------------------------------------------+
                                          |          MongoDB Replica Set                |
                                          |     (century_gate_vms @ 127.0.0.1:27018)   |
                                          +---------------------------------------------+
```

### Architectural Highlights
- **Zero Direct Database Exposure**: Browsers communicate exclusively with the API layer over HTTP/REST. Database connection credentials remain isolated within backend services.
- **Strict Legacy Isolation**: Operates exclusively on its dedicated database (`century_gate_vms`). The application explicitly refuses to launch or migrate legacy database names (`century_gate_system`).
- **Transaction Safety**: Utilizes MongoDB replica set transactions to process visits, audit logs, and notification creations within atomic multi-document ACID transactions.

---

## 🔒 Key Security & System Principles

### 1. Pass Security & QR Token Architecture
- **256-Bit Cryptographic Token**: QR codes hold only `CGP1:` followed by 64 random hexadecimal digits (256 bits of entropy).
- **Hashed Database Storage**: The database stores only the SHA-256 hash of tokens. Database access leaks zero usable pass credentials.
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
| **Database** | MongoDB Community `8.x` | Document database using PyMongo async driver with Replica Set ACID transactions |
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
│   │   ├── db/               # MongoDB client, indices, migrations
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
├── scripts/                  # Development utility scripts (dev_mongo.py, etc.)
├── start-production.bat      # One-click Windows production startup batch script
├── stop-production.bat       # Production shutdown batch script
└── README.md                 # Project documentation
```

---

## 🚀 Local Development Setup

### Prerequisites
- **Python**: `3.12+`
- **Node.js**: `24+` & `npm`
- **MongoDB**: Community Server `8.x` binary installed (Windows MongoDB service does **not** need to be running).

---

### Step 1: Start Isolated Development Database

The development stack requires a local MongoDB replica set running on port `27018` with data stored in `.dev/mongo/` (isolated from any legacy database on port 27017).

```powershell
# Start local development MongoDB replica set on 127.0.0.1:27018
backend\.venv\Scripts\python scripts\dev_mongo.py start

# Check status
backend\.venv\Scripts\python scripts\dev_mongo.py status
```

---

### Step 2: Backend Setup & API Server

```powershell
cd backend

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt

# Copy environment configuration
copy .env.example .env

# Run database migrations (idempotent: creates collections, validators, indexes)
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
| `CG_MONGO_URI` | `mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev` | MongoDB connection URI string |
| `CG_MONGO_DB` | `century_gate_vms` | Database name (refuses legacy `century_gate_system`) |
| `CG_MONGO_LOCALHOST_WITHOUT_LOGIN` | `false` | Set to `true` by deployment scripts for 127.0.0.1 DBs without auth |
| `CG_PHOTO_DIR` | `.dev/photos` | Private filesystem directory for visitor photos |
| `CG_PHOTO_MAX_BYTES` | `2097152` (2 MB) | Maximum permitted photo file upload size |
| `CG_COOKIE_SECURE` | `true` | Requires HTTPS secure cookies (`false` automatically in `http-lan`) |
| `CG_SECRETS_KEY` | *(Secret)* | AES-256-GCM 32-byte key for hardware credential encryption |
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
                          |   └──> MongoDB           @ 127.0.0.1:27018|
                          +------------------------------------------+
```

### Production Lifecycle Commands

Production batch files are located in the project root folder:

| Batch / Script File | Purpose |
| :--- | :--- |
| `start-production.bat` | Initializes MongoDB, runs migrations, verifies admin, builds Next.js frontend, and launches services |
| `stop-production.bat` | Gracefully shuts down Node web server, FastAPI backend, and MongoDB service |
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

# 1. Run database schema migrations & indexes
.venv\Scripts\python -m app.cli migrate

# 2. Seed default admin account (admin / admin1234) if no accounts exist
.venv\Scripts\python -m app.cli first-admin

# 3. Create a custom administrator account interactively
.venv\Scripts\python -m app.cli create-admin --username john_admin

# 4. Generate a cryptographically secure 32-byte AES key for camera password encryption
.venv\Scripts\python -m app.cli generate-secrets-key

# 5. Backfill historical entry denial records from audit log WATCHLIST_MATCH entries
.venv\Scripts\python -m app.cli backfill-entry-denials
```

---

## 🩺 Monitoring, Health & Recovery

### 1. Automated Health Diagnostics
Run `deploy\windows\check-health.ps1` to inspect system integrity. It evaluates:
- MongoDB connectivity and replica set state.
- FastAPI backend readiness (`/api/v1/health/ready`).
- Database schema version compliance.
- Photo directory availability and disk space (alerts if <15% or <10GB free).
- Windows Event Log logging (`CenturyGateVMS` event source, Event IDs `1000`/`1001`).

### 2. Recovery Runbook

| Symptom | Cause | Solution |
| :--- | :--- | :--- |
| **Gate PCs cannot reach server** | Network issue or Web service offline | Run `check-health.ps1`. If services are down, execute `stop-production.bat` then `start-production.bat`. Verify gate PCs use `http://<SERVER_IP>:6543`. |
| **API fails to start** | Environment variable configuration invalid | Inspect **CGVMS API** terminal window for exact validation error. Update `backend\.env` and run `start-production.bat`. |
| **Photo upload failure** | `CG_PHOTO_DIR` folder unavailable or disk full | Verify path in `CG_PHOTO_DIR`. Check disk space on server. Restart services once path is mounted. |
| **MongoDB process stopped** | Disk space exhausted or lock conflict | Inspect `.dev\mongo\mongod.log` for severe errors (`"s":"F"`). Free disk space and execute `start-production.bat`. |

---

## 🧪 Testing & Quality Assurance

The project enforces quality assurance across both backend and frontend codebases.

### Backend Testing & Code Quality
```powershell
cd backend

# Run pytest suite (requires development database running on port 27018)
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

