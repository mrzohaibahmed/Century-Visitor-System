@echo off
rem ============================================================================
rem  Century Gate VMS - start the application for LOCAL DEVELOPMENT on this PC.
rem
rem    1. development MongoDB  127.0.0.1:27018  (scripts\dev_mongo.py; never the
rem       legacy MongoDB service on 27017)
rem    2. database migration   (safe to repeat) and, on a brand-new database only,
rem       the first administrator:  admin / admin1234  (a new password must be
rem       chosen at the first login)
rem    3. API                  http://127.0.0.1:8000  (own window, auto-reload)
rem    4. web                  http://localhost:3000  (own window, auto-reload)
rem    5. opens the browser
rem
rem  Anything already running is left alone. Close the "CGVMS API" and
rem  "CGVMS Web" windows to stop them; stop the database with:
rem      backend\.venv\Scripts\python scripts\dev_mongo.py stop
rem
rem  This is NOT for the gate server: production runs as Windows services
rem  (see README, "Production operations").
rem ============================================================================
setlocal
cd /d "%~dp0"
set "PY=%~dp0backend\.venv\Scripts\python.exe"

rem ---- prerequisites ---------------------------------------------------------
if not exist "%PY%" (
    echo ERROR: The API environment is missing. Set it up first ^(README, "Local development"^):
    echo     cd backend
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements-dev.txt
    goto :fail
)
if not exist "frontend\node_modules" (
    echo ERROR: The frontend dependencies are missing. Run:  cd frontend ^&^& npm install
    goto :fail
)
if not exist "backend\.env" (
    echo Creating backend\.env from backend\.env.example ...
    copy /y "backend\.env.example" "backend\.env" >nul
)
if not exist "frontend\.env.local" (
    echo Creating frontend\.env.local from frontend\.env.example ...
    copy /y "frontend\.env.example" "frontend\.env.local" >nul
)

rem ---- 1. database -------------------------------------------------------------
echo.
echo [1/5] Development database ...
"%PY%" scripts\dev_mongo.py start
if errorlevel 1 goto :fail

rem ---- 2. migration ------------------------------------------------------------
echo.
echo [2/5] Database schema ...
pushd backend
"%PY%" -m app.cli migrate >nul 2>&1
if errorlevel 1 (
    popd
    echo ERROR: The migration failed. Run it by hand to see why:  cd backend ^&^& .venv\Scripts\python -m app.cli migrate
    goto :fail
)
"%PY%" -m app.cli dev-first-admin
if errorlevel 1 (
    popd
    goto :fail
)
popd
echo       up to date.

rem ---- 3. API ------------------------------------------------------------------
echo.
echo [3/5] API on port 8000 ...
netstat -ano | findstr /R /C:"127.0.0.1:8000 .*LISTENING" /C:"0.0.0.0:8000 .*LISTENING" >nul
if not errorlevel 1 (
    echo       already running - left as it is.
) else (
    start "CGVMS API" /D "%~dp0backend" cmd /k ".venv\Scripts\python -m uvicorn app.main:create_app --factory --reload --port 8000"
    echo       started in the window "CGVMS API".
)

rem ---- 4. web ------------------------------------------------------------------
echo.
echo [4/5] Web on port 3000 ...
netstat -ano | findstr /R /C:":3000 .*LISTENING" >nul
if not errorlevel 1 (
    echo       already running - left as it is.
) else (
    start "CGVMS Web" /D "%~dp0frontend" cmd /k "npm run dev"
    echo       started in the window "CGVMS Web".
)

rem ---- 5. browser --------------------------------------------------------------
echo.
echo [5/5] Waiting for the application (up to 2 minutes) ...
powershell -NoProfile -Command "$end=(Get-Date).AddMinutes(2); while((Get-Date) -lt $end){ try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 http://localhost:3000/login; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Seconds 2 }; exit 1"
if errorlevel 1 (
    echo WARNING: The web page did not answer yet. Check the "CGVMS Web" and "CGVMS API" windows.
    goto :end
)
start "" http://localhost:3000
echo.
echo Century Gate VMS is running:  http://localhost:3000
echo First login on a new database:  admin / admin1234  (you then choose your own password)
echo (Use localhost, not 127.0.0.1: the development web server only serves localhost.)
goto :end

:fail
echo.
echo Start-up stopped.
pause
exit /b 1

:end
endlocal
exit /b 0
