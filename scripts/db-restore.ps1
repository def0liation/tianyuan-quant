param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [string]$TargetDb = ".\storage\tianyuan_quant.db",
  [switch]$DryRun,
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendPath = Join-Path $projectRoot "backend"

function Resolve-ProjectPath([string]$PathValue, [switch]$MustExist) {
  $candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) {
    $PathValue
  } else {
    Join-Path $projectRoot $PathValue
  }
  if ($MustExist) {
    return (Resolve-Path -LiteralPath $candidate).Path
  }
  return [System.IO.Path]::GetFullPath($candidate)
}

function Assert-UnderAllowedRoot([string]$PathValue, [string[]]$AllowedRoots, [string]$Label) {
  $fullPath = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
  foreach ($root in $AllowedRoots) {
    $fullRoot = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
    if ($fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
      return
    }
  }
  throw "$Label must stay under one of: $($AllowedRoots -join ', ')"
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
  throw "No usable Python interpreter was found for SQLite restore."
}

Push-Location $backendPath
try {
  $backupPath = Resolve-ProjectPath $BackupFile -MustExist
  $targetPath = Resolve-ProjectPath $TargetDb
  $allowedBackupRoots = @(
    (Join-Path $projectRoot "deploy\backups\db"),
    (Join-Path $projectRoot "storage"),
    (Join-Path $projectRoot ".tmp\db-backup-restore-drill")
  )
  $allowedTargetRoots = @(
    (Join-Path $projectRoot "deploy\db"),
    (Join-Path $projectRoot "storage"),
    (Join-Path $projectRoot ".tmp\db-backup-restore-drill")
  )
  Assert-UnderAllowedRoot $backupPath $allowedBackupRoots "BackupFile"
  Assert-UnderAllowedRoot $targetPath $allowedTargetRoots "TargetDb"
  $pythonArgs = @("-m", "app.db.backup", "restore", "--backup-file", $backupPath, "--target-db", $targetPath)
  if ($DryRun) { $pythonArgs += "--dry-run" }
  if ($Force) { $pythonArgs += "--force" }
  $python = Get-ProjectPython
  & $python @pythonArgs
}
finally {
  Pop-Location
}
