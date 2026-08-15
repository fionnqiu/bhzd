[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$BackendPort = 8787,
    [int]$FrontendPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$serverPath = Join-Path $ProjectRoot "server"
$appPath = Join-Path $ProjectRoot "app"
$logPath = Join-Path $ProjectRoot "var\logs"
New-Item -ItemType Directory -Path $logPath -Force | Out-Null

function Assert-PortAvailable([int]$Port, [string]$Name) {
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        $processIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
        $processDetails = $processIds | ForEach-Object {
            Get-CimInstance Win32_Process -Filter "ProcessId = $_" | Select-Object ProcessId, CommandLine
        }
        $detailText = ($processDetails | Format-Table -AutoSize | Out-String).Trim()
        throw "$Name port $Port is already in use. This script will not stop an existing process.`n$detailText"
    }
}

# Refuse to guess listener ownership: the operator can change ports or resolve the conflict explicitly.
Assert-PortAvailable -Port $BackendPort -Name "FastAPI"
Assert-PortAvailable -Port $FrontendPort -Name "Vite"

$backendLog = Join-Path $logPath "backend.log"
$frontendLog = Join-Path $logPath "frontend.log"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "set BHZD_HOST=127.0.0.1&& set BHZD_PORT=$BackendPort&& uv run --locked python -m bhzd_py.main > `"$backendLog`" 2>&1" -WorkingDirectory $serverPath -WindowStyle Hidden
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "set VITE_API_TARGET=http://127.0.0.1:$BackendPort&& pnpm dev -- --port $FrontendPort > `"$frontendLog`" 2>&1" -WorkingDirectory $appPath -WindowStyle Hidden

$backendUrl = "http://127.0.0.1:$BackendPort/api/health"
$frontendUrl = "http://127.0.0.1:$FrontendPort/api/health"
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $backend = Invoke-RestMethod -Uri $backendUrl -TimeoutSec 2
        $frontend = Invoke-RestMethod -Uri $frontendUrl -TimeoutSec 2
        if ($backend.status -eq "ok" -and $frontend.status -eq "ok") {
            Write-Host "BHZD is ready: http://127.0.0.1:$FrontendPort"
            exit 0
        }
    }
    catch {
        Start-Sleep -Seconds 1
    }
}

throw "BHZD did not become ready. Inspect $backendLog and $frontendLog."
