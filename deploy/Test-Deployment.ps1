[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$BackendPort = 8787,
    [int]$FrontendPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$backend = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 5
$frontend = Invoke-RestMethod -Uri "http://127.0.0.1:$FrontendPort/api/health" -TimeoutSec 5
if ($backend.status -ne "ok" -or $frontend.status -ne "ok") {
    throw "One or more health checks did not return status=ok."
}

$serverPython = Join-Path $ProjectRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $serverPython)) {
    throw "Backend virtual environment is missing."
}

# Query only migration metadata; the check avoids printing operational user or provider data.
$migrationCode = @'
from bhzd_py.config import get_config
from bhzd_py.db import connect

connection = connect(get_config().resolved_database_path)
try:
    print(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0])
finally:
    connection.close()
'@
Push-Location (Join-Path $ProjectRoot "server")
try {
    # Feed the check through stdin because Windows native-command argument rewriting can strip
    # SQL quotes from `python -c`, producing a false-negative deployment result.
    $migrationCount = $migrationCode | & $serverPython -
}
finally {
    Pop-Location
}
if ([int]$migrationCount -lt 1) {
    throw "No database migrations are recorded. Run Initialize-Database.ps1."
}

Write-Host "Deployment verification passed. Backend=$($backend.version); migrations=$migrationCount; frontend proxy=ok"
