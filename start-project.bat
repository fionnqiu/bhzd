@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem Starts or safely reuses the local Vite and FastAPI services from any working directory.
set "PROJECT_ROOT=%~dp0"
rem Normalize the root before comparing it with Windows process command lines.
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "SCRIPT_NAME=%~nx0"
set "APP_PATH=%PROJECT_ROOT%\app"
set "SERVER_PATH=%PROJECT_ROOT%\server"
set "BACKEND_PORT=8787"
set "FRONTEND_PORT=5173"
set "FRONTEND_URL=http://127.0.0.1:%FRONTEND_PORT%"
set "BACKEND_HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%/api/health"
set "FRONTEND_HEALTH_URL=%FRONTEND_URL%/api/health"
set "SWAGGER_URL=http://127.0.0.1:%BACKEND_PORT%/docs"
set "NO_BROWSER=0"
set "PAUSE_ON_FAILURE=1"

rem These internal modes run inside visible child command windows so their ancestor
rem command lines retain this checkout path for future ownership verification.
if /I "%~1"=="--run-backend" goto :RunBackend
if /I "%~1"=="--run-frontend" goto :RunFrontend

:ParseOptions
if "%~1"=="" goto :StartProject
if /I "%~1"=="--no-browser" (
    set "NO_BROWSER=1"
    shift
    goto :ParseOptions
)
if /I "%~1"=="--no-pause" (
    set "PAUSE_ON_FAILURE=0"
    shift
    goto :ParseOptions
)
echo Unknown option.
echo Usage: %SCRIPT_NAME% [--no-browser] [--no-pause]
goto :Failure

:StartProject
call :EnsureBackend
if errorlevel 1 goto :Failure
call :EnsureFrontend
if errorlevel 1 goto :Failure

if "%NO_BROWSER%"=="0" (
    rem Open pages only after direct and proxied health probes both succeed.
    start "" "%FRONTEND_URL%"
    start "" "%SWAGGER_URL%"
)

echo Project is running. Frontend: %FRONTEND_URL%  Swagger: %SWAGGER_URL%
exit /b 0

:Failure
rem Explorer closes a failed batch window immediately, so retain the diagnostic for users.
echo.
echo Project did not start. Review the message above and retry after fixing the reported issue.
if "%PAUSE_ON_FAILURE%"=="1" pause
exit /b 1

:RunBackend
rem This launcher owns the fixed local port, so environment or .env overrides cannot
rem make the readiness probe observe a different backend instance.
set "BHZD_HOST=127.0.0.1"
set "BHZD_PORT=8787"
cd /d "%SERVER_PATH%" || exit /b 1
uv run --locked python -m bhzd_py.main
exit /b %errorlevel%

:RunFrontend
rem Vite must keep the matching proxy target and fail on a taken port instead of
rem silently selecting another port that this launcher does not monitor.
set "VITE_API_TARGET=http://127.0.0.1:8787"
cd /d "%APP_PATH%" || exit /b 1
pnpm --dir "%APP_PATH%" dev -- --host 127.0.0.1 --port 5173 --strictPort
exit /b %errorlevel%

:EnsureBackend
call :TestBHZDHealth "%BACKEND_HEALTH_URL%"
if not errorlevel 1 (
    call :TestExpectedOwner %BACKEND_PORT%
    if not errorlevel 1 (
        echo FastAPI backend is already running for this checkout: %BACKEND_HEALTH_URL%
        exit /b 0
    )
    echo FastAPI backend responded, but its ownership cannot be confirmed for this checkout.
    call :ShowPortOwner %BACKEND_PORT%
    exit /b 1
)

call :TestPortListening %BACKEND_PORT%
if not errorlevel 1 (
    echo FastAPI backend port %BACKEND_PORT% is occupied, but the expected health endpoint is unavailable.
    call :ShowPortOwner %BACKEND_PORT%
    exit /b 1
)

