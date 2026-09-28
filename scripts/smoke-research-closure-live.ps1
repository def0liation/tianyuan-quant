param(
  [int]$BackendPortStart = 8766,
  [int]$FrontendPortStart = 5796,
  [switch]$BrowserSmoke
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$tmpDir = Join-Path $repoRoot ".tmp"
$logDir = Join-Path $repoRoot ".logs"
$backendProcess = $null
$frontendProcess = $null
$createdRunId = ""
$script:smokeStep = "initializing"
$script:lastApiRequest = ""
$script:lastApiResponse = ""

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

function Wait-ForJson([string]$Uri, [string]$Label, $Process = $null) {
  for ($i = 0; $i -lt 60; $i++) {
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

function Invoke-SmokeJson([string]$Method, [string]$Uri, [object]$Body = $null) {
  $script:lastApiRequest = "$Method $Uri"
  $params = @{
    Method = $Method
    Uri = $Uri
    TimeoutSec = 30
    Headers = @{
      "X-Operator-ID" = "research-closure-smoke"
      "X-Operator-Role" = "admin"
    }
  }
  if ($null -ne $Body) {
    $params["ContentType"] = "application/json"
    $params["Body"] = ($Body | ConvertTo-Json -Depth 12)
  }
  try {
    $response = Invoke-RestMethod @params
    $script:lastApiResponse = $response | ConvertTo-Json -Depth 12 -Compress
    return $response
  } catch {
    $script:lastApiResponse = $_.Exception.Message
    throw
  }
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

New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$tmpFull = [System.IO.Path]::GetFullPath($tmpDir)
$smokeRunId = "$(Get-Date -Format 'yyyyMMddHHmmss')-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$smokeDb = [System.IO.Path]::GetFullPath((Join-Path $tmpDir "research-closure-smoke-$smokeRunId.db"))
$viteCacheDir = [System.IO.Path]::GetFullPath((Join-Path $frontendRoot ".vite-smoke-$smokeRunId"))
$uvCacheDir = if ($env:TIANYUAN_UV_CACHE_DIR) {
  [System.IO.Path]::GetFullPath($env:TIANYUAN_UV_CACHE_DIR)
} else {
  [System.IO.Path]::GetFullPath((Join-Path $repoRoot ".uv-cache"))
}
New-Item -ItemType Directory -Path $uvCacheDir -Force | Out-Null
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

$backendPort = Find-FreePort $BackendPortStart
$frontendPort = Find-FreePort $FrontendPortStart
$backendUrl = "http://127.0.0.1:$backendPort"
$frontendUrl = "http://127.0.0.1:$frontendPort"
$smokeDbUrlPath = $smokeDb -replace "\\", "/"

$env:TIANYUAN_QUANT_DB_URL = "sqlite+aiosqlite:///$smokeDbUrlPath"
$env:TIANYUAN_SKIP_ALEMBIC = "1"
$env:TIANYUAN_FORCE_MOCK_MARKET_DATA = "1"
$env:TIANYUAN_MARKET_DATA_MODE = "mock"
$env:API_AUTH_MODE = "off"
$env:UV_CACHE_DIR = $uvCacheDir
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$backendRoot;$env:PYTHONPATH" } else { $backendRoot }
$env:BACKEND_HOST = "127.0.0.1"
$env:BACKEND_PORT = [string]$backendPort
if ($BrowserSmoke) {
  $env:ANALYSIS_EXECUTION_MODE = "worker"
}

$backendOut = Join-Path $logDir "research-closure-backend.out.log"
$backendErr = Join-Path $logDir "research-closure-backend.err.log"
$frontendOut = Join-Path $logDir "research-closure-frontend.out.log"
$frontendErr = Join-Path $logDir "research-closure-frontend.err.log"

function Write-LogTail([string]$Label, [string]$Path) {
  Write-Output "--- $Label ---"
  if (Test-Path -LiteralPath $Path) {
    Get-Content -LiteralPath $Path -Tail 80 -ErrorAction SilentlyContinue | ForEach-Object { Write-Output $_ }
  } else {
    Write-Output "missing: $Path"
  }
}

function Write-SmokeDiagnostics([string]$Message) {
  Write-Output "=== research closure smoke diagnostics ==="
  Write-Output "failure: $Message"
  Write-Output "step: $script:smokeStep"
  Write-Output "backend_url: $backendUrl"
  Write-Output "frontend_url: $frontendUrl"
  Write-Output "smoke_db: $smokeDb"
  if ($backendProcess) {
    Write-Output "backend_pid: $($backendProcess.Id) exited=$($backendProcess.HasExited)"
  }
  if ($frontendProcess) {
    Write-Output "frontend_pid: $($frontendProcess.Id) exited=$($frontendProcess.HasExited)"
  }
  Write-Output "last_api_request: $script:lastApiRequest"
  Write-Output "last_api_response: $script:lastApiResponse"
  Write-LogTail "backend stdout tail" $backendOut
  Write-LogTail "backend stderr tail" $backendErr
  Write-LogTail "frontend stdout tail" $frontendOut
  Write-LogTail "frontend stderr tail" $frontendErr
  Write-Output "=== end diagnostics ==="
}

function Get-SmokeSqliteCount([string]$TableName) {
  $code = "import sqlite3, sys; db=sys.argv[1]; table=sys.argv[2]; conn=sqlite3.connect(db); print(conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]); conn.close()"
  $value = & $pythonExe -c $code $smokeDb $TableName
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to read SQLite smoke count for $TableName"
  }
  return [int]($value | Select-Object -Last 1)
}

try {
  $script:smokeStep = "starting backend"
  $requirements = Join-Path $backendRoot "requirements.txt"
  $backendArgValues = @("run")
  if (Test-Path (Join-Path $backendRoot "pyproject.toml")) {
    $backendArgValues += "--no-project"
  }
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
  Wait-ForJson "$backendUrl/api/health" "backend health" $backendProcess | Out-Null
  $script:smokeStep = "waiting for research summary"
  Wait-ForJson "$backendUrl/api/research/summary" "research summary" $backendProcess | Out-Null
  Write-Output "ok backend $backendUrl"

  $script:smokeStep = "starting frontend"
  if ($BrowserSmoke) {
    $frontendDistIndex = Join-Path $frontendRoot "dist\index.html"
    if (-not (Test-Path -LiteralPath $frontendDistIndex)) {
      throw "Frontend dist was not found. Run `npm.cmd run build` before smoke:research-closure:browser."
    }

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
  } else {
    $env:VITE_API_PROXY_TARGET = $backendUrl
    $env:VITE_CACHE_DIR = $viteCacheDir
    $env:HOST = "127.0.0.1"
    $env:FRONTEND_PORT = [string]$frontendPort
    $frontendProcess = Start-Process `
      -FilePath $node.Source `
      -ArgumentList @("start-vite-dev.mjs", "--host", "127.0.0.1", "--port", "$frontendPort") `
      -WorkingDirectory $frontendRoot `
      -WindowStyle Hidden `
      -RedirectStandardOutput $frontendOut `
      -RedirectStandardError $frontendErr `
      -PassThru
  }

  foreach ($route in @("/research-lab/research", "/research-lab/backtest", "/bottom-research", "/quant-engine")) {
    $script:smokeStep = "checking frontend route $route"
    Wait-ForHtml "$frontendUrl$route" "frontend $route" $frontendProcess | Out-Null
    Write-Output "ok frontend $route"
  }

  $script:smokeStep = "creating research loop"
  $loop = Invoke-SmokeJson "Post" "$backendUrl/api/research/loops" @{
    title = "Smoke MFE/MAE Path Research Closure"
    objective = "Verify MFE/MAE Path Research retry warnings without manual browser checks."
    hypothesis = "An unstarted MFE/MAE Path Research run should retry into a warning, not a 500."
    target_modules = @("mfe_mae_path_research", "research_lab")
  }
  $iterationId = [string]$loop.iterations[0].iteration_id
  if (-not $iterationId) {
    throw "Research loop response did not include an iteration_id."
  }

  $script:smokeStep = "creating research run"
  $start = Invoke-SmokeJson "Post" "$backendUrl/api/research/iterations/$iterationId/start-run" @{
    symbol = "SMOKE001.SZ"
    task_type = "mfe_mae_path_research"
    run_mode = "STANDARD_MODE"
    auto_start = $false
    bottom_research_config = @{
      repair_probability_threshold = 0.25
    }
  }
  $createdRunId = [string]$start.run_id
  if (-not $createdRunId) {
    throw "Start-run response did not include run_id."
  }

  $script:smokeStep = "retrying MFE/MAE Path Research backtest"
  $retry = Invoke-SmokeJson "Post" "$backendUrl/api/research/iterations/$iterationId/mfe-mae/backtest" @{
    run_id = $createdRunId
    force_new = $false
    reviewer = "research-closure-smoke"
  }
  $warning = [string]$retry.metrics.mfe_mae_research_backtest_warning
  if (-not $warning) {
    $warning = [string]$retry.metrics.bottom_research_backtest_warning
  }
  if (-not $warning) {
    throw "MFE/MAE retry did not return a warning for the unstarted run."
  }
  if ($retry.metrics.simulation_only -ne $true -or $retry.metrics.is_real_trade -ne $false) {
    throw "MFE/MAE retry did not preserve simulation-only / non-real-trade metrics."
  }
  Write-Output "ok MFE/MAE retry warning $warning"

  if ($BrowserSmoke) {
    $script:smokeStep = "running browser smoke"
    $env:RESEARCH_CLOSURE_FRONTEND_URL = $frontendUrl
    $env:RESEARCH_CLOSURE_BACKEND_URL = $backendUrl
    $env:RESEARCH_CLOSURE_BROWSER_REQUIRED = "1"
    & $node.Source (Join-Path $PSScriptRoot "smoke-research-closure-browser.mjs")
    if ($LASTEXITCODE -ne 0) {
      throw "browser smoke failed with exit code $LASTEXITCODE"
    }
  }

  $script:smokeStep = "creating temp db portfolio sample"
  $portfolioSample = Invoke-SmokeJson "Post" "$backendUrl/api/portfolio/manual" @{
    sourceName = "research closure smoke portfolio"
    accountName = "smoke"
    cash = 50000
    availableCash = 50000
    totalAssets = 100000
    positions = @(
      @{
        symbol = "603663"
        name = "Smoke Holding"
        shares = 1000
        availableShares = 1000
        costPrice = 20
        marketValue = 20000
        pnl = 0
      }
    )
  }
  Write-Output "ok temp portfolio snapshot $($portfolioSample.snapshotId)"

  $script:smokeStep = "checking temp db closure counts"
  $portfolioCount = Get-SmokeSqliteCount "portfolio_snapshots"
  $holdingCount = Get-SmokeSqliteCount "holding_positions"
  if ($portfolioCount -le 0 -or $holdingCount -le 0) {
    throw "Temporary DB did not contain portfolio_snapshots > 0 and holding_positions > 0. portfolio_snapshots=$portfolioCount holding_positions=$holdingCount"
  }
  Write-Output "ok temp db portfolio_snapshots=$portfolioCount holding_positions=$holdingCount"
} catch {
  Write-SmokeDiagnostics $_.Exception.Message
  throw
} finally {
  if ($createdRunId -and $backendProcess -and -not $backendProcess.HasExited) {
    try {
      Invoke-SmokeJson "Delete" "$backendUrl/api/analysis/runs/$createdRunId" | Out-Null
      Write-Output "ok cleanup run $createdRunId"
    } catch {
      Write-Warning "Unable to delete smoke run ${createdRunId}: $($_.Exception.Message)"
    }
  }
  if ($frontendProcess) {
    Stop-ProcessTree -ProcessId $frontendProcess.Id
  }
  if ($backendProcess) {
    Stop-ProcessTree -ProcessId $backendProcess.Id
  }
}
