[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5174,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSCommandPath
if (-not $ScriptPath) {
    $ScriptPath = $MyInvocation.MyCommand.Path
}
$ScriptDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($ScriptPath))
$Root = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$RuntimeDir = Join-Path $Root "runtime"
$NodeExe = Join-Path $RuntimeDir "node\node.exe"
$PythonExe = Join-Path $RuntimeDir "python\python.exe"
$PythonDeps = Join-Path $RuntimeDir "python-deps"
$EnvFile = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"
$LogDir = Join-Path $Root ".logs"
$RunId = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss-fff"), $PID
$BackendOutLog = Join-Path $LogDir "portable-backend-$RunId.out.log"
$BackendErrLog = Join-Path $LogDir "portable-backend-$RunId.err.log"
$FrontendOutLog = Join-Path $LogDir "portable-frontend-$RunId.out.log"
$FrontendErrLog = Join-Path $LogDir "portable-frontend-$RunId.err.log"
$ProcessStatePath = Join-Path $LogDir "portable-processes.json"
$OwnedProcesses = @()

function Write-Step {
    param([string]$Message)
    Write-Host "[portable] $Message" -ForegroundColor Cyan
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

function Import-DotEnv {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $name, $value = $trimmed -split "=", 2
        if (-not $name -or $null -eq $value) {
            continue
        }

        $name = $name.Trim()
        $value = $value.Trim()
        if (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

function Test-StrictWriteAuthEnabled {
    $mode = $env:API_AUTH_MODE
    if (-not $mode) {
        $mode = ""
    }
    $mode = $mode.Trim().ToLowerInvariant()
    if ($mode -in @("on", "enabled", "required", "strict", "write", "write_protect")) {
        return $true
    }
    if ($mode -in @("off", "disabled", "none", "dev", "development", "local", "bypass")) {
        return $false
    }

    $appEnv = $env:APP_ENV
    if (-not $appEnv) {
        $appEnv = $env:ENVIRONMENT
    }
    if (-not $appEnv) {
        $appEnv = ""
    }
    $appEnv = $appEnv.Trim().ToLowerInvariant()
    return $appEnv -in @("prod", "production", "staging", "strict")
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

function Save-ProcessState {
    param(
        [int]$ResolvedBackendPort,
        [int]$ResolvedFrontendPort,
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
        backendPort = $ResolvedBackendPort
        frontendPort = $ResolvedFrontendPort
        backendUrl = $BackendUrl
        frontendUrl = $FrontendUrl
        updatedAt = (Get-Date).ToString("o")
        processes = $processes
    }

    $payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ProcessStatePath -Encoding UTF8
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

foreach ($requiredPath in @($NodeExe, $PythonExe, $PythonDeps, $BackendDir, $FrontendDir)) {
    if (-not (Test-Path $requiredPath)) {
        throw "Portable package is incomplete. Missing: $requiredPath"
    }
}

Normalize-ProcessPathVariable

if ((-not (Test-Path $EnvFile)) -and (Test-Path $EnvExample)) {
    Copy-Item -LiteralPath $EnvExample -Destination $EnvFile -Force
    Write-Warning "Created .env from .env.example. Fill your own API_WRITE_TOKEN, LLM_API_KEY, TUSHARE_TOKEN, and MARKET_DATA_API_KEY when needed."
}

Import-DotEnv -Path $EnvFile

New-Item -ItemType Directory -Force -Path (Join-Path $Root "storage") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackendDir "storage") | Out-Null

if ((Test-StrictWriteAuthEnabled) -and (-not $env:API_WRITE_TOKEN) -and (-not $env:SUPER_API_WRITE_TOKEN)) {
    Write-Warning "Strict API write auth is enabled, but API_WRITE_TOKEN is empty. The app can start, but write APIs will be blocked until you fill .env."
}

if (-not $env:TIANYUAN_SKIP_ALEMBIC -and $env:REQUIRE_DB_MIGRATIONS -ne "1") {
    $env:TIANYUAN_SKIP_ALEMBIC = "1"
}

$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
if ($previousPythonPath) {
    $env:PYTHONPATH = "$PythonDeps$([System.IO.Path]::PathSeparator)$previousPythonPath"
}
else {
    $env:PYTHONPATH = $PythonDeps
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Write-Step "Log file suffix: $RunId"

try {
    $BackendPort = Find-AvailablePort -StartPort $BackendPort
    $FrontendPort = Find-AvailablePort -StartPort $FrontendPort
    $backendUrl = "http://127.0.0.1:$BackendPort"
    $frontendUrl = "http://127.0.0.1:$FrontendPort"

    $env:BACKEND_PORT = $BackendPort
    Start-ManagedProcess `
        -Name "backend" `
        -FilePath $PythonExe `
        -Arguments @("start_uvicorn.py", "--port", "$BackendPort", "--no-reload") `
        -WorkingDirectory $BackendDir `
        -StdOutPath $BackendOutLog `
        -StdErrPath $BackendErrLog

    if (-not (Wait-HttpSuccess -Url "$backendUrl/api/health" -TimeoutSeconds 45)) {
        throw "Backend did not become healthy. See $BackendErrLog"
    }

    $env:FRONTEND_PORT = $FrontendPort
    $env:VITE_API_PROXY_TARGET = $backendUrl
    Start-ManagedProcess `
        -Name "frontend" `
        -FilePath $NodeExe `
        -Arguments @("start-vite-dev.mjs", "--host", "127.0.0.1", "--port", "$FrontendPort") `
        -WorkingDirectory $FrontendDir `
        -StdOutPath $FrontendOutLog `
        -StdErrPath $FrontendErrLog

    if (-not (Wait-HttpOk -Url $frontendUrl -TimeoutSeconds 45)) {
        throw "Frontend did not become available. See $FrontendErrLog"
    }

    Save-ProcessState -ResolvedBackendPort $BackendPort -ResolvedFrontendPort $FrontendPort -BackendUrl $backendUrl -FrontendUrl $frontendUrl

    Write-Host ""
    Write-Host "Backend:  $backendUrl" -ForegroundColor Green
    Write-Host "API docs: $backendUrl/docs" -ForegroundColor Green
    Write-Host "Frontend: $frontendUrl" -ForegroundColor Green
    Write-Host "Logs:     $LogDir" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "Press Ctrl+C to stop processes started by this portable launcher." -ForegroundColor Yellow

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
    if ($null -eq $previousPythonPath) {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
}
