# Century Gate VMS — Installation Guide

## Overview

This guide sets up Century Gate VMS on a new Windows 11 PC so that gate PCs on the office network can open it at `http://<this PC's IP>:6543`. Plan on about 60–90 minutes, most of it waiting for downloads and installers.

When you finish, three parts run on this PC:

| Part | What it does | Address |
| --- | --- | --- |
| Web app (Node.js) | The screens guards and admins use in the browser | `0.0.0.0:6543` (reachable from the network) |
| API (Python) | The business logic; only the web app talks to it | `127.0.0.1:8000` (this PC only) |
| SQL Server Express | Stores visitors, visits, users and audit logs in the database `century_gate_vms` | `.\SQLEXPRESS` (this PC only) |

You install the software once (Steps 1–4). After that, a single double-click on `start-production.bat` creates the database, builds the app and starts everything (Step 5).

**Typing commands:** wherever this guide shows a command, open **Windows PowerShell** (Start menu → type *PowerShell* → Enter), paste the command, and press Enter. Run them one at a time and wait for each to finish.

## Before you start

You need a Windows 11 (or 10) 64-bit PC with at least 8 GB RAM, 20 GB of free disk space, an administrator account, and internet access during setup. Sign in with the Windows account that will run the system day to day: SQL Server will trust that account automatically.

Install these three programs first, in this order. Accept the default options unless the table says otherwise.

