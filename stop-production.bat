@echo off
rem ============================================================================
rem  Century Gate VMS - stop the production application on this PC:
rem  web, API, then MongoDB (clean shutdown).
rem  Start again with start-production.bat.
rem ============================================================================
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\production.ps1" -Action stop
set "CODE=%errorlevel%"
if not defined CGVMS_NOPAUSE pause
endlocal & exit /b %CODE%
