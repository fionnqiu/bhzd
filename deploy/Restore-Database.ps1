[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$DatabasePath,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $ProjectRoot "var\bhzd.sqlite"
}
if (-not [System.IO.Path]::IsPathRooted($DatabasePath)) {
    $DatabasePath = Join-Path $ProjectRoot $DatabasePath
}
$BackupPath = (Resolve-Path -LiteralPath $BackupPath).Path
$DatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$defaultDatabasePath = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot "var\bhzd.sqlite"))

if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
    throw "Backup file was not found: $BackupPath"
}
if ($BackupPath -eq $DatabasePath) {
    throw "BackupPath must not be the target database path."
}
if ((Test-Path -LiteralPath $DatabasePath) -and -not $Force) {
    throw "Target database already exists: $DatabasePath. Use -Force and confirm only after stopping the backend."
}
if ($DatabasePath -eq $defaultDatabasePath -and (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue)) {
    throw "Port 8787 is listening. Stop the BHZD backend before restoring its database."
}

$serverPython = Join-Path $ProjectRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $serverPython)) {
    throw "Backend virtual environment is missing. Run Initialize-BHZD.ps1 before restoring a backup."
}
$targetDirectory = Split-Path -Parent $DatabasePath
New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
$stagingPath = "$DatabasePath.restore-staging"
$previousPath = "$DatabasePath.pre-restore-$(Get-Date -Format 'yyyyMMddHHmmss')"

if ($PSCmdlet.ShouldProcess($DatabasePath, "Replace database using $BackupPath")) {
    # Restore through SQLite rather than byte-copying so the restored database is internally consistent.
    $restoreCode = @'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:3]
with sqlite3.connect(source_path) as source, sqlite3.connect(destination_path) as destination:
    source.backup(destination)
'@
    & $serverPython -c $restoreCode $BackupPath $stagingPath
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite restore staging failed."
    }

    if (Test-Path -LiteralPath $DatabasePath) {
        Move-Item -LiteralPath $DatabasePath -Destination $previousPath
    }
    Move-Item -LiteralPath $stagingPath -Destination $DatabasePath

    # Stale sidecar files cannot be paired with the new database. Preserve them for recovery instead of deleting.
    foreach ($suffix in @("-wal", "-shm")) {
        $sidecarPath = "$DatabasePath$suffix"
        if (Test-Path -LiteralPath $sidecarPath) {
            Move-Item -LiteralPath $sidecarPath -Destination "$previousPath$suffix"
        }
    }
    Write-Host "Restored database to $DatabasePath"
    if (Test-Path -LiteralPath $previousPath) {
        Write-Host "Previous database retained at $previousPath"
    }
}
