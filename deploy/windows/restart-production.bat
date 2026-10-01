@echo off
rem ============================================================================
rem  Century Gate VMS - restart the application: stop-production.bat, then
rem  start-production.bat (which ends with the health check).
rem
rem  Must be run as Administrator (right-click - "Run as administrator").
rem  To apply a change to backend\.env only, restarting CGVMS-API is enough:
rem      powershell Restart-Service CGVMS-API
rem
rem  Optional:  restart-production.bat C:\path\to\cgvms.psd1
rem ============================================================================
setlocal
set "CGVMS_NOPAUSE=1"
call "%~dp0stop-production.bat"
if errorlevel 1 goto :fail
call "%~dp0start-production.bat" %*
if errorlevel 1 goto :fail
echo.
echo Restart finished.
pause
endlocal
exit /b 0

:fail
echo.
echo Restart stopped - see above.
pause
endlocal
exit /b 1
