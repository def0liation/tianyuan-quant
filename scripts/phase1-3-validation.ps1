[CmdletBinding()]
param(
  [switch]$SkipBuild,
  [switch]$SkipBrowserSmoke
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  throw "npm.cmd was not found on PATH."
}

$steps = @(
  [pscustomobject]@{ Name = "baseline audit"; Args = @("run", "audit:baseline") },
  [pscustomobject]@{ Name = "module participation validation"; Args = @("run", "validate:module-participation") },
  [pscustomobject]@{ Name = "frontend typecheck"; Args = @("run", "typecheck") },
  [pscustomobject]@{ Name = "frontend lint"; Args = @("run", "lint") }
)

if (-not $SkipBuild) {
  $steps += [pscustomobject]@{ Name = "frontend build"; Args = @("run", "build") }
}
$steps += [pscustomobject]@{ Name = "frontend static smoke"; Args = @("run", "smoke:frontend") }
if (-not $SkipBrowserSmoke) {
  $steps += [pscustomobject]@{ Name = "research closure browser smoke"; Args = @("run", "smoke:research-closure:browser") }
}

Push-Location $repoRoot
try {
  $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
  if ($gitCommand) {
    Write-Output "phase 1-3 validation git status:"
    & $gitCommand.Source status --short
  }

  $startedAt = Get-Date
  foreach ($step in $steps) {
    $stepStartedAt = Get-Date
    Write-Output "phase 1-3 validation start: $($step.Name)"
    & $npmCommand.Source @($step.Args)
    if ($LASTEXITCODE -ne 0) {
      throw "phase 1-3 validation failed at $($step.Name) with exit code $LASTEXITCODE"
    }
    $elapsed = [Math]::Round(((Get-Date) - $stepStartedAt).TotalSeconds, 1)
    Write-Output "phase 1-3 validation ok: $($step.Name) (${elapsed}s)"
  }
  $totalSeconds = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
  Write-Output "ok phase 1-3 validation ($($steps.Count) steps, ${totalSeconds}s)"
}
finally {
  Pop-Location
}
