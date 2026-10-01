@echo off
rem ============================================================================
rem  Century Gate VMS - first-time PRODUCTION setup on this Windows 11 PC.
rem  Runs setup-production.ps1 (see the description at the top of that file).
rem
rem  Before running it:
rem    - put the application folder (this repository) anywhere on the PC
rem    - install Python 3.12 (all users), Node.js 24, MongoDB 8.x, and put caddy.exe,
rem      WinSW-x64.exe and the MongoDB Database Tools in C:\CenturyGateVMS\tools
rem      (the script lists anything missing and stops)
rem
rem  Right-click - "Run as administrator". Safe to run again after fixing a problem.
rem  Extra options are passed to the script, for example:
rem      setup-production.bat -SiteName vms-pc -PhotoDir E:\VisitorPhotos
rem ============================================================================
setlocal
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run this file as Administrator ^(right-click - "Run as administrator"^).
    pause
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-production.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup stopped. Fix the problem shown above and run this file again.
    pause
    exit /b 1
)
pause
endlocal
exit /b 0
