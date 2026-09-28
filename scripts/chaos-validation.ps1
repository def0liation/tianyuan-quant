param(
  [switch]$SkipStrictAuthMatrix,
  [switch]$SkipBackendChaos,
  [int]$FrontendRounds = 4,
  [int]$FrontendConcurrency = 12
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$runId = "$(Get-Date -Format 'yyyyMMddHHmmss')-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$chaosRoot = Join-Path $repoRoot ".tmp\chaos-validation-$runId"
$realDb = Join-Path $repoRoot "storage\tianyuan_quant.db"

function Get-RealDbProjectBackendProcesses {
  $repoPath = [System.IO.Path]::GetFullPath([string]$repoRoot) -replace "/", "\"
  Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $commandLine = [string]$_.CommandLine
      if (-not $commandLine) {
        return $false
      }
      $normalizedCommandLine = $commandLine -replace "/", "\"
      $normalizedCommandLine -like "*$repoPath*" -and
        $normalizedCommandLine -like "*start_uvicorn.py*" -and
        $normalizedCommandLine -notlike "*.tmp\*" -and
        $normalizedCommandLine -notlike "*strict-auth-browser-smoke-*"
    }
}

function Assert-NoRealDbProjectBackendProcess {
  $processes = @(Get-RealDbProjectBackendProcesses)
  if ($processes.Count -eq 0) {
    return
  }
  $descriptions = $processes |
    ForEach-Object { "pid=$($_.ProcessId) command=$($_.CommandLine)" }
  throw "Refusing to start isolated chaos validation while project backend processes may write storage\tianyuan_quant.db: $($descriptions -join '; ')"
}

function Get-FileFingerprint([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    return $null
  }
  $item = Get-Item -LiteralPath $Path
  $stream = [System.IO.File]::Open($item.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
  try {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
      $hashBytes = $sha256.ComputeHash($stream)
      $hash = ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToUpperInvariant()
    } finally {
      $sha256.Dispose()
    }
  } finally {
    $stream.Dispose()
  }
  return @{
    Length = $item.Length
    Sha256 = $hash
  }
}

function Invoke-ChaosStep([string]$Label, [scriptblock]$Command) {
  Write-Output "== chaos step: $Label =="
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "Chaos step failed: $Label (exit $LASTEXITCODE)"
  }
}

function Invoke-Npm([string[]]$Arguments) {
  & npm.cmd @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "npm.cmd $($Arguments -join ' ') failed with exit $LASTEXITCODE"
  }
}

function Assert-RealDbUnchanged {
  if (-not $realDbBefore) {
    return
  }
  $after = Get-FileFingerprint -Path $realDb
  if (-not $after) {
    throw "Refusing to accept chaos validation: storage\tianyuan_quant.db was removed during an isolated chaos run."
  }
  if ($after.Length -ne $realDbBefore.Length -or $after.Sha256 -ne $realDbBefore.Sha256) {
    throw "Refusing to accept chaos validation: storage\tianyuan_quant.db changed during an isolated chaos run."
  }
}

Assert-NoRealDbProjectBackendProcess
$realDbBefore = Get-FileFingerprint -Path $realDb
New-Item -ItemType Directory -Path $chaosRoot -Force | Out-Null

try {
  Invoke-ChaosStep "frontend build" {
    Invoke-Npm @("run", "build")
  }

  Invoke-ChaosStep "frontend route pressure" {
    $env:CHAOS_FRONTEND_ROUNDS = [string]$FrontendRounds
    $env:CHAOS_FRONTEND_CONCURRENCY = [string]$FrontendConcurrency
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) {
      $node = Get-Command node -ErrorAction SilentlyContinue
    }
    if (-not $node) {
      throw "node was not found on PATH."
    }
    & $node.Source (Join-Path $repoRoot "scripts\chaos-frontend-pressure.mjs")
  }

  if (-not $SkipBackendChaos) {
    Invoke-ChaosStep "backend destructive boundary tests" {
      $basetemp = Join-Path $chaosRoot "pytest-backend"
      Invoke-Npm @(
        "run", "test:backend", "--",
        "backend\tests\test_http_auth.py",
        "backend\tests\test_stream_auth.py",
        "backend\tests\test_analysis_job_sqlite.py",
        "backend\tests\test_analysis_job_reconciliation.py",
        "backend\tests\test_portfolio_store.py",
        "backend\tests\test_auto_paper_routes.py::test_auto_paper_tick_route_forced_and_blocked",
        "-q",
        "--basetemp=$basetemp"
      )
    }
  }

  if (-not $SkipStrictAuthMatrix) {
    Invoke-ChaosStep "strict-auth browser matrix" {
      Invoke-Npm @("run", "smoke:strict-auth-browser:matrix")
    }
  }

  Assert-RealDbUnchanged
  Write-Output "ok isolated chaos validation run_id=$runId root=$chaosRoot"
} finally {
  Assert-RealDbUnchanged
}
