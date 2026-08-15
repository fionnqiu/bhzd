[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$Demo
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# The seed loader is intentionally the single migration entry point: it preserves migration hashes
# and creates only missing baseline rows, so rerunning this script never resets existing data.
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$serverPath = Join-Path $ProjectRoot "server"
if (-not (Test-Path -LiteralPath (Join-Path $serverPath "uv.lock"))) {
    throw "Cannot find server/uv.lock below $ProjectRoot."
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found in PATH. Run Initialize-BHZD.ps1 after installing uv."
}

Push-Location $serverPath
try {
    $arguments = @("run", "--locked", "python", "-m", "bhzd_py.seed.loader")
    if ($Demo) {
        # Demo data is explicitly opt-in because it adds accounts, classes, documents, and exercises.
        $arguments += "--demo"
    }
    & uv @arguments
}
finally {
    Pop-Location
}
