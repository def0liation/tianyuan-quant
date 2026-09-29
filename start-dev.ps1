[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5174,
    [switch]$Install,
    [switch]$RecreateBackendVenv,
    [switch]$Open,
    [switch]$BackendReload
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root ".logs"
$UvCacheDir = Join-Path $Root ".uv-cache"
$BackendUvCacheDir = Join-Path $Root ".uv-runtime-cache"
$BackendVenvDir = Join-Path $BackendDir ".venv"
$BackendPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$RunId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"), $PID
$BackendOutLog = Join-Path $LogDir "backend-$RunId.out.log"
$BackendErrLog = Join-Path $LogDir "backend-$RunId.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend-$RunId.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend-$RunId.err.log"
$ProcessStatePath = Join-Path $LogDir "dev-processes.json"
$OwnedProcesses = @()

function Write-Step {
    param([string]$Message)
    Write-Host "[dev] $Message" -ForegroundColor Cyan
}

function Normalize-ProcessPathVariable {
    $pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
    if (-not $pathValue) {
        $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
    }

    if (-not $pathValue) {
        return
    }

    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
    $env:Path = $pathValue
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port
    )

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $asyncResult = $client.BeginConnect($HostName, $Port, $null, $null)
        $connected = $asyncResult.AsyncWaitHandle.WaitOne(300, $false)
        if ($connected) {
            $client.EndConnect($asyncResult)
            return $true
        }
        return $false
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Find-AvailablePort {
    param(
        [int]$StartPort,
        [int]$MaxAttempts = 20
    )

    for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
        $candidate = $StartPort + $offset
        if (-not (Test-TcpPort -HostName "127.0.0.1" -Port $candidate)) {
            return $candidate
        }
    }

    throw "No available port found from $StartPort to $($StartPort + $MaxAttempts - 1)."
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Wait-HttpSuccess {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

function Wait-BackendCoreReady {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri "$Url/api/startup/status" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                $status = $response.Content | ConvertFrom-Json
                if ($status.coreReady -eq $true) {
                    return $true
                }
            }
        }
        catch {
            if (Wait-HttpSuccess -Url "$Url/api/health" -TimeoutSeconds 1) {
                return $true
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Resolve-PythonForVenv {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return @{ File = $python.Source; Args = @() }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return @{ File = $py.Source; Args = @("-3") }
    }

    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uv) {
        $fallbackPython = Resolve-FallbackPython
        if ($fallbackPython) {
            $env:UV_CACHE_DIR = $BackendUvCacheDir
            return @{ File = $uv.Source; Args = @("run", "--no-project", "--python", $fallbackPython, "python") }
        }
    }

    throw "Python was not found. Install Python 3.13, install uv, or create backend\.venv manually."
}

function Resolve-FallbackPython {
    $candidates = @()

    if ($env:CODEX_HOME) {
        $candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    }

    $candidates += Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) {
            continue
        }

        try {
            & $candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
        }
    }

    return $null
}

