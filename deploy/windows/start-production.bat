@echo off
rem ============================================================================
rem  Century Gate VMS - start the application in PRODUCTION mode on this PC,
rem  from this project folder (no copy, no Windows services):
rem
rem    1. MongoDB   127.0.0.1:27018   the project's database (.dev\mongo)
rem    2. build     npm run build     only when there is no build yet
rem    3. API       127.0.0.1:8000    python -m app.serve (no reload)
rem    4. Web       0.0.0.0:6543      node server.mjs (Next.js production server)
rem    then the health check.
rem
rem  Gate PCs open http://<this PC's name or IP>:6543 (plain HTTP on the trusted
rem  LAN; no Caddy, no certificate). A double-click is enough; Windows Firewall is
rem  not changed by this script.
rem  Output: the "CGVMS API" and "CGVMS Web" windows.  Details: deploy\windows\production.ps1, deploy\PRODUCTION-COMMANDS.md
rem
rem  Optional:  start-production.bat rebuild    (npm run build first, after an update)
rem ============================================================================
setlocal
set "EXTRA="
if /i "%~1"=="rebuild" set "EXTRA=-Rebuild"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0production.ps1" -Action start %EXTRA%
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
    echo.
    echo Start-up stopped - see above.
)
if not defined CGVMS_NOPAUSE pause
endlocal & exit /b %CODE%
