# Century Gate VMS — Production commands

## Production on one Windows 11 PC (from this project folder)

The existing project runs in production mode as normal programs: no copy of the application, no Windows services.
This is the only supported production deployment: `start-production.bat`, plain HTTP, port 6543, gate PCs open
`http://<this PC's IP>:6543`. There is no Caddy, HTTPS, certificate or port 443, and Windows Firewall is not part
of it (no script changes it). Backups: `python -m app.cli backup` plus a copy of the photo folder (below, and
README "Backups").

| Part | Production command (started by `production.ps1`) | Listens on | Log |
| --- | --- | --- | --- |
| SQL Server | the Windows service **SQL Server (SQLEXPRESS)**, already installed and running; `production.ps1` only connects (`app.cli create-database`, then `migrate`) and never starts or stops it | the instance in `CG_MSSQL_SERVER` (default `.\SQLEXPRESS`) | SQL Server's error log / Windows Event Viewer |
| API | `backend\.venv\Scripts\python -m app.serve --host 127.0.0.1 --port 8000` (no reload, no API docs) | 127.0.0.1:8000 | the **CGVMS API** window (JSON lines) |
| Web | `npm run build`, then `node server.mjs --hostname 0.0.0.0 --port 6543` (Next.js production server; sets the client address the API sees) | 0.0.0.0:6543 (plain HTTP) | the **CGVMS Web** window |

As with `start-dev.bat`, the API and the web server each run in their own console window, **CGVMS API** and
**CGVMS Web**, and print their output there live. Closing one of these windows stops that server (start it again
with `start-production.bat`); `stop-production.bat` closes both. Their output is not saved to a file. Other
databases on the SQL Server instance, and the legacy desktop database `century_gate_system`, are never used or
touched.

**Plain HTTP on the organization's trusted network:** gate PCs open `http://<this PC's name or IP>:6543`. No Caddy, no TLS, no
certificate. Only the web server listens on the network; the API stays on 127.0.0.1. HTTP is not
encrypted (passwords, session cookies and visitor data cross the LAN in clear text): never expose port 6543 to
the internet. Gate cameras (Hikvision) work (server-side); the browser webcam fallback and webcam QR scanning
need HTTPS and so only work on this PC itself (`http://localhost:6543`). README, "Production on one Windows 11 PC".

**Settings:** `backend\.env` as it is (the database: `CG_MSSQL_*`; by default Windows authentication as the
signed-in account, which must be allowed to use the database). For the API process only, `production.ps1` sets
`CG_ENVIRONMENT=production`, `CG_DEPLOYMENT_MODE=http-lan` (cookies without `Secure`, for plain HTTP) and
`CG_PHOTO_DIR=<project>\.cgvms\data\photos` (the existing photos; a `CG_PHOTO_DIR` in `backend\.env` wins). `start-dev.bat` keeps working unchanged. Optional: `CGVMS_SITE` = the name gate PCs use in
messages (default: this PC's computer name).

### Once

1. Prerequisites already used for development: `backend\.venv`, `frontend\node_modules`, `backend\.env`, SQL Server
   (Express) with the ODBC Driver 18 for SQL Server. The first start creates the database `century_gate_vms`.
2. Connect this PC to the organization's network. Any organization network works: the Windows network profile
   (Public, Private or Domain), the network name and the IP addresses are not checked, and no subnet is
   configured anywhere. Node listens on `0.0.0.0:6543`; the API stays on 127.0.0.1 on every network.
3. First login: on a database with no account yet, `start-production.bat` creates **admin / admin1234**. Log in
   on this PC right after the first start: the app makes you choose a new password before anything else.
4. Each gate PC: open the `http://<this PC's IP>:6543` address that `start-production.bat` prints, or
   `http://<this PC's name>:6543`. If the name does not resolve, use the IP or add `<this PC's IP> <name>` to the gate
   PC's `C:\Windows\System32\drivers\etc\hosts`. A browser that used the former `https://<name>` address may
   force HTTPS for that name (HSTS): use the IP, or clear the name at `edge://net-internals/#hsts`.

### Daily operations (double-click in project root folder)

| Task | Command |
| --- | --- |
| Start | `start-production.bat` (ends with the health check) |
| Stop | `stop-production.bat` (web, then API; SQL Server keeps running) |
| Backup | `cd backend; .venv\Scripts\python -m app.cli backup --to D:\CenturyGateVMS\backups`, and copy the photo folder; the SQL Server service account must be allowed to write to the folder (README "Backups") |
| Health | `powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1` |
| After an update (`git pull`) | `stop-production.bat` then `start-production.bat rebuild` (runs `npm run build`); if `requirements.txt` changed first `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`; if the schema changed `cd backend; .venv\Scripts\python -m app.cli migrate` |

The programs keep running when the start window closes (not when their own CGVMS API / CGVMS Web window is
closed) and stop at sign-out or shutdown. To start them with Windows,
add a Task Scheduler task "At log on" that runs `start-production.bat` with `CGVMS_NOPAUSE=1` (optional).
