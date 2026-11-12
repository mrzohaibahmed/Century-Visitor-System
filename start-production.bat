@echo off
rem ============================================================================
rem  Century Gate VMS - start the application in PRODUCTION mode on this PC:
rem
rem    1. SQL Server .\SQLEXPRESS     the application database (created if missing,
rem                                   then migrated; the service itself keeps running)
rem    2. build     npm run build     only when there is no build yet
rem    3. API       127.0.0.1:8000    python -m app.serve (no reload)
rem    4. Web       0.0.0.0:6543      node server.mjs (Next.js production server)
rem    then the health check.
rem
rem  Gate PCs open http://<this PC's name or IP>:6543 (plain HTTP on the trusted
rem  LAN; no Caddy, no certificate).
rem
rem  Optional:  start-production.bat rebuild    (npm run build first, after an update)
rem ============================================================================
setlocal
set "EXTRA="
if /i "%~1"=="rebuild" set "EXTRA=-Rebuild"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\production.ps1" -Action start %EXTRA%
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
    echo.
    echo Start-up stopped - see above.
)
if not defined CGVMS_NOPAUSE pause
endlocal & exit /b %CODE%
