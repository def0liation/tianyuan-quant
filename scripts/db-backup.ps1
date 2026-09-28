param(
  [string]$SourceDb = ".\storage\tianyuan_quant.db",
  [string]$BackupDir = ".\deploy\backups\db",
  [string]$Label = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendPath = Join-Path $projectRoot "backend"

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
  throw "No usable Python interpreter was found for SQLite backup."
}

Push-Location $backendPath
try {
  $sourcePath = Resolve-Path (Join-Path $projectRoot $SourceDb)
  $backupPath = Join-Path $projectRoot $BackupDir
  $python = Get-ProjectPython
  & $python -m app.db.backup backup --source-db $sourcePath --backup-dir $backupPath --label $Label
}
finally {
  Pop-Location
}
