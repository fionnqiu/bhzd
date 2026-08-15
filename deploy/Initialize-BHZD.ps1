[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$CreateLocalConfig,
    [switch]$SkipDependencyInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve the root once so callers can invoke the script from any working directory.
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$appPath = Join-Path $ProjectRoot "app"
$serverPath = Join-Path $ProjectRoot "server"

foreach ($requiredPath in @($appPath, $serverPath, (Join-Path $ProjectRoot ".env.example"))) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "The supplied project root is incomplete: $requiredPath"
    }
}

foreach ($command in @("pnpm", "uv")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command was not found in PATH. Install the prerequisite described in docs/deployment/windows-deployment.md."
    }
}

if ($CreateLocalConfig) {
    $examplePath = Join-Path $ProjectRoot ".env.example"
    $localConfigPath = Join-Path $ProjectRoot ".env.local"
    if (Test-Path -LiteralPath $localConfigPath) {
        Write-Host ".env.local already exists; it was not changed."
    }
    else {
        # The template contains placeholders only. Operators must fill secrets outside version control.
        Copy-Item -LiteralPath $examplePath -Destination $localConfigPath
        Write-Host "Created $localConfigPath from .env.example. Review it before starting the service."
    }
}

if (-not $SkipDependencyInstall) {
    Push-Location $serverPath
    try {
        # uv.lock pins runtime dependencies so a new computer receives the reviewed dependency set.
        & uv sync --locked --no-dev
    }
    finally {
        Pop-Location
    }

    Push-Location $appPath
    try {
        # pnpm-lock.yaml is the frontend equivalent of the backend's locked installation.
        & pnpm install --frozen-lockfile
    }
    finally {
        Pop-Location
    }
}

Write-Host "BHZD prerequisites are ready at $ProjectRoot"
