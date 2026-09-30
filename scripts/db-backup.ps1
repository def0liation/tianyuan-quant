param(
  [string]$SourceDb = ".\storage\tianyuan_quant.db",
  [string]$BackupDir = ".\deploy\backups\db",
  [string]$Label = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backendPath = Join-Path $projectRoot "backend"

function Resolve-ProjectPath([string]$PathValue, [switch]$MustExist) {
  $candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) { $PathValue } else { Join-Path $projectRoot $PathValue }
  if ($MustExist) { return (Resolve-Path -LiteralPath $candidate).Path }
  return [System.IO.Path]::GetFullPath($candidate)
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
  throw "No usable Python interpreter was found for SQLite backup."
}

Push-Location $backendPath
try {
  $sourcePath = Resolve-ProjectPath $SourceDb -MustExist
  $backupPath = Resolve-ProjectPath $BackupDir
  $python = Get-ProjectPython
  $pythonArgs = @("-m", "app.db.backup", "backup", "--source-db", $sourcePath, "--backup-dir", $backupPath)
  if (-not [string]::IsNullOrWhiteSpace($Label)) { $pythonArgs += @("--label", $Label) }
  & $python @pythonArgs
  if ($LASTEXITCODE -ne 0) { throw "SQLite backup helper failed with exit code $LASTEXITCODE." }
}
finally {
  Pop-Location
}
