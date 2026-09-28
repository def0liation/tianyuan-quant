[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  throw "npm.cmd was not found on PATH."
}
$powershellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue
if (-not $powershellCommand) {
  throw "powershell.exe was not found on PATH."
}

$runId = [guid]::NewGuid().ToString("N").Substring(0, 8)
$workerTimeoutSeconds = 120
$workerTimeoutOverride = [string]$env:TIANYUAN_ANALYSIS_WORKER_CLI_TIMEOUT_SECONDS
if (-not [string]::IsNullOrWhiteSpace($workerTimeoutOverride)) {
  $parsedTimeout = 0
  if (-not [int]::TryParse($workerTimeoutOverride, [ref]$parsedTimeout) -or $parsedTimeout -le 0) {
    throw "TIANYUAN_ANALYSIS_WORKER_CLI_TIMEOUT_SECONDS must be a positive integer."
  }
  $workerTimeoutSeconds = $parsedTimeout
}
$workerTimeoutMs = $workerTimeoutSeconds * 1000
$previousSqliteJobTimeout = $env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS
$env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS = "2"

function Stop-ProcessTree([int]$ProcessId) {
  $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ParentProcessId -eq $ProcessId } |
    Select-Object -ExpandProperty ProcessId
  foreach ($childId in $children) {
    Stop-ProcessTree -ProcessId ([int]$childId)
  }
  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
  Wait-Process -Id $ProcessId -Timeout 5 -ErrorAction SilentlyContinue
}

$workerTests = @(
  "backend\tests\test_analysis_lifecycle_core_services.py::test_core_prepare_start_worker_queue_preserves_simulation_boundary",
  "backend\tests\test_analysis_workflow.py::test_worker_mode_start_queues_without_background_task",
  "backend\tests\test_analysis_workflow.py::test_worker_once_claims_queued_run_and_executes",
  "backend\tests\test_analysis_workflow.py::test_worker_heartbeat_updates_while_run_is_executing",
  "backend\tests\test_analysis_workflow.py::test_worker_running_cancel_request_is_observed_by_heartbeat",
  "backend\tests\test_analysis_workflow.py::test_cancel_running_worker_run_keeps_request_for_worker",
  "backend\tests\test_analysis_workflow.py::test_worker_cancel_request_cannot_be_overwritten_by_late_completion",
  "backend\tests\test_analysis_job_sqlite.py::test_claim_next_job_respects_concurrency_group_limit",
  "backend\tests\test_analysis_job_sqlite.py::test_worker_heartbeat_refreshes_lease_metadata",
  "backend\tests\test_analysis_job_sqlite.py::test_worker_heartbeat_rejects_non_owner",
  "backend\tests\test_analysis_job_sqlite.py::test_terminal_update_rejects_non_owner_and_preserves_running_job",
  "backend\tests\test_analysis_job_sqlite.py::test_claim_next_job_skips_cancel_requested",
  "backend\tests\test_analysis_job_sqlite.py::test_stale_reconciliation_updates_sqlite_only_job",
  "backend\tests\test_analysis_job_reconciliation.py::test_jobs_list_reconciles_stale_pending_run_and_job",
  "backend\tests\test_analysis_job_reconciliation.py::test_job_attempts_endpoint_exposes_retry_history",
  "-q",
  "--basetemp=.tmp\pytest-analysis-worker-smoke-$runId"
)

Push-Location $repoRoot
try {
  & $npmCommand.Source @("run", "test:backend", "--") $workerTests
  if ($LASTEXITCODE -ne 0) {
    throw "analysis worker smoke pytest coverage failed with exit code $LASTEXITCODE"
  }

  $workerScript = Join-Path $repoRoot "scripts\analysis-worker.ps1"
  $workerArgs = @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $workerScript,
    "-Once",
    "-DatabaseFile",
    ".tmp\analysis-worker-cli-smoke\$runId\analysis-worker.db",
    "-JobStorageFile",
    ".tmp\analysis-worker-cli-smoke\$runId\analysis_jobs.json"
  )
  $workerProcess = Start-Process -FilePath $powershellCommand.Source -ArgumentList $workerArgs -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
  if (-not $workerProcess.WaitForExit($workerTimeoutMs)) {
    Stop-ProcessTree -ProcessId $workerProcess.Id
    throw "analysis worker CLI smoke timed out after $workerTimeoutSeconds seconds"
  }
  $workerProcess.Refresh()
  $workerExitCode = $workerProcess.ExitCode
  if ($workerExitCode -ne 0) {
    throw "analysis worker CLI smoke failed with exit code $workerExitCode"
  }

  Write-Output "ok analysis worker smoke"
}
finally {
  if ($null -eq $previousSqliteJobTimeout) {
    Remove-Item Env:\TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS -ErrorAction SilentlyContinue
  } else {
    $env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS = $previousSqliteJobTimeout
  }
  Pop-Location
}
