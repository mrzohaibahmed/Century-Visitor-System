# Century Gate VMS — Production commands

## Production on one Windows 11 PC (from this project folder)

The existing project runs in production mode as normal programs: no copy of the application, no Windows services.
This is the only supported production deployment: `start-production.bat`, plain HTTP, port 6543, gate PCs open
`http://<this PC's IP>:6543`. There is no Caddy, HTTPS, certificate or port 443, and Windows Firewall is not part
of it (no script changes it). Backup and restore are not part of this VMS.

| Part | Production command (started by `production.ps1`) | Listens on | Log |
| --- | --- | --- | --- |
| MongoDB | `scripts\dev_mongo.py start` (the project's own database, data in `.dev\mongo`) | 127.0.0.1:27018 | `.dev\mongo\mongod.log` |
| API | `backend\.venv\Scripts\python -m app.serve --host 127.0.0.1 --port 8000` (no reload, no API docs) | 127.0.0.1:8000 | the **CGVMS API** window (JSON lines) |
| Web | `npm run build`, then `node server.mjs --hostname 0.0.0.0 --port 6543` (Next.js production server; sets the client address the API sees) | 0.0.0.0:6543 (plain HTTP) | the **CGVMS Web** window |

As with `start-dev.bat`, the API and the web server each run in their own console window, **CGVMS API** and
**CGVMS Web**, and print their output there live. Closing one of these windows stops that server (start it again
with `start-production.bat`); `stop-production.bat` closes both. Their output is not saved to a file. The legacy
MongoDB on 27017 is never used or touched.

**Plain HTTP on the organization's trusted network:** gate PCs open `http://<this PC's name or IP>:6543`. No Caddy, no TLS, no
certificate. Only the web server listens on the network; the API and MongoDB stay on 127.0.0.1. HTTP is not
encrypted (passwords, session cookies and visitor data cross the LAN in clear text): never expose port 6543 to
the internet. Gate cameras (Hikvision) work (server-side); the browser webcam fallback and webcam QR scanning
need HTTPS and so only work on this PC itself (`http://localhost:6543`). README, "Production on one Windows 11 PC".

**Settings:** `backend\.env` as it is. For the API process only, `production.ps1` sets
`CG_ENVIRONMENT=production`, `CG_DEPLOYMENT_MODE=http-lan` (cookies without `Secure`, for plain HTTP),
`CG_MONGO_LOCALHOST_WITHOUT_LOGIN=true` (the project's database has no login; this is only accepted for a
database on 127.0.0.1) and `CG_PHOTO_DIR=<project>\.dev\photos` (the existing photos; a `CG_PHOTO_DIR` in
`backend\.env` wins). `start-dev.bat` keeps working unchanged. Optional: `CGVMS_SITE` = the name gate PCs use in
messages (default: this PC's computer name).

### Once

1. Prerequisites already used for development: `backend\.venv`, `frontend\node_modules`, `backend\.env`, MongoDB 8.x.
2. Connect this PC to the organization's network. Any organization network works: the Windows network profile
   (Public, Private or Domain), the network name and the IP addresses are not checked, and no subnet is
   configured anywhere. Node listens on `0.0.0.0:6543`; the API and MongoDB stay on 127.0.0.1 on every network.
3. First login: on a database with no account yet, `start-production.bat` creates **admin / admin1234**. Log in
   on this PC right after the first start: the app makes you choose a new password before anything else.
4. Each gate PC: open the `http://<this PC's IP>:6543` address that `start-production.bat` prints, or
   `http://<this PC's name>:6543`. If the name does not resolve, use the IP or add `<this PC's IP> <name>` to the gate
   PC's `C:\Windows\System32\drivers\etc\hosts`. A browser that used the former `https://<name>` address may
   force HTTPS for that name (HSTS): use the IP, or clear the name at `edge://net-internals/#hsts`.

### Daily operations (double-click in `deploy\windows\`)

| Task | Command |
| --- | --- |
| Start | `start-production.bat` (ends with the health check) |
| Stop | `stop-production.bat` (web, API, then a clean MongoDB shutdown) |
| Restart | `restart-production.bat` |
| Health | `powershell -ExecutionPolicy Bypass -File deploy\windows\check-health.ps1` |
| After an update (`git pull`) | `restart-production.bat rebuild` (runs `npm run build`); if `requirements.txt` changed first `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt`; if the schema changed `cd backend; .venv\Scripts\python -m app.cli migrate` |

The programs keep running when the start window closes (not when their own CGVMS API / CGVMS Web window is
closed) and stop at sign-out or shutdown. To start them with Windows,
add a Task Scheduler task "At log on" that runs `start-production.bat` with `CGVMS_NOPAUSE=1` (optional).
