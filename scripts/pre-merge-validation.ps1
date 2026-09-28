[CmdletBinding()]
param(
  [switch]$SkipBackend,
  [switch]$SkipAnalysisWorkerSmoke,
  [switch]$SkipClosedLoopParticipation,
  [switch]$SkipStrictAuthMatrix,
  [switch]$SkipBuild,
  [switch]$SkipResponsiveSmoke
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  throw "npm.cmd was not found on PATH."
}

$steps = @()
if (-not $SkipBackend) {
  $steps += [pscustomobject]@{ Name = "backend regression"; Args = @("run", "test:backend") }
}
if (-not $SkipClosedLoopParticipation) {
  $steps += [pscustomobject]@{ Name = "closed-loop participation smoke"; Args = @("run", "smoke:closed-loop-participation") }
}
if (-not $SkipAnalysisWorkerSmoke) {
  $steps += [pscustomobject]@{ Name = "analysis worker smoke"; Args = @("run", "smoke:analysis-worker") }
}
$steps += [pscustomobject]@{ Name = "frontend typecheck"; Args = @("run", "typecheck") }
$steps += [pscustomobject]@{ Name = "frontend lint"; Args = @("run", "lint") }
if (-not $SkipBuild) {
  $steps += [pscustomobject]@{ Name = "frontend build"; Args = @("run", "build") }
}
$steps += [pscustomobject]@{ Name = "frontend static smoke"; Args = @("run", "smoke:frontend") }
if (-not $SkipResponsiveSmoke) {
  $steps += [pscustomobject]@{ Name = "frontend responsive smoke"; Args = @("run", "smoke:frontend:responsive") }
}
if (-not $SkipStrictAuthMatrix) {
  $steps += [pscustomobject]@{ Name = "strict-auth browser matrix"; Args = @("run", "smoke:strict-auth-browser:matrix") }
}

Push-Location $repoRoot
try {
  $startedAt = Get-Date
  foreach ($step in $steps) {
    $stepStartedAt = Get-Date
    Write-Output "pre-merge gate start: $($step.Name)"
    & $npmCommand.Source @($step.Args)
    if ($LASTEXITCODE -ne 0) {
      throw "pre-merge gate failed at $($step.Name) with exit code $LASTEXITCODE"
    }
    $elapsed = [Math]::Round(((Get-Date) - $stepStartedAt).TotalSeconds, 1)
    Write-Output "pre-merge gate ok: $($step.Name) (${elapsed}s)"
  }
  $totalSeconds = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
  Write-Output "ok pre-merge validation ($($steps.Count) steps, ${totalSeconds}s)"
}
finally {
  Pop-Location
}
