@echo off
setlocal EnableExtensions

rem Starts or reuses the local Vite and FastAPI services from any working directory.
set "PROJECT_ROOT=%~dp0"
set "APP_PATH=%PROJECT_ROOT%app"
set "SERVER_PATH=%PROJECT_ROOT%server"
set "FRONTEND_URL=http://127.0.0.1:5173"
set "SWAGGER_URL=http://127.0.0.1:8787/docs"
set "NO_BROWSER=0"

if /I "%~1"=="--no-browser" set "NO_BROWSER=1"
if not "%~1"=="" if /I not "%~1"=="--no-browser" (
    echo Unknown option: %~1
    echo Usage: %~nx0 [--no-browser]
    exit /b 1
)

where pnpm >nul 2>&1 || (
    echo pnpm was not found. Install it and add it to PATH before retrying.
    exit /b 1
)

where uv >nul 2>&1 || (
    echo uv was not found. Install it and add it to PATH before retrying.
    exit /b 1
)

if not exist "%APP_PATH%\node_modules" (
    echo Frontend dependencies are missing. Run pnpm install in the app directory first.
    exit /b 1
)

if not exist "%SERVER_PATH%\.venv" (
    echo Backend virtual environment is missing. Run uv sync in the server directory first.
    exit /b 1
)

call :EnsureService "FastAPI backend" "%SERVER_PATH%" "uv run python -m bhzd_py.main" 8787 "%SWAGGER_URL%" || exit /b 1
call :EnsureService "Vite frontend" "%APP_PATH%" "pnpm dev" 5173 "%FRONTEND_URL%" || exit /b 1

if "%NO_BROWSER%"=="0" (
    rem Open pages only after both HTTP probes succeed.
    start "" "%FRONTEND_URL%"
    start "" "%SWAGGER_URL%"
)

echo Project is running. Frontend: %FRONTEND_URL%  Swagger: %SWAGGER_URL%
exit /b 0

:EnsureService
set "SERVICE_NAME=%~1"
set "SERVICE_PATH=%~2"
set "SERVICE_COMMAND=%~3"
set "SERVICE_PORT=%~4"
set "SERVICE_URL=%~5"

call :TestHttpEndpoint "%SERVICE_URL%"
if not errorlevel 1 (
    echo %SERVICE_NAME% is already running: %SERVICE_URL%
    exit /b 0
)

call :TestPortListening %SERVICE_PORT%
if not errorlevel 1 (
    echo %SERVICE_NAME% port %SERVICE_PORT% is occupied, but %SERVICE_URL% is unavailable.
    echo Free the port and run this script again.
    exit /b 1
)

rem Separate visible command windows preserve each service's logs and stop control.
start "BHZD - %SERVICE_NAME%" /D "%SERVICE_PATH%" cmd.exe /k "%SERVICE_COMMAND%"
echo Starting %SERVICE_NAME%...
call :WaitForEndpoint "%SERVICE_URL%" "%SERVICE_NAME%"
exit /b %errorlevel%

:TestHttpEndpoint
powershell.exe -NoProfile -Command "$response = Invoke-WebRequest -Uri '%~1' -TimeoutSec 2 -UseBasicParsing; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { exit 0 }; exit 1" >nul 2>&1
exit /b %errorlevel%

:TestPortListening
powershell.exe -NoProfile -Command "$listener = Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue; if ($null -ne $listener) { exit 0 }; exit 1" >nul 2>&1
exit /b %errorlevel%

:WaitForEndpoint
for /L %%I in (1,1,30) do (
    call :TestHttpEndpoint "%~1"
    if not errorlevel 1 (
        echo %~2 is ready: %~1
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)

echo %~2 did not become ready within 30 seconds: %~1
exit /b 1