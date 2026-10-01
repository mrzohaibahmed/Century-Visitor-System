@echo off
rem ============================================================================
rem  Century Gate VMS - restart: stop-production.bat, then start-production.bat.
rem
rem    restart-production.bat            restart (e.g. after changing backend\.env)
rem    restart-production.bat rebuild    after an update: also npm run build
rem ============================================================================
setlocal
set "CGVMS_NOPAUSE=1"
call "%~dp0stop-production.bat"
call "%~dp0start-production.bat" %*
set "CODE=%errorlevel%"
pause
endlocal & exit /b %CODE%