function Resolve-CachedBackendSitePackages {
    param([string]$PythonPath)

    if (-not $PythonPath) {
        return $null
    }

    $archiveRoot = Join-Path $BackendUvCacheDir "archive-v0"
    if (-not (Test-Path $archiveRoot)) {
        return $null
    }

    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $candidateDirs = Get-ChildItem -LiteralPath $archiveRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending

    foreach ($candidateDir in $candidateDirs) {
        $sitePackages = Join-Path $candidateDir.FullName "Lib\site-packages"
        if (-not (Test-Path (Join-Path $sitePackages "fastapi"))) {
            continue
        }
        if (-not (Test-Path (Join-Path $sitePackages "uvicorn"))) {
            continue
        }

        try {
            $env:PYTHONPATH = $sitePackages
            & $PythonPath -c "import fastapi, uvicorn, pydantic_core" *> $null
            if ($LASTEXITCODE -eq 0) {
                return $sitePackages
            }
        }
        catch {
        }
        finally {
            if ($null -eq $previousPythonPath) {
                [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
                Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
            }
            else {
                $env:PYTHONPATH = $previousPythonPath
            }
        }
    }

    return $null
}

function Use-BackendPythonPath {
    param([string]$SitePackages)

    $currentPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    if ($currentPythonPath) {
        $env:PYTHONPATH = "$SitePackages$([System.IO.Path]::PathSeparator)$currentPythonPath"
    }
    else {
        $env:PYTHONPATH = $SitePackages
    }
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Test-BackendPython {
    if (-not (Test-Path $BackendPython)) {
        return $false
    }

    try {
        & $BackendPython --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Ensure-Backend {
    if (-not (Test-BackendPython)) {
        $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
        $fallbackPython = Resolve-FallbackPython
        $cachedSitePackages = Resolve-CachedBackendSitePackages -PythonPath $fallbackPython
        if ((-not $Install) -and $fallbackPython -and $cachedSitePackages) {
            Write-Step "Backend virtualenv is missing or broken; using cached backend dependencies"
            Use-BackendPythonPath -SitePackages $cachedSitePackages
            return @{
                File = $fallbackPython
                Args = @()
            }
        }

        if ((-not $Install) -and $uv -and $fallbackPython) {
            Write-Step "Backend virtualenv is missing or broken; using uv runtime fallback"
            $env:UV_CACHE_DIR = $BackendUvCacheDir
            return @{
                File = $uv.Source
                Args = @(
                    "run",
                    "--no-project",
                    "--python",
                    $fallbackPython,
                    "--with-requirements",
                    "requirements.lock",
                    "python"
                )
            }
        }

        if (-not $Install) {
            throw "Missing or broken backend virtualenv, and no uv runtime fallback is available. Run: .\start-dev.ps1 -Install"
        }

        if (Test-Path $BackendVenvDir) {
            if (-not $RecreateBackendVenv) {
                throw "Backend virtualenv exists but is broken. Refusing to remove it during -Install without explicit confirmation. Rerun with: .\start-dev.ps1 -Install -RecreateBackendVenv"
            }

            Write-Step "Removing broken backend virtualenv after explicit -RecreateBackendVenv"
            Remove-Item -LiteralPath $BackendVenvDir -Recurse -Force
        }

        Write-Step "Creating backend virtualenv"
        $pythonCommand = Resolve-PythonForVenv
        $venvArgs = @($pythonCommand.Args) + @("-m", "venv", ".venv")
        Invoke-Checked -FilePath $pythonCommand.File -Arguments $venvArgs -WorkingDirectory $BackendDir
    }

    if ($Install) {
        Write-Step "Installing backend dependencies"
        Invoke-Checked -FilePath $BackendPython -Arguments @("-m", "pip", "install", "--require-hashes", "-r", "requirements.lock") -WorkingDirectory $BackendDir
    }

    return @{ File = $BackendPython; Args = @() }
}

function Ensure-Frontend {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "npm.cmd was not found. Install Node.js or add npm to PATH."
    }

    $nodeModules = Join-Path $FrontendDir "node_modules"
    if ((-not (Test-Path $nodeModules)) -and (-not $Install)) {
        throw "Missing frontend node_modules. Run: .\start-dev.ps1 -Install"
    }

    if ($Install) {
        Write-Step "Installing frontend dependencies"
        Invoke-Checked -FilePath $npm.Source -Arguments @("install") -WorkingDirectory $FrontendDir
    }

    return $npm.Source
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdOutPath,
        [string]$StdErrPath
    )

    Write-Step "Starting $Name"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOutPath `
        -RedirectStandardError $StdErrPath `
        -WindowStyle Hidden `
        -PassThru

    $script:OwnedProcesses += @{
        Name = $Name
        Process = $process
        FilePath = $FilePath
        Arguments = $Arguments
        WorkingDirectory = $WorkingDirectory
        StdOutPath = $StdOutPath
        StdErrPath = $StdErrPath
        StartedAt = (Get-Date).ToString("o")
    }

    Write-Step "$Name PID: $($process.Id)"
}

function Save-DevProcessState {
    param(
        [int]$BackendPort,
        [int]$FrontendPort,
        [string]$BackendUrl,
        [string]$FrontendUrl
    )

    $processes = @(
        foreach ($entry in $script:OwnedProcesses) {
            [ordered]@{
                name = $entry.Name
                pid = $entry.Process.Id
                filePath = $entry.FilePath
                arguments = $entry.Arguments
                workingDirectory = $entry.WorkingDirectory
                stdout = $entry.StdOutPath
                stderr = $entry.StdErrPath
                startedAt = $entry.StartedAt
            }
        }
    )

    $payload = [ordered]@{
        runId = $RunId
        launcherPid = $PID
        root = $Root
        backendPort = $BackendPort
        frontendPort = $FrontendPort
        backendUrl = $BackendUrl
        frontendUrl = $FrontendUrl
        backendReload = [bool]$BackendReload
        updatedAt = (Get-Date).ToString("o")
        processes = $processes
    }

    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ProcessStatePath -Encoding UTF8
}

function Clear-DevProcessState {
    if (-not (Test-Path $ProcessStatePath)) {
        return
    }

    try {
        $state = Get-Content -LiteralPath $ProcessStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.runId -and $state.runId -ne $RunId) {
            return
        }
    }
    catch {
    }

    Remove-Item -LiteralPath $ProcessStatePath -Force -ErrorAction SilentlyContinue
}

function Stop-OwnedProcesses {
    foreach ($entry in $script:OwnedProcesses) {
        $process = $entry.Process
        if ($process -and -not $process.HasExited) {
            Write-Step "Stopping $($entry.Name) PID $($process.Id)"
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-BackendProcess {
    param(
        [int]$Port,
        [string]$Url,
        [hashtable]$PythonCommand
    )

    $env:BACKEND_PORT = $Port
    if (-not $env:TIANYUAN_SKIP_ALEMBIC -and $env:APP_ENV -ne "production" -and $env:REQUIRE_DB_MIGRATIONS -ne "1") {
        $env:TIANYUAN_SKIP_ALEMBIC = "1"
    }
    $backendArgs = @($PythonCommand.Args) + @("start_uvicorn.py", "--port", "$Port")
    if (-not $BackendReload) {
        $backendArgs += "--no-reload"
    }

    Start-ManagedProcess `
        -Name "backend" `
        -FilePath $PythonCommand.File `
        -Arguments $backendArgs `
        -WorkingDirectory $BackendDir `
        -StdOutPath $BackendOutLog `
        -StdErrPath $BackendErrLog
}

function Start-FrontendProcess {
    param(
        [int]$Port,
        [string]$Url,
        [string]$BackendUrl,
        [string]$NpmPath
    )

    $env:FRONTEND_PORT = $Port
    $env:VITE_API_PROXY_TARGET = $BackendUrl
    Start-ManagedProcess `
        -Name "frontend" `
        -FilePath $NpmPath `
        -Arguments @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$Port") `
        -WorkingDirectory $FrontendDir `
        -StdOutPath $FrontendOutLog `
        -StdErrPath $FrontendErrLog

    if (-not (Wait-HttpOk -Url $Url -TimeoutSeconds 35)) {
        throw "Frontend did not become available. See $FrontendErrLog"
    }
}

Normalize-ProcessPathVariable
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Write-Step "Log file suffix: $RunId"

try {
    $backendPythonCommand = Ensure-Backend
    $npmPath = Ensure-Frontend

    $requestedBackendPort = $BackendPort
    $requestedFrontendPort = $FrontendPort
    $backendUrl = "http://127.0.0.1:$BackendPort"
    $frontendUrl = "http://127.0.0.1:$FrontendPort"

    if (Test-TcpPort -HostName "127.0.0.1" -Port $BackendPort) {
        $backendHealthy = Wait-HttpSuccess -Url "$backendUrl/api/health" -TimeoutSeconds 3
        if ($backendHealthy) {
            Write-Step "Backend already running at $backendUrl"
        }
        else {
            $BackendPort = Find-AvailablePort -StartPort ($BackendPort + 1)
            $backendUrl = "http://127.0.0.1:$BackendPort"
            Write-Step "Backend port $requestedBackendPort is occupied but not usable; using $backendUrl"
            Start-BackendProcess -Port $BackendPort -Url $backendUrl -PythonCommand $backendPythonCommand
        }
    }
    else {
        Start-BackendProcess -Port $BackendPort -Url $backendUrl -PythonCommand $backendPythonCommand
    }
    Save-DevProcessState -BackendPort $BackendPort -FrontendPort $FrontendPort -BackendUrl $backendUrl -FrontendUrl $frontendUrl

    if (Test-TcpPort -HostName "127.0.0.1" -Port $FrontendPort) {
        $frontendAvailable = Wait-HttpOk -Url $frontendUrl -TimeoutSeconds 3
        if ($frontendAvailable -and $BackendPort -eq $requestedBackendPort) {
            Write-Step "Frontend already running at $frontendUrl"
        }
        else {
            $FrontendPort = Find-AvailablePort -StartPort ($FrontendPort + 1)
            $frontendUrl = "http://127.0.0.1:$FrontendPort"
            Write-Step "Frontend port $requestedFrontendPort is occupied or tied to a stale backend; using $frontendUrl"
            Start-FrontendProcess -Port $FrontendPort -Url $frontendUrl -BackendUrl $backendUrl -NpmPath $npmPath
        }
    }
    else {
        Start-FrontendProcess -Port $FrontendPort -Url $frontendUrl -BackendUrl $backendUrl -NpmPath $npmPath
    }
    Save-DevProcessState -BackendPort $BackendPort -FrontendPort $FrontendPort -BackendUrl $backendUrl -FrontendUrl $frontendUrl

    if (Wait-BackendCoreReady -Url $backendUrl -TimeoutSeconds 5) {
        Write-Step "Backend core is ready; optional modules may continue warming"
    }
    else {
        Write-Step "Backend is still warming; frontend will keep retrying status checks"
    }

    Write-Host ""
    Write-Host "Backend:  $backendUrl" -ForegroundColor Green
    Write-Host "API docs: $backendUrl/docs" -ForegroundColor Green
    Write-Host "Frontend: $frontendUrl" -ForegroundColor Green
    Write-Host "Logs:     $LogDir" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Press Ctrl+C to stop processes started by this launcher." -ForegroundColor Yellow

    if ($Open) {
        Start-Process $frontendUrl | Out-Null
    }

    while ($true) {
        foreach ($entry in $OwnedProcesses) {
            $process = $entry.Process
            if ($process.HasExited) {
                throw "$($entry.Name) exited with code $($process.ExitCode). See $($entry.StdErrPath)"
            }
        }
        Start-Sleep -Seconds 2
    }
}
finally {
    Stop-OwnedProcesses
    Clear-DevProcessState
}
