@echo off
rem ============================================================================
rem  Century Gate VMS - start the PRODUCTION services on the gate server.
rem
rem    1. CGVMS-MongoDB   database
rem    2. CGVMS-API       API
rem    3. CGVMS-Web       web
rem    4. CGVMS-Proxy     HTTPS proxy
rem    5. health check    (check-health.ps1, retried for up to 2 minutes)
rem
rem  Services are started in this order; any already running are left alone.
rem  Must be run as Administrator (right-click - "Run as administrator").
rem  Requires the services to be installed first (PRODUCTION-COMMANDS.md, step 12).
rem
rem  Optional:  start-production.bat C:\path\to\cgvms.psd1
rem             (default C:\CenturyGateVMS\config\cgvms.psd1)
rem ============================================================================
setlocal
cd /d "%~dp0"
set "CONFIG=%~1"
if "%CONFIG%"=="" set "CONFIG=C:\CenturyGateVMS\config\cgvms.psd1"

rem ---- prerequisites ---------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run this file as Administrator ^(right-click - "Run as administrator"^).
    goto :fail
)
if not exist "%CONFIG%" (
    echo ERROR: Settings file not found: %CONFIG%
    echo        See PRODUCTION-COMMANDS.md, step 4.
    goto :fail
)

rem ---- 1-4. services -----------------------------------------------------------
call :start_service 1 CGVMS-MongoDB || goto :fail
call :start_service 2 CGVMS-API     || goto :fail
call :start_service 3 CGVMS-Web     || goto :fail
call :start_service 4 CGVMS-Proxy   || goto :fail

rem ---- 5. health check -----------------------------------------------------------
echo.
echo [5/5] Health check (up to 2 minutes) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$end=(Get-Date).AddMinutes(2); do { & '%~dp0check-health.ps1' -ConfigPath '%CONFIG%' *> $null; if ($LASTEXITCODE -eq 0) { exit 0 }; Start-Sleep -Seconds 5 } while ((Get-Date) -lt $end); exit 1"
if errorlevel 1 (
    echo.
    echo WARNING: The application is not healthy yet. Details:
    echo.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-health.ps1" -ConfigPath "%CONFIG%"
    goto :fail
)

echo.
echo Century Gate VMS is running and healthy.
powershell -NoProfile -Command "Get-Service CGVMS-* | Format-Table -AutoSize Name, Status"
goto :end

rem ---- start_service <step> <name> -----------------------------------------------
:start_service
echo.
echo [%~1/5] %~2 ...
sc query "%~2" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Service %~2 is not installed. See PRODUCTION-COMMANDS.md, step 12.
    exit /b 1
)
sc query "%~2" | findstr /C:"RUNNING" >nul
if not errorlevel 1 (
    echo       already running - left as it is.
    exit /b 0
)
powershell -NoProfile -Command "try { Start-Service -Name '%~2' -ErrorAction Stop; (Get-Service '%~2').WaitForStatus('Running', [TimeSpan]::FromSeconds(60)); exit 0 } catch { Write-Host ('      ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 (
    echo ERROR: %~2 did not start. Check the service logs in C:\CenturyGateVMS\logs
    echo        and the Windows event log ^(Event Viewer - Windows Logs - Application^).
    exit /b 1
)
echo       started.
exit /b 0

:fail
echo.
echo Start-up stopped.
pause
endlocal
exit /b 1

:end
pause
endlocal
exit /b 0
