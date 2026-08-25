[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)]
    [string]$DestinationDirectory,
    [switch]$ServicesStopped,
    [int[]]$ExpectedStoppedPorts = @(8787, 5173)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ServicesStopped) {
    throw "Refusing to capture runtime state without -ServicesStopped. Stop only the confirmed BHZD services first."
}
foreach ($port in $ExpectedStoppedPorts) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Refusing to capture while port $port is still listening."
    }
}

$pathSeparators = [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$ProjectRoot = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ProjectRoot).Path).TrimEnd($pathSeparators)
$DestinationDirectory = [System.IO.Path]::GetFullPath($DestinationDirectory).TrimEnd($pathSeparators)
$projectPrefix = $ProjectRoot + [System.IO.Path]::DirectorySeparatorChar
if ($DestinationDirectory.Equals($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $DestinationDirectory.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "DestinationDirectory must be outside the project directory."
}
if (Test-Path -LiteralPath $DestinationDirectory) {
    $existing = @(Get-ChildItem -LiteralPath $DestinationDirectory -Force)
    if ($existing.Count -gt 0) {
        throw "DestinationDirectory must be empty so a manifest cannot mix snapshots."
    }
}
else {
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
}

$sourceVar = Join-Path $ProjectRoot "var"
$sourceDatabase = Join-Path $sourceVar "bhzd.sqlite"
$sourceLangGraph = Join-Path $sourceVar "bhzd.sqlite.langgraph"
$serverPython = Join-Path $ProjectRoot "server\.venv\Scripts\python.exe"
foreach ($requiredPath in @($sourceDatabase, $sourceLangGraph, $serverPython)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required runtime source is missing: $requiredPath"
    }
}

$destinationVar = Join-Path $DestinationDirectory "var"
New-Item -ItemType Directory -Path $destinationVar -Force | Out-Null

$excludedNames = @(
    "bhzd.sqlite",
    "bhzd.sqlite.langgraph",
    "bhzd.sqlite-wal",
    "bhzd.sqlite-shm",
    "bhzd.sqlite.langgraph-wal",
    "bhzd.sqlite.langgraph-shm"
)
$excludedPaths = @($excludedNames | ForEach-Object { [System.IO.Path]::GetFullPath((Join-Path $sourceVar $_)) })
$unexpectedSQLite = Get-ChildItem -LiteralPath $sourceVar -File -Recurse | Where-Object {
    $_.FullName -notin $excludedPaths -and $_.Name -match '(?i)(\.sqlite(?:$|[-.])|\.langgraph(?:$|[-.]))'
}
if ($unexpectedSQLite) {
    throw "Unexpected SQLite-like runtime files require an explicit migration rule: $($unexpectedSQLite.FullName -join ', ')"
}

# SQLite Backup API produces a transactionally consistent file and folds committed
# WAL pages into it; copying the live database or sidecars would not provide that guarantee.
$backupCode = @'
import sqlite3
import sys

source_path, destination_path = sys.argv[1:3]
with sqlite3.connect(source_path) as source, sqlite3.connect(destination_path) as destination:
    source.backup(destination)
    result = destination.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"integrity_check failed: {result}")
'@
foreach ($pair in @(
    @($sourceDatabase, (Join-Path $destinationVar "bhzd.sqlite")),
    @($sourceLangGraph, (Join-Path $destinationVar "bhzd.sqlite.langgraph"))
)) {
    & $serverPython -c $backupCode $pair[0] $pair[1]
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite backup failed for $($pair[0])."
    }
}

# Copy all other runtime files and directories (uploads, outbox, and future logs)
# while explicitly excluding every live SQLite database and sidecar.
Get-ChildItem -LiteralPath $sourceVar -Force | Where-Object {
    $_.Name -notin $excludedNames
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $destinationVar -Recurse -Force
}

# Hash every captured file so the remote restore can prove that no upload or backup
# changed in transit; the manifest itself is deliberately excluded to avoid recursion.
$manifestFiles = Get-ChildItem -LiteralPath $destinationVar -File -Recurse | ForEach-Object {
    [PSCustomObject]@{
        Path = $_.FullName.Substring($DestinationDirectory.Length + 1).Replace('\', '/')
        Length = $_.Length
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$manifest = [PSCustomObject]@{
    FormatVersion = 1
    SourceRoot = $ProjectRoot
    CapturedAt = (Get-Date).ToUniversalTime().ToString('o')
    ExcludedSQLiteFiles = @(
        'bhzd.sqlite',
        'bhzd.sqlite.langgraph',
        'bhzd.sqlite-wal',
        'bhzd.sqlite-shm',
        'bhzd.sqlite.langgraph-wal',
        'bhzd.sqlite.langgraph-shm'
    )
    Files = @($manifestFiles)
}
$manifestJson = $manifest | ConvertTo-Json -Depth 5
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $DestinationDirectory "runtime-manifest.json"), $manifestJson, $utf8NoBom)

Write-Host "Captured runtime state: $DestinationDirectory"
Write-Host "Files: $($manifestFiles.Count); bytes: $(([int64]($manifestFiles | Measure-Object Length -Sum).Sum))"
