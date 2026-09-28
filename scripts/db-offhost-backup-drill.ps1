param(
  [string]$DrillRoot = ".tmp\db-offhost-backup-drill"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$allowedDrillRoot = Join-Path $projectRoot ".tmp\db-offhost-backup-drill"

function Resolve-ProjectPath([string]$PathValue) {
  $candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) {
    $PathValue
  } else {
    Join-Path $projectRoot $PathValue
  }
  return [System.IO.Path]::GetFullPath($candidate)
}

function Assert-UnderRoot([string]$PathValue, [string]$RootValue, [string]$Label) {
  $fullPath = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
  $fullRoot = [System.IO.Path]::GetFullPath($RootValue).TrimEnd('\')
  if ($fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
      $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    return
  }
  throw "$Label must stay under $fullRoot"
}

function ConvertTo-ProjectRelative([string]$PathValue) {
  $fullPath = [System.IO.Path]::GetFullPath($PathValue)
  $fullRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\') + '\'
  if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path must stay under project root: $fullPath"
  }
  return ".\" + $fullPath.Substring($fullRoot.Length)
}

function Get-ProjectPython {
  $candidates = @()
  if ($env:PYTHON) { $candidates += $env:PYTHON }
  $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($pythonCommand) { $candidates += $pythonCommand.Source }
  $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (Test-Path $bundledPython) { $candidates += $bundledPython }
  $repoPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
  if (Test-Path $repoPython) { $candidates += $repoPython }
  $candidates += "python"

  $seen = @{}
  foreach ($candidate in $candidates) {
    if ($seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    try {
      & $candidate -c "import sqlite3, sys; print(sys.executable)" *> $null
      if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    catch {
      continue
    }
  }
  throw "No usable Python interpreter was found for SQLite off-host backup drill."
}

function Get-FileSha256([string]$PathValue) {
  return (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToLowerInvariant()
}

$drillRootPath = Resolve-ProjectPath $DrillRoot
Assert-UnderRoot $drillRootPath $allowedDrillRoot "DrillRoot"

$runId = "run-{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$runRoot = Join-Path $drillRootPath $runId
$sourceDb = Join-Path $runRoot "source.db"
$localBackupDir = Join-Path $runRoot "local-backups"
$offHostDir = Join-Path $runRoot "simulated-offhost"
New-Item -ItemType Directory -Force -Path $runRoot, $localBackupDir, $offHostDir | Out-Null

$python = Get-ProjectPython
$env:PYTHON = $python
$createSource = @"
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as conn:
    conn.execute('create table drill_check (id integer primary key, marker text not null)')
    conn.execute('insert into drill_check (id, marker) values (?, ?)', (1, 'offhost_backup_drill'))
    conn.commit()
"@
& $python -c $createSource $sourceDb
if ($LASTEXITCODE -ne 0) { throw "Failed to create source drill database." }

$backupScript = Join-Path $PSScriptRoot "db-backup.ps1"
$sourceArg = ConvertTo-ProjectRelative $sourceDb
$backupDirArg = ConvertTo-ProjectRelative $localBackupDir
$backupOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupScript -SourceDb $sourceArg -BackupDir $backupDirArg -Label "offhost-drill"
if ($LASTEXITCODE -ne 0) { throw "Backup drill command failed." }
$backupPayload = $backupOutput | Out-String | ConvertFrom-Json
$backupFile = [string]$backupPayload.backup_file
$manifestFile = [string]$backupPayload.manifest_file

if (-not (Test-Path -LiteralPath $backupFile)) { throw "Local backup file was not created: $backupFile" }
if (-not (Test-Path -LiteralPath $manifestFile)) { throw "Local backup manifest was not created: $manifestFile" }

$copiedBackup = Join-Path $offHostDir ([System.IO.Path]::GetFileName($backupFile))
$copiedManifest = Join-Path $offHostDir ([System.IO.Path]::GetFileName($manifestFile))
Copy-Item -LiteralPath $backupFile -Destination $copiedBackup -Force
Copy-Item -LiteralPath $manifestFile -Destination $copiedManifest -Force

$manifest = Get-Content -LiteralPath $copiedManifest -Raw | ConvertFrom-Json
$expectedHash = [string]$manifest.sha256
$localHash = Get-FileSha256 $backupFile
$offHostHash = Get-FileSha256 $copiedBackup
if (-not $expectedHash) { throw "Copied manifest did not contain sha256." }
if ($expectedHash.ToLowerInvariant() -ne $localHash) { throw "Local backup checksum does not match manifest." }
if ($expectedHash.ToLowerInvariant() -ne $offHostHash) { throw "Off-host backup checksum does not match manifest." }

$result = [ordered]@{
  status = "ok"
  run_id = $runId
  source_db = $sourceDb
  local_backup_file = $backupFile
  local_manifest_file = $manifestFile
  offhost_backup_file = $copiedBackup
  offhost_manifest_file = $copiedManifest
  sha256 = $offHostHash
  manifest_integrity = [string]$manifest.sqlite_integrity_check
  copied = $true
  verified = $true
}

Write-Output ($result | ConvertTo-Json -Depth 4)
