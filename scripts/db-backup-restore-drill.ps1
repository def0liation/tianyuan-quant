param(
  [string]$DrillRoot = ".tmp\db-backup-restore-drill"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$allowedDrillRoot = Join-Path $projectRoot ".tmp\db-backup-restore-drill"

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
  throw "No usable Python interpreter was found for SQLite backup/restore drill."
}

$drillRootPath = Resolve-ProjectPath $DrillRoot
Assert-UnderRoot $drillRootPath $allowedDrillRoot "DrillRoot"

$runId = "run-{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$runRoot = Join-Path $drillRootPath $runId
$sourceDb = Join-Path $runRoot "source.db"
$targetDb = Join-Path $runRoot "restored.db"
$backupDir = Join-Path $runRoot "backups"
New-Item -ItemType Directory -Force -Path $runRoot, $backupDir | Out-Null

$python = Get-ProjectPython
$env:PYTHON = $python
$createSource = @"
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as conn:
    conn.execute('create table drill_check (id integer primary key, marker text not null)')
    conn.execute('insert into drill_check (id, marker) values (?, ?)', (1, 'backup_restore_drill'))
    conn.commit()
"@
& $python -c $createSource $sourceDb
if ($LASTEXITCODE -ne 0) { throw "Failed to create source drill database." }

$createStaleTarget = @"
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as conn:
    conn.execute('create table drill_check (id integer primary key, marker text not null)')
    conn.execute('insert into drill_check (id, marker) values (?, ?)', (1, 'stale_target'))
    conn.commit()
"@
& $python -c $createStaleTarget $targetDb
if ($LASTEXITCODE -ne 0) { throw "Failed to create stale target drill database." }

$backupScript = Join-Path $PSScriptRoot "db-backup.ps1"
$restoreScript = Join-Path $PSScriptRoot "db-restore.ps1"
$sourceArg = ConvertTo-ProjectRelative $sourceDb
$backupDirArg = ConvertTo-ProjectRelative $backupDir
$targetArg = ConvertTo-ProjectRelative $targetDb

$backupOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backupScript -SourceDb $sourceArg -BackupDir $backupDirArg -Label "drill"
if ($LASTEXITCODE -ne 0) { throw "Backup drill command failed." }
$backupPayload = $backupOutput | Out-String | ConvertFrom-Json
$backupFile = [string]$backupPayload.backup_file

$dryRunOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $restoreScript -BackupFile $backupFile -TargetDb $targetArg -DryRun
if ($LASTEXITCODE -ne 0) { throw "Restore dry-run drill command failed." }
$dryRunPayload = $dryRunOutput | Out-String | ConvertFrom-Json
if (-not $dryRunPayload.dry_run -or $dryRunPayload.restored) {
  throw "Restore dry-run did not report the expected non-restored state."
}

$restoreOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $restoreScript -BackupFile $backupFile -TargetDb $targetArg -Force
if ($LASTEXITCODE -ne 0) { throw "Restore force drill command failed." }
$restorePayload = $restoreOutput | Out-String | ConvertFrom-Json
if (-not $restorePayload.restored) {
  throw "Restore force drill did not report restored=true."
}

$verifyTarget = @"
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as conn:
    marker = conn.execute('select marker from drill_check where id = 1').fetchone()
    integrity = conn.execute('pragma integrity_check').fetchone()

if marker != ('backup_restore_drill',):
    raise SystemExit(f'unexpected restored marker: {marker!r}')
if integrity != ('ok',):
    raise SystemExit(f'unexpected integrity result: {integrity!r}')
"@
& $python -c $verifyTarget $targetDb
if ($LASTEXITCODE -ne 0) { throw "Restored database verification failed." }

$result = [ordered]@{
  status = "ok"
  run_id = $runId
  source_db = $sourceDb
  backup_file = $backupFile
  manifest_file = [string]$backupPayload.manifest_file
  target_db = $targetDb
  dry_run = [bool]$dryRunPayload.dry_run
  restored = [bool]$restorePayload.restored
  integrity = [string]$dryRunPayload.integrity
  marker = "backup_restore_drill"
}

Write-Output ($result | ConvertTo-Json -Depth 4)
