[CmdletBinding()]
param(
    [switch]$All,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$UvCacheDirOverride = [string]$env:TIANYUAN_UV_CACHE_DIR
$BackendPythonOverride = [string]$env:TIANYUAN_BACKEND_TEST_PYTHON
if ([string]::IsNullOrWhiteSpace($UvCacheDirOverride)) {
    $UvCacheDir = Join-Path $Root ".uv-cache"
}
elseif ([System.IO.Path]::IsPathRooted($UvCacheDirOverride)) {
    $UvCacheDir = $UvCacheDirOverride
}
else {
    $UvCacheDir = Join-Path $Root $UvCacheDirOverride
}
$PytestCacheDir = Join-Path $Root ".tmp\pytest-cache"
$TempRunId = [guid]::NewGuid().ToString("N")
$SystemTempRoot = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "Temp\tianyuan-quant-agent-ui"
}
else {
    Join-Path ([System.IO.Path]::GetTempPath()) "tianyuan-quant-agent-ui"
}
$PytestTempDir = Join-Path $SystemTempRoot ("pytest-temp-{0}" -f $TempRunId)
$PytestBaseTempDir = Join-Path $Root (".tmp\pytest-basetemp-{0}" -f $TempRunId)
$BackendDir = Join-Path $Root "backend"
$Requirements = Join-Path $BackendDir "requirements.txt"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$RepoVenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Test-UsablePython([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue) -or -not (Test-Path -LiteralPath $PathValue -PathType Leaf)) {
        return $false
    }
    try {
        & $PathValue "--version" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Resolve-BackendPythonOverride([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return ""
    }
    $Candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) {
        $PathValue
    }
    else {
        Join-Path $Root $PathValue
    }
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        throw "TIANYUAN_BACKEND_TEST_PYTHON points to a missing Python executable: $Candidate"
    }
    return (Resolve-Path -LiteralPath $Candidate).Path
}

$UseDirectPython = $false
$PythonCommand = if ($BackendPythonOverride) { $null } else { Get-Command python.exe -ErrorAction SilentlyContinue }
if ($BackendPythonOverride) {
    $PythonExe = Resolve-BackendPythonOverride $BackendPythonOverride
    $UseDirectPython = $true
}
elseif (Test-UsablePython $RepoVenvPython) {
    $PythonExe = (Resolve-Path -LiteralPath $RepoVenvPython).Path
    $UseDirectPython = $true
}
elseif ($PythonCommand) {
    $PythonExe = $PythonCommand.Source
}
elseif (Test-Path $BundledPython) {
    $PythonExe = $BundledPython
}
else {
    throw "No usable Python interpreter was found. Install Python, or run inside Codex with the bundled Python runtime available."
}

if (-not $UseDirectPython -and -not (Get-Command uv.exe -ErrorAction SilentlyContinue)) {
    throw "uv.exe was not found. Install uv or add it to PATH, then rerun: npm.cmd run test:backend"
}

if (-not $UseDirectPython) {
    New-Item -ItemType Directory -Path $UvCacheDir -Force | Out-Null
    $env:UV_CACHE_DIR = $UvCacheDir
}
New-Item -ItemType Directory -Path $PytestCacheDir -Force | Out-Null
New-Item -ItemType Directory -Path $SystemTempRoot -Force | Out-Null
New-Item -ItemType Directory -Path $PytestTempDir -Force | Out-Null
$env:TEMP = $PytestTempDir
$env:TMP = $PytestTempDir
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$BackendDir;$env:PYTHONPATH" } else { $BackendDir }

if ($All -and (-not $PytestArgs -or $PytestArgs.Count -eq 0)) {
    $PytestArgs = @("backend\tests", "-q")
}
elseif (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @(
        "backend\tests\test_http_auth.py",
        "backend\tests\test_config_routes.py",
        "backend\tests\test_agent_runtime.py",
        "backend\tests\test_analysis_workflow.py",
        "backend\tests\test_analysis_lifecycle_core_services.py",
        "backend\tests\test_analysis_run_compare.py",
        "backend\tests\test_mfe_mae_quant_core_chain.py",
        "backend\tests\test_market_data_runner.py",
        "backend\tests\test_market_data_adapter.py",
        "backend\tests\test_data_reliability_routes.py",
        "backend\tests\test_portfolio_store.py",
        "backend\tests\test_auto_paper_trading.py",
        "backend\tests\test_auto_paper_routes.py",
        "backend\tests\test_signalops_lifecycle_store.py",
        "backend\tests\test_signalops.py",
        "backend\tests\test_signalops_routes.py",
        "backend\tests\test_backtest_engine.py",
        "backend\tests\test_backtest_signalops_sample.py",
        "backend\tests\test_backtest_store.py",
        "backend\tests\test_research_store.py",
        "backend\tests\test_research_artifact_store.py",
        "backend\tests\test_research_verdict_store.py",
        "backend\tests\test_evaluation.py",
        "backend\tests\test_plugin_store.py",
        "backend\tests\test_plugin_runtime.py",
        "backend\tests\test_analysis_job_sqlite.py",
        "backend\tests\test_analysis_job_reconciliation.py",
        "backend\tests\test_observability_routes.py",
        "backend\tests\test_repo_hygiene.py",
        "-q"
    )
}

Push-Location $Root
try {
    $PytestCommandArgs = @(
        "-m",
        "pytest",
        "-o",
        "cache_dir=$PytestCacheDir"
    )
    $HasBaseTemp = $false
    foreach ($Arg in $PytestArgs) {
        if ($Arg -eq "--basetemp" -or $Arg.StartsWith("--basetemp=")) {
            $HasBaseTemp = $true
            break
        }
    }
    if (-not $HasBaseTemp) {
        $PytestCommandArgs += "--basetemp=$PytestBaseTempDir"
    }
    $PytestCommandArgs += $PytestArgs
    if ($UseDirectPython) {
        & $PythonExe @PytestCommandArgs
    }
    else {
        $UvArgs = @("run")
        if (Test-Path (Join-Path $Root "pyproject.toml")) {
            $UvArgs += "--no-project"
        }
        $UvArgs += @(
            "--no-python-downloads",
            "--python",
            $PythonExe,
            "--with-requirements",
            $Requirements,
            "python"
        )
        $UvArgs += $PytestCommandArgs
        uv @UvArgs
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