rem Synchronize from uv.lock before launch so a missing or stale environment cannot block a double-click start.
where uv >nul 2>&1 || (
    echo uv was not found. Install it and add it to PATH before retrying.
    exit /b 1
)
pushd "%SERVER_PATH%" >nul
if errorlevel 1 (
    echo Could not open the backend directory: %SERVER_PATH%
    exit /b 1
)
if not exist "%SERVER_PATH%\.venv\pyvenv.cfg" (
    rem .venv is a reproducible local artifact, so clear only this confirmed incomplete environment.
    echo Rebuilding the backend virtual environment from uv.lock...
    uv venv --clear .venv
    if errorlevel 1 (
        popd
        echo Could not recreate the backend virtual environment.
        exit /b 1
    )
)
uv sync --locked
if errorlevel 1 (
    popd
    echo Backend dependency synchronization failed.
    exit /b 1
)
popd
if not exist "%SERVER_PATH%\.venv\pyvenv.cfg" (
    echo Backend virtual environment is still incomplete after synchronization.
    exit /b 1
)

call :StartService "FastAPI backend" "--run-backend" "%SERVER_PATH%"
if errorlevel 1 exit /b 1
call :WaitForBackend
exit /b %errorlevel%

:EnsureFrontend
call :TestHttpSuccess "%FRONTEND_URL%"
if not errorlevel 1 (
    call :TestBHZDHealth "%FRONTEND_HEALTH_URL%"
    if not errorlevel 1 (
        call :TestExpectedOwner %FRONTEND_PORT%
        if not errorlevel 1 (
            echo Vite frontend is already running for this checkout: %FRONTEND_URL%
            exit /b 0
        )
        echo Vite frontend responded, but its ownership cannot be confirmed for this checkout.
        call :ShowPortOwner %FRONTEND_PORT%
        exit /b 1
    )
)

call :TestPortListening %FRONTEND_PORT%
if not errorlevel 1 (
    echo Vite frontend port %FRONTEND_PORT% is occupied, but its BHZD API proxy is unavailable.
    call :ShowPortOwner %FRONTEND_PORT%
    exit /b 1
)

rem Install the locked frontend toolchain only when it is absent; normal starts stay fast.
where pnpm >nul 2>&1 || (
    echo pnpm was not found. Install it and add it to PATH before retrying.
    exit /b 1
)
if not exist "%APP_PATH%\node_modules" (
    pushd "%APP_PATH%" >nul
    if errorlevel 1 (
        echo Could not open the frontend directory: %APP_PATH%
        exit /b 1
    )
    echo Installing the frontend dependencies from pnpm-lock.yaml...
    pnpm install --frozen-lockfile
    if errorlevel 1 (
        popd
        echo Frontend dependency installation failed.
        exit /b 1
    )
    popd
)

call :StartService "Vite frontend" "--run-frontend" "%APP_PATH%"
if errorlevel 1 exit /b 1
call :WaitForFrontend
exit /b %errorlevel%

:StartService
set "SERVICE_NAME=%~1"
set "SERVICE_MODE=%~2"
set "SERVICE_PATH=%~3"

rem Calling this batch file in the child shell leaves an auditable project-path marker
rem in the process ancestry while retaining the visible logs and manual stop control.
start "BHZD - %SERVICE_NAME%" /D "%SERVICE_PATH%" "%ComSpec%" /d /k call "%~f0" %SERVICE_MODE%
if errorlevel 1 (
    echo Could not open a command window for %SERVICE_NAME%.
    exit /b 1
)

echo Starting %SERVICE_NAME%...
exit /b 0

:WaitForBackend
for /L %%I in (1,1,30) do (
    call :TestBHZDHealth "%BACKEND_HEALTH_URL%"
    if not errorlevel 1 (
        call :TestExpectedOwner %BACKEND_PORT%
        if not errorlevel 1 (
            echo FastAPI backend is ready: %BACKEND_HEALTH_URL%
            exit /b 0
        )
    )
    rem timeout can skip waits when stdin is redirected, so use a process-independent delay.
    powershell.exe -NoProfile -Command "Start-Sleep -Seconds 1" >nul
)

