[CmdletBinding()]
param(
    [switch]$Once,
    [string]$WorkerId = "",
    [double]$IntervalSeconds = 1.0,
    [string]$DatabaseFile = "",
    [string]$JobStorageFile = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$UvCacheDirOverride = [string]$env:TIANYUAN_UV_CACHE_DIR
$WorkerPythonOverride = [string]$env:TIANYUAN_BACKEND_TEST_PYTHON
if ([string]::IsNullOrWhiteSpace($UvCacheDirOverride)) {
    $UvCacheDir = Join-Path $Root ".uv-cache"
}
elseif ([System.IO.Path]::IsPathRooted($UvCacheDirOverride)) {
    $UvCacheDir = $UvCacheDirOverride
}
else {
    $UvCacheDir = Join-Path $Root $UvCacheDirOverride
}
$BackendDir = Join-Path $Root "backend"
$Requirements = Join-Path $BackendDir "requirements.txt"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$RepoVenvPython = Join-Path $Root ".venv\Scripts\python.exe"

function Resolve-WorkerPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $Root $PathValue))
}

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

function Resolve-WorkerPythonOverride([string]$PathValue) {
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
$PythonCommand = if ($WorkerPythonOverride) { $null } else { Get-Command python.exe -ErrorAction SilentlyContinue }
if ($WorkerPythonOverride) {
    $PythonExe = Resolve-WorkerPythonOverride $WorkerPythonOverride
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
    throw "uv.exe was not found. Install uv or add it to PATH, then rerun: npm.cmd run worker:analysis"
}

if (-not $UseDirectPython) {
    New-Item -ItemType Directory -Path $UvCacheDir -Force | Out-Null
    $env:UV_CACHE_DIR = $UvCacheDir
}
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$BackendDir;$env:PYTHONPATH" } else { $BackendDir }
$env:ANALYSIS_EXECUTION_MODE = "worker"
if ($DatabaseFile) {
    $ResolvedDatabaseFile = Resolve-WorkerPath $DatabaseFile
    New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($ResolvedDatabaseFile)) -Force | Out-Null
    $DatabaseUrlPath = $ResolvedDatabaseFile -replace "\\", "/"
    $env:TIANYUAN_QUANT_DB_URL = "sqlite+aiosqlite:///$DatabaseUrlPath"
    $env:TIANYUAN_SKIP_ALEMBIC = "1"
}
if ($JobStorageFile) {
    $ResolvedJobStorageFile = Resolve-WorkerPath $JobStorageFile
    New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($ResolvedJobStorageFile)) -Force | Out-Null
    $env:TIANYUAN_ANALYSIS_JOBS_FILE = $ResolvedJobStorageFile
}

$WorkerArgs = @("--interval", "$IntervalSeconds")
if ($Once) {
    $WorkerArgs += "--once"
}
if ($WorkerId) {
    $WorkerArgs += @("--worker-id", $WorkerId)
}

Push-Location $Root
try {
    $PythonWorkerArgs = @(
        "-m",
        "app.core.analysis_worker"
    )
    $PythonWorkerArgs += $WorkerArgs
    if ($UseDirectPython) {
        & $PythonExe @PythonWorkerArgs
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
        $UvArgs += $PythonWorkerArgs
        uv @UvArgs
    }
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
