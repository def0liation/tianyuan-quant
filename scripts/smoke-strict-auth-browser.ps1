param(
  [int]$BackendPortStart = 8866,
  [int]$FrontendPortStart = 5896,
  [string]$Scenario = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$tmpDir = Join-Path $repoRoot ".tmp"
$logDir = Join-Path $repoRoot ".logs"
$backendProcess = $null
$frontendProcess = $null
$script:smokeStep = "initializing"

function Test-PortAvailable([int]$Port) {
  $listener = $null
  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
    $listener.Start()
    return $true
  } catch {
    return $false
  } finally {
    if ($listener) {
      $listener.Stop()
    }
  }
}

function Find-FreePort([int]$StartPort) {
  for ($port = $StartPort; $port -lt ($StartPort + 100); $port++) {
    if (Test-PortAvailable $port) {
      return $port
    }
  }
  throw "No free port found from $StartPort."
}

function Resolve-PositiveIntEnv([string]$Name, [int]$Default) {
  $value = [string][System.Environment]::GetEnvironmentVariable($Name, "Process")
  if ([string]::IsNullOrWhiteSpace($value)) {
    return $Default
  }
  $parsed = 0
  if ([int]::TryParse($value, [ref]$parsed) -and $parsed -gt 0) {
    return $parsed
  }
  throw "$Name must be a positive integer, got '$value'."
}