echo FastAPI backend did not become ready within 30 seconds: %BACKEND_HEALTH_URL%
call :ShowPortOwner %BACKEND_PORT%
exit /b 1

:WaitForFrontend
for /L %%I in (1,1,30) do (
    call :TestHttpSuccess "%FRONTEND_URL%"
    if not errorlevel 1 (
        call :TestBHZDHealth "%FRONTEND_HEALTH_URL%"
        if not errorlevel 1 (
            call :TestExpectedOwner %FRONTEND_PORT%
            if not errorlevel 1 (
                echo Vite frontend is ready: %FRONTEND_URL%
                exit /b 0
            )
        )
    )
    rem timeout can skip waits when stdin is redirected, so use a process-independent delay.
    powershell.exe -NoProfile -Command "Start-Sleep -Seconds 1" >nul
)

echo Vite frontend did not become ready within 30 seconds: %FRONTEND_URL%
call :ShowPortOwner %FRONTEND_PORT%
exit /b 1

:TestBHZDHealth
rem A JSON health response prevents an unrelated 200/404 page from being reused.
powershell.exe -NoProfile -Command "$response = Invoke-RestMethod -Uri '%~1' -TimeoutSec 2 -ErrorAction Stop; if ($response.status -eq 'ok' -and $null -ne $response.version) { exit 0 }; exit 1" >nul 2>&1
exit /b %errorlevel%

:TestHttpSuccess
powershell.exe -NoProfile -Command "$response = Invoke-WebRequest -Uri '%~1' -TimeoutSec 2 -UseBasicParsing; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { exit 0 }; exit 1" >nul 2>&1
exit /b %errorlevel%

:TestPortListening
powershell.exe -NoProfile -Command "$listener = Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue; if ($null -ne $listener) { exit 0 }; exit 1" >nul 2>&1
exit /b %errorlevel%

:TestExpectedOwner
rem Working directories are not exposed by Win32_Process, so compare this script's
rem absolute path against each listener's ancestor command lines instead.
powershell.exe -NoProfile -Command "$port = [int]%~1; $projectRoot = [System.IO.Path]::GetFullPath('%PROJECT_ROOT%').TrimEnd('\'); $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); foreach ($listener in $listeners) { $listenerProcessId = [int]$listener.OwningProcess; $current = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $listenerProcessId) -ErrorAction SilentlyContinue; $depth = 0; while ($null -ne $current -and $depth -lt 16) { if ($current.CommandLine -and $current.CommandLine.IndexOf($projectRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { exit 0 }; if ($current.ParentProcessId -le 0 -or $current.ParentProcessId -eq $current.ProcessId) { break }; $current = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $current.ParentProcessId) -ErrorAction SilentlyContinue; $depth++ } }; exit 1" >nul 2>&1
exit /b %errorlevel%

:ShowPortOwner
powershell.exe -NoProfile -Command "$port = [int]%~1; $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); if ($listeners.Count -eq 0) { Write-Output ('No listener found on port {0}.' -f $port); exit 1 }; $seen = @{}; foreach ($listener in $listeners) { $listenerProcessId = [int]$listener.OwningProcess; if ($seen.ContainsKey($listenerProcessId)) { continue }; $seen[$listenerProcessId] = $true; $process = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $listenerProcessId) -ErrorAction SilentlyContinue; if ($null -eq $process) { Write-Output ('PID {0}: process details unavailable.' -f $listenerProcessId); continue }; Write-Output ('PID {0} ({1})' -f $process.ProcessId, $process.Name); Write-Output ('  CommandLine: {0}' -f $process.CommandLine); Write-Output ('  Parent PID: {0}' -f $process.ParentProcessId); $parent = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $process.ParentProcessId) -ErrorAction SilentlyContinue; if ($null -ne $parent) { Write-Output ('  Parent CommandLine: {0}' -f $parent.CommandLine) } }; exit 0"
exit /b %errorlevel%
