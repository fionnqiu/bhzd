[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)]
    [string]$DestinationDirectory,
    [switch]$Archive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$DestinationDirectory = [System.IO.Path]::GetFullPath($DestinationDirectory)
if ($DestinationDirectory.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "DestinationDirectory must be outside the project directory to avoid copying a package into itself."
}
New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$packageRoot = Join-Path $DestinationDirectory "bhzd-transfer-$stamp"
New-Item -ItemType Directory -Path $packageRoot -ErrorAction Stop | Out-Null

# Runtime dependencies and local caches are intentionally excluded because lock files rebuild them on the new PC.
$excludedDirectoryNames = @(".git", ".venv", "node_modules", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "test-results", "playwright-report", ".playwright-mcp", ".worktrees", ".codex")
$excludedFileNames = @(".env", ".env.local")
Get-ChildItem -LiteralPath $ProjectRoot -Force | Where-Object {
    $_.FullName -ne $packageRoot -and $_.Name -notin $excludedDirectoryNames -and $_.Name -notin $excludedFileNames
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $packageRoot -Recurse -Force
}

# Replace a potentially live SQLite file with a consistent API-level backup in the transfer package.
$copiedDatabasePath = Join-Path $packageRoot "var\bhzd.sqlite"
if (Test-Path -LiteralPath $copiedDatabasePath) {
    Remove-Item -LiteralPath $copiedDatabasePath -Force
}
foreach ($sidecarSuffix in @("-wal", "-shm")) {
    $copiedSidecarPath = "$copiedDatabasePath$sidecarSuffix"
    if (Test-Path -LiteralPath $copiedSidecarPath) {
        # The fresh backup below has already incorporated committed WAL data; copied sidecars are stale.
        Remove-Item -LiteralPath $copiedSidecarPath -Force
    }
}
& (Join-Path $ProjectRoot "deploy\Backup-Database.ps1") -ProjectRoot $ProjectRoot -DestinationPath $copiedDatabasePath
if ($LASTEXITCODE -ne 0) {
    throw "The transfer database backup failed."
}

# A manifest lets the receiving operator detect an incomplete file copy before restoration.
$manifest = Get-ChildItem -LiteralPath $packageRoot -File -Recurse | ForEach-Object {
    [PSCustomObject]@{
        Path = $_.FullName.Substring($packageRoot.Length + 1)
        Length = $_.Length
        SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $packageRoot "transfer-manifest.json") -Encoding utf8

if ($Archive) {
    $archivePath = "$packageRoot.zip"
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $archivePath -CompressionLevel Optimal
    Write-Host "Created transfer archive: $archivePath"
}
else {
    Write-Host "Created transfer directory: $packageRoot"
}
Write-Warning "The transfer package deliberately excludes .env and .env.local. Transfer BHZD_CONFIG_ENCRYPTION_KEY separately through an approved secret channel."