function Wait-ForJson([string]$Uri, [string]$Label, $Process = $null, [int]$MaxAttempts = 60) {
  for ($i = 0; $i -lt $MaxAttempts; $i++) {
    if ($Process -and $Process.HasExited) {
      throw "$Label process exited before readiness."
    }
    try {
      return Invoke-RestMethod -Method Get -Uri $Uri -TimeoutSec 1
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "$Label did not become ready at $Uri"
}

function Wait-ForHtml([string]$Uri, [string]$Label, $Process = $null) {
  for ($i = 0; $i -lt 60; $i++) {
    if ($Process -and $Process.HasExited) {
      throw "$Label process exited before readiness."
    }
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 1
      if ($response.StatusCode -eq 200 -and $response.Content -match 'id="root"') {
        return $response
      }
    } catch {
      Start-Sleep -Milliseconds 500
    }
  }
  throw "$Label did not become ready at $Uri"
}

function Quote-ProcessArgument([string]$Value) {
  if ($Value -match '[\s"]') {
    return '"' + ($Value -replace '"', '\"') + '"'
  }
  return $Value
}

function Remove-SmokeDb([string]$Path, [string]$Root) {
  $rootFull = [System.IO.Path]::GetFullPath($Root)
  foreach ($candidate in @($Path, "$Path-shm", "$Path-wal")) {
    $full = [System.IO.Path]::GetFullPath($candidate)
    if (-not $full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove smoke DB path outside ${rootFull}: $full"
    }
    if (Test-Path -LiteralPath $full) {
      Remove-Item -LiteralPath $full -Force
    }
  }
}

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

function Write-LogTail([string]$Label, [string]$Path) {
  Write-Output "--- $Label ---"
  if (Test-Path -LiteralPath $Path) {
    Get-Content -LiteralPath $Path -Tail 80 -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
  } else {
    Write-Output "missing: $Path"
  }
}

function Write-SmokeDiagnostics([string]$Message) {
  Write-Output "=== strict-auth browser smoke diagnostics ==="
  Write-Output "failure: $Message"
  Write-Output "step: $script:smokeStep"
  Write-Output "backend_url: $backendUrl"
  Write-Output "frontend_url: $frontendUrl"
  if ($backendProcess) {
    Write-Output "backend_pid: $($backendProcess.Id) exited=$($backendProcess.HasExited)"
  }
  if ($frontendProcess) {
    Write-Output "frontend_pid: $($frontendProcess.Id) exited=$($frontendProcess.HasExited)"
  }
  if ($backendHealthAttempts) {
    Write-Output "backend_health_attempts: $backendHealthAttempts"
  }
  if ($uvCacheDir) {
    Write-Output "uv_cache_dir: $uvCacheDir"
  }
  if ($requirements) {
    Write-Output "backend_requirements: $requirements"
  }
  Write-LogTail "backend stdout tail" $backendOut
  Write-LogTail "backend stderr tail" $backendErr
  Write-LogTail "frontend stdout tail" $frontendOut
  Write-LogTail "frontend stderr tail" $frontendErr
  Write-Output "=== end diagnostics ==="
}

function Normalize-ProcessPathEnvironment {
  $processEnv = [System.Environment]::GetEnvironmentVariables("Process")
  $pathValue = $null
  foreach ($key in @("Path", "PATH", "path")) {
    if ($processEnv.Contains($key) -and $processEnv[$key]) {
      $pathValue = [string]$processEnv[$key]
      break
    }
  }
  $pathKeys = @()
  foreach ($key in $processEnv.Keys) {
    if ([string]::Equals([string]$key, "PATH", [System.StringComparison]::OrdinalIgnoreCase)) {
      $pathKeys += [string]$key
    }
  }
  foreach ($key in $pathKeys) {
    [System.Environment]::SetEnvironmentVariable($key, $null, "Process")
  }
  if ($pathValue) {
    [System.Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
  }
}

New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
Normalize-ProcessPathEnvironment

$tmpFull = [System.IO.Path]::GetFullPath($tmpDir)
$smokeRunId = "$(Get-Date -Format 'yyyyMMddHHmmss')-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$smokeDb = [System.IO.Path]::GetFullPath((Join-Path $tmpDir "strict-auth-browser-smoke-$smokeRunId.db"))
$smokeDbUrlPath = $smokeDb -replace "\\", "/"
$strictAuthToken = "strict-auth-browser-smoke-token-$smokeRunId"
Remove-SmokeDb -Path $smokeDb -Root $tmpFull

$uv = Get-Command uv.exe -ErrorAction SilentlyContinue
if (-not $uv) {
  throw "uv.exe was not found on PATH."
}

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCommand) {
  $pythonExe = $pythonCommand.Source
} else {
  $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
  if (-not (Test-Path -LiteralPath $bundledPython)) {
    throw "No usable Python interpreter was found."
  }
  $pythonExe = $bundledPython
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $node) {
  $node = Get-Command node -ErrorAction SilentlyContinue
}
if (-not $node) {
  throw "node was not found on PATH."
}

$frontendDistIndex = Join-Path $frontendRoot "dist\index.html"
if (-not (Test-Path -LiteralPath $frontendDistIndex)) {
  throw "Frontend dist was not found. Run `npm.cmd run build` before smoke:strict-auth-browser."
}

$backendPort = Find-FreePort $BackendPortStart
$frontendPort = Find-FreePort $FrontendPortStart
$backendUrl = "http://127.0.0.1:$backendPort"
$frontendUrl = "http://127.0.0.1:$frontendPort"
$backendHealthAttempts = Resolve-PositiveIntEnv "TIANYUAN_STRICT_AUTH_BACKEND_HEALTH_ATTEMPTS" 360

$env:TIANYUAN_QUANT_DB_URL = "sqlite+aiosqlite:///$smokeDbUrlPath"
$env:TIANYUAN_ANALYSIS_JOBS_FILE = Join-Path $tmpDir "strict-auth-analysis-jobs-$smokeRunId.json"
$env:TIANYUAN_SKIP_ALEMBIC = "1"
$env:TIANYUAN_FORCE_MOCK_MARKET_DATA = "1"
$env:TIANYUAN_MARKET_DATA_MODE = "mock"
$env:API_AUTH_MODE = "strict"
$env:API_ADMIN_TOKEN = $strictAuthToken
$uvCacheDirOverride = [string]$env:TIANYUAN_UV_CACHE_DIR
if ([string]::IsNullOrWhiteSpace($uvCacheDirOverride)) {
  $uvCacheDir = Join-Path $repoRoot ".uv-cache"
} elseif ([System.IO.Path]::IsPathRooted($uvCacheDirOverride)) {
  $uvCacheDir = $uvCacheDirOverride
} else {
  $uvCacheDir = Join-Path $repoRoot $uvCacheDirOverride
}
New-Item -ItemType Directory -Path $uvCacheDir -Force | Out-Null
$env:UV_CACHE_DIR = $uvCacheDir
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$backendRoot;$env:PYTHONPATH" } else { $backendRoot }
$env:BACKEND_HOST = "127.0.0.1"
$env:BACKEND_PORT = [string]$backendPort
$env:ANALYSIS_EXECUTION_MODE = "worker"
$env:TIANYUAN_PLUGIN_ARTIFACT_DIR = Join-Path $tmpDir "strict-auth-plugin-artifacts-$smokeRunId"
$env:TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR = Join-Path $tmpDir "strict-auth-plugin-external-scan-$smokeRunId"
$env:TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED = "1"
$env:BACKTEST_PARAMETER_SCAN_HANDOFF_DIR = Join-Path $tmpDir "strict-auth-backtest-parameter-scan-handoff-$smokeRunId"
$env:PRODUCTION_ALERT_OUTBOX_FILE = Join-Path $tmpDir "strict-auth-production-alerts-$smokeRunId.jsonl"
$env:PRODUCTION_ALERT_EXPORT_HANDOFF_DIR = Join-Path $tmpDir "strict-auth-production-alert-handoff-$smokeRunId"
$env:PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE = Join-Path $tmpDir "strict-auth-production-alert-rule-provider-acceptance-$smokeRunId.json"
$env:OPS_LOG_EXPORT_HANDOFF_DIR = Join-Path $tmpDir "strict-auth-ops-log-handoff-$smokeRunId"
$env:TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE = Join-Path $tmpDir "strict-auth-analysis-external-queue-status-$smokeRunId.json"
$analysisExternalQueueStatus = @{
  schema = "analysis_job_external_queue_status_v1"
  status = "READY"
  reported_at = (Get-Date).ToUniversalTime().ToString("o")
  source = "strict-auth-smoke-sidecar"
  provider = "local-smoke-queue"
  queue_name = "analysis"
  lease_backend = "local-smoke-lease"
  claim_backend = "local-smoke-claim"
  claim_status = "READY"
  idempotency_scope = "run_id+attempt"
  audit_stream = "analysis-job-audit"
  dead_letter_queue = "analysis-dlq"
  dead_letter_count = 0
  visibility_timeout_seconds = 120
  lease_renewal_status = "READY"
  worker_pool = "strict-auth-worker"
  active_workers = 1
  pending_jobs = 0
  running_jobs = 0
  oldest_pending_age_seconds = 0
  message = "strict-auth sidecar ready"
  issues = @()
} | ConvertTo-Json -Depth 4
Set-Content -LiteralPath $env:TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE -Value $analysisExternalQueueStatus -Encoding UTF8

$productionAlertRuleProviderAcceptance = @{
  schema = "production_alert_rule_provider_acceptance_v1"
  status = "ACCEPTED"
  reported_at = (Get-Date).ToUniversalTime().ToString("o")
  last_synced_at = (Get-Date).ToUniversalTime().ToString("o")
  source = "strict-auth-alert-rule-provider"
  provider = "alertmanager"
  policy_id = "builtin_default"
  provider_policy_id = "strict-auth-default-policy"
  rules_accepted = 3
  rules_total = 3
  accepted_rule_ids = @("critical_ops_page", "warning_ops_notify", "info_record_only")
  routing_key = "ops-critical"
  message = "accepted token=unit-secret"
  issues = @()
} | ConvertTo-Json -Depth 4
Set-Content -LiteralPath $env:PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE -Value $productionAlertRuleProviderAcceptance -Encoding UTF8

$backendOut = Join-Path $logDir "strict-auth-browser-backend.out.log"
$backendErr = Join-Path $logDir "strict-auth-browser-backend.err.log"
$frontendOut = Join-Path $logDir "strict-auth-browser-frontend.out.log"
$frontendErr = Join-Path $logDir "strict-auth-browser-frontend.err.log"

try {
  $script:smokeStep = "starting backend"
  $smokeRequirements = Join-Path $backendRoot "requirements-smoke.txt"
  $requirements = if (Test-Path -LiteralPath $smokeRequirements) { $smokeRequirements } else { Join-Path $backendRoot "requirements.txt" }
  $backendArgValues = @("run", "--no-project")
  $backendArgValues += @(
    "--no-python-downloads",
    "--python",
    $pythonExe,
    "--with-requirements",
    $requirements,
    "python",
    "start_uvicorn.py",
    "--host",
    "127.0.0.1",
    "--port",
    "$backendPort",
    "--no-reload"
  )
  $backendArgs = $backendArgValues | ForEach-Object { Quote-ProcessArgument $_ }
  $backendProcess = Start-Process `
    -FilePath $uv.Source `
    -ArgumentList ($backendArgs -join " ") `
    -WorkingDirectory $backendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru

  $script:smokeStep = "waiting for backend health"
  Wait-ForJson "$backendUrl/api/health" "backend health" $backendProcess $backendHealthAttempts | Out-Null
  Write-Output "ok strict-auth backend $backendUrl"

  $script:smokeStep = "starting frontend preview"
  $env:HOST = "127.0.0.1"
  $env:PORT = [string]$frontendPort
  $env:API_PROXY_TARGET = $backendUrl
  $frontendProcess = Start-Process `
    -FilePath $node.Source `
    -ArgumentList @("preview-dist.cjs") `
    -WorkingDirectory $frontendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $frontendOut `
    -RedirectStandardError $frontendErr `
    -PassThru

  $script:smokeStep = "waiting for frontend"
  Wait-ForHtml "$frontendUrl/backend" "frontend backend route" $frontendProcess | Out-Null
  Write-Output "ok strict-auth frontend $frontendUrl"

  $script:smokeStep = "running browser scenario"
  $env:STRICT_AUTH_FRONTEND_URL = $frontendUrl
  $env:STRICT_AUTH_BACKEND_URL = $backendUrl
  $env:STRICT_AUTH_TOKEN = $strictAuthToken
  if ($Scenario) {
    $env:STRICT_AUTH_BROWSER_SCENARIO = $Scenario
  } elseif (-not $env:STRICT_AUTH_BROWSER_SCENARIO) {
    $env:STRICT_AUTH_BROWSER_SCENARIO = "all"
  }
  Write-Output "ok strict-auth scenario $env:STRICT_AUTH_BROWSER_SCENARIO"
  & $node.Source (Join-Path $PSScriptRoot "smoke-strict-auth-browser.mjs")
  if ($LASTEXITCODE -ne 0) {
    throw "strict-auth browser scenario failed with exit code $LASTEXITCODE"
  }
} catch {
  Write-SmokeDiagnostics $_.Exception.Message
  throw
} finally {
  if ($frontendProcess) {
    Stop-ProcessTree -ProcessId $frontendProcess.Id
  }
  if ($backendProcess) {
    Stop-ProcessTree -ProcessId $backendProcess.Id
  }
}
