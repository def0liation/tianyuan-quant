[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  throw "npm.cmd was not found on PATH."
}

$runId = [guid]::NewGuid().ToString("N").Substring(0, 8)

$signalOpsTests = @(
  "backend\tests\test_auto_paper_trading.py::test_auto_paper_tick_creates_sim_buy_without_manual_intervention",
  "backend\tests\test_auto_paper_routes.py::test_auto_paper_tick_route_forced_and_blocked",
  "-q",
  "--basetemp=.tmp\pytest-module-signalops-$runId"
)

$mfeMaeTests = @(
  "backend\tests\test_mfe_mae_quant_core_chain.py",
  "-q",
  "--basetemp=.tmp\pytest-module-mfe-mae-$runId"
)

$closedLoopTests = @(
  "backend\tests\test_closed_loop_sample.py::test_p2_closed_loop_sample_route_materializes_full_chain",
  "-q",
  "--basetemp=.tmp\pytest-module-closed-loop-$runId"
)

$moduleTests = @(
  "backend\tests\test_data_reliability_routes.py",
  "backend\tests\test_portfolio_store.py",
  "backend\tests\test_backtest_engine.py",
  "backend\tests\test_backtest_signalops_sample.py",
  "backend\tests\test_backtest_store.py",
  "backend\tests\test_research_store.py",
  "backend\tests\test_research_artifact_store.py",
  "backend\tests\test_research_verdict_store.py",
  "backend\tests\test_evaluation.py",
  "backend\tests\test_plugin_store.py",
  "backend\tests\test_plugin_runtime.py",
  "backend\tests\test_observability_routes.py",
  "-q",
  "--basetemp=.tmp\pytest-module-participation-validation-$runId"
)

$steps = @(
  [pscustomobject]@{ Name = "SignalOps auto-paper module chain"; Args = @("run", "test:backend", "--") + $signalOpsTests },
  [pscustomobject]@{ Name = "MFE/MAE Quant Core module chain"; Args = @("run", "test:backend", "--") + $mfeMaeTests },
  [pscustomobject]@{ Name = "closed-loop persistence participation"; Args = @("run", "test:backend", "--") + $closedLoopTests },
  [pscustomobject]@{ Name = "analysis worker participation"; Args = @("run", "smoke:analysis-worker") },
  [pscustomobject]@{ Name = "portfolio/backtest/research/evaluation/plugin/data-reliability modules"; Args = @("run", "test:backend", "--") + $moduleTests }
)

Push-Location $repoRoot
try {
  $startedAt = Get-Date
  foreach ($step in $steps) {
    $stepStartedAt = Get-Date
    Write-Output "module participation validation start: $($step.Name)"
    & $npmCommand.Source @($step.Args)
    if ($LASTEXITCODE -ne 0) {
      throw "module participation validation failed at $($step.Name) with exit code $LASTEXITCODE"
    }
    $elapsed = [Math]::Round(((Get-Date) - $stepStartedAt).TotalSeconds, 1)
    Write-Output "module participation validation ok: $($step.Name) (${elapsed}s)"
  }
  $totalSeconds = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
  Write-Output "ok module participation validation ($($steps.Count) steps, ${totalSeconds}s)"
}
finally {
  Pop-Location
}