| Program | Version | Download | Important during install |
| --- | --- | --- | --- |
| Git | latest | [git-scm.com/download/win](https://git-scm.com/download/win) | Defaults are fine. Only needed if you download the code from GitHub. |
| Python | 3.12 (64-bit) | [python.org/downloads/windows](https://www.python.org/downloads/windows/) | On the first screen tick **Add python.exe to PATH**, then click **Install Now**. Use 3.12; it is the version the project is built and tested on. |
| Node.js | 24 LTS | [nodejs.org](https://nodejs.org/) | Keep the default folder `C:\Program Files\nodejs` (the start script looks there). Leave "Tools for native modules" unticked. |

When all three are installed, **close and reopen PowerShell**, then check them:

```powershell
git --version
py -3.12 --version
node --version
npm --version
```

Each line should print a version number (for example `Python 3.12.x`, `v24.x.x`). If one says *not recognized*, reinstall that program and make sure the PATH option was ticked. If `npm` says *running scripts is disabled*, see the fix at the end of Step 3.

## Step 1 — Get the project onto the PC

Put the project in a short folder such as `C:\CenturyGateVMS\century-gate-vms`. This guide uses that path; if you choose another, use yours in every command.

**Option A — download from GitHub (recommended):**

```powershell
mkdir C:\CenturyGateVMS
cd C:\CenturyGateVMS
git clone https://github.com/mrzohaibahmed/Century-Visitor-System.git century-gate-vms
```

If the repository is private, Git opens a browser window to sign in with a GitHub account that has access.

**Option B — copy from another PC (USB drive or network share):** copy the whole `century-gate-vms` folder, but leave out these folders. They are specific to the old PC and are recreated in Step 3:

- `backend\.venv`
- `frontend\node_modules`
- `frontend\.next`
- `.cgvms` (photos and logs; copy it only if you are moving existing data — see [Moving data from an old PC](#moving-data-from-an-old-pc))

Check you are in the right place: `C:\CenturyGateVMS\century-gate-vms` should contain the folders `backend`, `frontend`, `deploy` and the file `start-production.bat`.

## Step 2 — Install SQL Server Express and its driver

The app keeps its data in Microsoft SQL Server. You only install it here; the app creates its own database `century_gate_vms` automatically in Step 5.

1. Download **SQL Server 2022 Express** from [microsoft.com/sql-server/sql-server-downloads](https://www.microsoft.com/en-us/sql-server/sql-server-downloads) and run it.
2. Choose **Basic**, accept the license, keep the install location, and click **Install**. Basic installs the instance with the name `SQLEXPRESS` and makes your Windows account its administrator, which is exactly what the app expects.
3. When it says *Installation has completed successfully*, click **Close** (you do not need "Connect Now" or "Customize").
4. Download **ODBC Driver 18 for SQL Server** (x64) from [Microsoft's ODBC driver page](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) and install it with the defaults. If it asks for the *Visual C++ Redistributable*, install that first from [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe), then run the driver installer again.
5. Optional: install **SQL Server Management Studio (SSMS)** from the same Microsoft download page if you want to look at the database or restore backups later.

Check that SQL Server is running:

```powershell
Get-Service 'MSSQL$SQLEXPRESS'
```

The **Status** column should say `Running`. If it says `Stopped`, open **Services** (Start → type *services.msc*), find **SQL Server (SQLEXPRESS)**, set *Startup type* to **Automatic**, and click **Start**.

## Step 3 — Install the app's components

The app needs its own Python and Node.js libraries. They download from the internet and take about 5–15 minutes in total.

**Backend (Python):**

```powershell
cd C:\CenturyGateVMS\century-gate-vms\backend
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

The last command ends with *Successfully installed …*. This creates the folder `backend\.venv`, a private copy of Python just for this app.

**Frontend (Node.js):**

```powershell
cd C:\CenturyGateVMS\century-gate-vms\frontend
npm ci
```

This creates the folder `frontend\node_modules`. Warnings in yellow are normal; only a red `npm ERR!` at the end means it failed.

If PowerShell says *running scripts is disabled on this system*, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer **Y**, and run `npm ci` again.

## Step 4 — Create the settings file

The app reads its settings from `backend\.env`. The project ships a ready-made example that works on a standard install, so you mostly copy it.

1. Copy the example:

    ```powershell
    cd C:\CenturyGateVMS\century-gate-vms\backend
    copy .env.example .env
    ```

2. Create a security key (used to encrypt camera passwords and badge QR data):

    ```powershell
    .venv\Scripts\python -m app.cli generate-secrets-key
    ```

    It prints one long line of random characters. Copy it.

3. Open the settings file in Notepad: `notepad .env`. Make these changes, then save (Ctrl+S) and close:

| Setting | What to put | Why |
| --- | --- | --- |
| `CG_SECRETS_KEY` | Remove the `#` at the start of the line and paste the key after `=` | Lets the app store camera passwords and reprint the badge QR on belongings slips |
| `CG_ORGANIZATION_NAME` | Remove the `#` and set your name, e.g. `Century Paper & Board Mills` | Printed at the top of every visitor badge |
| `CG_FIRST_ADMIN_PASSWORD` | Leave as `admin1234`, or choose another temporary password | The first login; it must be changed on first sign-in |
| `CG_SMTP_*` lines | Optional: remove the `#` and fill in your mail server | Emails hosts when their visitor arrives. Can also be set later in the app's admin settings. |

Leave `CG_MSSQL_SERVER=.\SQLEXPRESS` and `CG_MSSQL_TRUST_SERVER_CERTIFICATE=true` as they are: they match the SQL Server you installed in Step 2.

**Keep a copy of `CG_SECRETS_KEY` somewhere safe** (a password manager or a sealed note with IT). If the key is lost or changed, the stored camera passwords and badge QR data cannot be read again.

The frontend needs no settings file in production.

## Step 5 — Start the system and sign in

Open the project folder in File Explorer and **double-click `start-production.bat`**. A black window shows five stages:

1. **[1/5] SQL Server** — creates the database `century_gate_vms` the first time.
2. **[2/5] Database schema** — creates or updates the tables.
3. **[3/5] Web production build** — builds the web app. The first time this takes 3–10 minutes; later starts skip it.
4. **[4/5] API** — creates the first admin account (first time only) and opens a window named **CGVMS API**.
5. **[5/5] Web** — opens a window named **CGVMS Web**.

If **Windows Defender Firewall** asks whether to allow *Node.js*, tick **Private networks** and click **Allow**. Without this, gate PCs cannot connect.

At the end you see *Century Gate VMS is running in production mode* and the addresses to use, for example `Gate PCs: http://192.168.1.25:6543`. Write that address down. Press any key to close the start window; the system keeps running.

**First sign-in (do this right away, on this PC):**

1. Open Edge or Chrome and go to `http://localhost:6543`.
2. Sign in as **admin** with the password **admin1234** (or the one you set in `CG_FIRST_ADMIN_PASSWORD`).
3. The app asks for a new password: at least 8 characters, not the same as the username.
4. Create guard and admin accounts for your staff from the admin screens.

**Daily use:**

| To… | Do this |
| --- | --- |
| Start the system | Double-click `start-production.bat` |
| Stop the system | Double-click `stop-production.bat` (SQL Server keeps running) |
| Check that everything is healthy | `powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1` in the project folder |

Do not close the **CGVMS API** or **CGVMS Web** windows: closing either one stops that part of the system. Minimise them instead. The system also stops when you sign out or shut down; double-click `start-production.bat` again afterwards, or set it to start automatically (next section).

**For developers only:** to work on the code instead of running it for production, install `requirements-dev.txt` instead of `requirements.txt`, copy `frontend\.env.example` to `frontend\.env.local`, then run the API with `.venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000` (in `backend`) and the web app with `npm run dev` (in `frontend`). Open `http://localhost:6543`.

## Optional extras

### Connect the gate PCs

On each gate PC, open Edge or Chrome and go to the address `start-production.bat` printed, e.g. `http://192.168.1.25:6543`. Save it as a bookmark or desktop shortcut. Nothing needs to be installed on gate PCs.

- If the gate PC cannot connect but `http://localhost:6543` works on the server, the firewall is blocking it. Set the server's network to **Private** (Settings → Network & internet → your connection → *Private network*), or add a rule in PowerShell **run as administrator**:

    ```powershell
    New-NetFirewallRule -DisplayName "Century Gate VMS" -Direction Inbound -Protocol TCP -LocalPort 6543 -Action Allow -Profile Private,Domain
    ```

- Give the server a fixed IP address (ask your network admin to reserve it), so the gate PC bookmarks keep working.
- Gate cameras (Hikvision) work from every gate PC. The browser webcam and webcam QR scanning work only on the server itself (`http://localhost:6543`), because browsers allow cameras only on secure or local pages.
- The system uses plain HTTP: keep it on the trusted office network and never open port 6543 to the internet.

### Start automatically when Windows starts

1. Open **Task Scheduler** → *Create Task*.
2. **General:** name it `Century Gate VMS`, choose *Run only when user is logged on*.
3. **Triggers:** *New* → *At log on* → your account.
4. **Actions:** *New* → Program `cmd.exe`, Arguments `/c "set CGVMS_NOPAUSE=1&& C:\CenturyGateVMS\century-gate-vms\start-production.bat"`.
5. Click **OK**. Set Windows to sign in this account automatically if the PC should run unattended.

### Daily backups

A full backup is the database plus the photo folder `.cgvms\data\photos`, and the `CG_SECRETS_KEY` from Step 4.

1. Create a backup folder, e.g. `D:\CenturyGateVMS\backups`. Right-click it → *Properties* → *Security* → *Edit* → *Add*, type `NT SERVICE\MSSQL$SQLEXPRESS`, and give it **Modify** permission (SQL Server writes the file itself).
2. Test it once in PowerShell, in the `backend` folder: `.venv\Scripts\python -m app.cli backup --to D:\CenturyGateVMS\backups`.
3. In Task Scheduler, add a daily task: Program `C:\CenturyGateVMS\century-gate-vms\backend\.venv\Scripts\python.exe`, Arguments `-m app.cli backup --to D:\CenturyGateVMS\backups`, *Start in* `C:\CenturyGateVMS\century-gate-vms\backend`.
4. Copy the backup folder and the photo folder to another disk or network share regularly.

### Moving data from an old PC

A new install starts with an empty database. To carry over existing data instead:

1. On the old PC, run the backup command above and stop the system.
2. Copy the `.bak` file, the old `.cgvms\data\photos` folder, and the old `CG_SECRETS_KEY` value to the new PC.
3. Before the first `start-production.bat` on the new PC, put the old key in `backend\.env`, copy the photos to `.cgvms\data\photos` in the new project folder, and restore the `.bak` in SSMS (*Databases* → right-click → *Restore Database* → *Device* → the file) with the name `century_gate_vms`.
4. Then run `start-production.bat`; it brings the restored tables up to date automatically.

### Installing an update

1. Double-click `stop-production.bat`.
2. In the project folder: `git pull`.
3. If `backend\requirements.txt` changed: `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`. If `frontend\package-lock.json` changed: `cd frontend` then `npm ci`.
4. Run `.\start-production.bat rebuild` from PowerShell in the project folder. It rebuilds the web app and updates the database.

## Troubleshooting

`start-production.bat` stops at the first problem and prints the reason in red after `ERROR:`. Find that message below.

| What you see | Likely cause | Fix |
| --- | --- | --- |
| `Missing:` followed by a list | A step was skipped | Python environment → redo Step 3 backend; `node_modules` → run `npm ci` in `frontend`; `backend\.env` → redo Step 4 |
| `SQL Server is not reachable or refused the login` | SQL Server service stopped, or not installed with the name `SQLEXPRESS` | Start **SQL Server (SQLEXPRESS)** in `services.msc`. If it isn't listed, redo Step 2 and choose *Basic*. |
| `Data source name not found` / `Can't open lib 'ODBC Driver 18 for SQL Server'` | ODBC driver missing | Install ODBC Driver 18 (Step 2, item 4) |
| `Login failed for user '…'` | You signed in to Windows with a different account than the one that installed SQL Server | Sign in with the installing account, or add your account as a login in SSMS (*Security* → *Logins* → *New Login*, server role **sysadmin**) |
| `Port 8000 (or 6543) is already in use` | The system, or another program, is already running | Run `stop-production.bat`, close any old **CGVMS API** / **CGVMS Web** windows, then start again |
| `npm run build failed` | `npm ci` did not finish, or not enough memory | Run `npm ci` in `frontend` again, close other programs, then run `start-production.bat rebuild` |
| `configuration is not valid` | A typo in `backend\.env` | Read the setting named in the message; compare with `.env.example`. The key in `CG_SECRETS_KEY` must be pasted exactly as printed. |
| `running scripts is disabled on this system` | PowerShell's default safety setting blocks `npm` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer **Y** |
| `py` / `python` / `node` *is not recognized* | Program not on PATH | Reinstall it with the PATH option ticked, then reopen PowerShell |
| Gate PC shows *can't reach this page* | Firewall, wrong IP, or system not running | Check `http://localhost:6543` on the server first, then see [Connect the gate PCs](#connect-the-gate-pcs) |
| Gate PC keeps switching to `https://` | The browser remembered an old HTTPS address | Use the IP address instead of the PC name, or clear it at `edge://net-internals/#hsts` |
| Forgot the admin password | — | In `backend`: `.venv\Scripts\python -m app.cli create-admin --username admin2` creates a new admin account |

For a full status report at any time, run `powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1` in the project folder. Live error messages appear in the **CGVMS API** and **CGVMS Web** windows.

## Installation checklist

Tick each item as you go.

- [ ] Git, Python 3.12 and Node.js 24 installed; version check passes
- [ ] Project folder at `C:\CenturyGateVMS\century-gate-vms`
- [ ] SQL Server 2022 Express (Basic) installed; service **SQL Server (SQLEXPRESS)** running
- [ ] ODBC Driver 18 for SQL Server installed
- [ ] `backend\.venv` created and `requirements.txt` installed
- [ ] `npm ci` finished in `frontend`
- [ ] `backend\.env` created with `CG_SECRETS_KEY` and `CG_ORGANIZATION_NAME`
- [ ] Copy of `CG_SECRETS_KEY` stored safely
- [ ] `start-production.bat` ends with *running in production mode*
- [ ] Signed in as admin and changed the password
- [ ] Staff accounts created
- [ ] A gate PC opens `http://<server IP>:6543`
- [ ] Optional: auto-start task and daily backup task set up
