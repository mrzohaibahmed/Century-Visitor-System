@echo off
rem ============================================================================
rem  Century Gate VMS - stop the application (production, Windows services).
rem
rem  Stops, in this order:  CGVMS-Proxy, CGVMS-Web, CGVMS-API, CGVMS-MongoDB
rem  (gate PCs first lose the site, then the database shuts down cleanly last).
rem  Services that are already stopped or not installed are skipped.
rem  The legacy MongoDB on port 27017 is not touched.
rem
rem  Must be run as Administrator (right-click - "Run as administrator").
rem  Start again with start-production.bat (or restart the PC: the services
rem  start by themselves with Windows).
rem ============================================================================
setlocal
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run this file as Administrator ^(right-click - "Run as administrator"^).
    if not defined CGVMS_NOPAUSE pause
    exit /b 1
)

set "FAILED="
call :stop_service 1 CGVMS-Proxy
call :stop_service 2 CGVMS-Web
call :stop_service 3 CGVMS-API
call :stop_service 4 CGVMS-MongoDB

echo.
if defined FAILED (
    echo Some services did not stop - see above.
    if not defined CGVMS_NOPAUSE pause
    endlocal
    exit /b 1
)
echo Century Gate VMS is stopped.
if not defined CGVMS_NOPAUSE pause
endlocal
exit /b 0

rem ---- stop_service <step> <name> ------------------------------------------------
:stop_service
echo.
echo [%~1/4] %~2 ...
sc query "%~2" >nul 2>&1
if errorlevel 1 (
    echo       not installed - skipped.
    exit /b 0
)
sc query "%~2" | findstr /C:"STOPPED" >nul
if not errorlevel 1 (
    echo       already stopped.
    exit /b 0
)
powershell -NoProfile -Command "try { Stop-Service -Name '%~2' -ErrorAction Stop; (Get-Service '%~2').WaitForStatus('Stopped', [TimeSpan]::FromSeconds(90)); exit 0 } catch { Write-Host ('      ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
    echo ERROR: %~2 did not stop.
    set "FAILED=1"
    exit /b 1
)
echo       stopped.
exit /b 0
