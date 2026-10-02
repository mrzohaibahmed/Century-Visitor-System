@echo off
rem ============================================================================
rem  Century Gate VMS - stop the production application on this PC:
rem  web, API, then MongoDB (clean shutdown). A Caddy left from the former
rem  HTTPS setup is stopped too, if this script started it.
rem  The legacy MongoDB on port 27017 is not touched.
rem  Start again with start-production.bat.
rem ============================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0production.ps1" -Action stop
set "CODE=%errorlevel%"
if not defined CGVMS_NOPAUSE pause
endlocal & exit /b %CODE%
