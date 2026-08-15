[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DatabasePath,
    [Parameter(Mandatory = $true)]
    [string]$DestinationPath,
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
$DatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$DestinationPath = [System.IO.Path]::GetFullPath($DestinationPath)

if (-not (Test-Path -LiteralPath $DatabasePath -PathType Leaf)) {
    throw "Source database was not found: $DatabasePath"
}
if ($DatabasePath -eq $DestinationPath) {
    throw "DestinationPath must not be the active database path."
}
if ((Test-Path -LiteralPath $DestinationPath) -and -not $Force) {
    throw "Backup already exists: $DestinationPath. Use -Force only when replacement is intentional."
}

$destinationDirectory = Split-Path -Parent $DestinationPath
New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
$serverPython = Join-Path $ProjectRoot "server\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $serverPython)) {
    throw "Backend virtual environment is missing. Run Initialize-BHZD.ps1 before creating a backup."
}

# SQLite's backup API captures a transactionally consistent snapshot even while the application uses WAL.
$backupCode = @'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:3]
with sqlite3.connect(source_path) as source, sqlite3.connect(destination_path) as destination:
    source.backup(destination)
'@
& $serverPython -c $backupCode $DatabasePath $DestinationPath
if ($LASTEXITCODE -ne 0) {
    throw "SQLite backup failed."
}

Write-Host "Created SQLite backup: $DestinationPath"
