[CmdletBinding()]
param(
    [int[]]$BackendPorts = @(8000..8019),
    [int[]]$FrontendPorts = @(5174..5193),
    [int]$TimeoutSeconds = 20,
    [switch]$StateOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root ".logs"
$ProcessStatePath = Join-Path $LogDir "dev-processes.json"
$Targets = @{}

function Write-Step {
    param([string]$Message)
    Write-Host "[dev-stop] $Message" -ForegroundColor Cyan
}

function Read-DevProcessState {
    if (-not (Test-Path $ProcessStatePath)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $ProcessStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        Write-Step "Ignoring unreadable process state: $ProcessStatePath"
        return $null
    }
}

function Test-StateBelongsToWorkspace {
    param($State)

    if (-not $State -or -not $State.root) {
        return $false
    }

    try {
        return [System.IO.Path]::GetFullPath([string]$State.root) -ieq [System.IO.Path]::GetFullPath($Root)
    }
    catch {
        return $false
    }
}

function Add-StopTarget {
    param(
        [int]$ProcessId,
        [string]$Reason
    )

    if ($ProcessId -le 0 -or $ProcessId -eq $PID) {
        return
    }

    if (-not $Targets.ContainsKey($ProcessId)) {
        $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        $Targets[$ProcessId] = [ordered]@{
            processId = $ProcessId
            processName = if ($process) { $process.ProcessName } else { "" }
            reasons = @()
        }
    }

    $Targets[$ProcessId].reasons += $Reason
}

function Stop-ProcessById {
    param([int]$ProcessId)

    if ($ProcessId -le 0 -or $ProcessId -eq $PID) {
        return
    }

    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    if (Test-Path $taskkill) {
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $taskkill /PID $ProcessId /T /F 1>$null 2>$null
        }
        catch {
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
    }

    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
    try {
        Wait-Process -Id $ProcessId -Timeout 2 -ErrorAction SilentlyContinue
    }
    catch {
    }
}

function Get-Listeners {
    $listeners = @()
    $lines = netstat -ano | Select-String -Pattern "LISTENING"
    foreach ($line in $lines) {
        if ($line.Line -match "^\s*TCP\s+\S+:(\d+)\s+\S+\s+LISTENING\s+(\d+)") {
            $listeners += [pscustomobject]@{
                Port = [int]$matches[1]
                ProcessId = [int]$matches[2]
            }
        }
    }
    return $listeners
}

function Add-ListenersForPorts {
    param([int[]]$Ports)

    $portSet = @{}
    foreach ($port in $Ports) {
        $portSet[$port] = $true
    }

    foreach ($listener in Get-Listeners) {
        if ($portSet.ContainsKey($listener.Port)) {
            Add-StopTarget -ProcessId $listener.ProcessId -Reason "listening on port $($listener.Port)"
        }
    }
}

function Get-ListenersForPorts {
    param([int[]]$Ports)

    $portSet = @{}
    foreach ($port in $Ports) {
        $portSet[$port] = $true
    }

    return @(Get-Listeners | Where-Object { $portSet.ContainsKey($_.Port) })
}

function Stop-Targets {
    if ($Targets.Count -eq 0) {
        Write-Step "No matching dev frontend/backend processes were found."
        return
    }

    $orderedTargets = @($Targets.Values) | Sort-Object processId
    foreach ($target in $orderedTargets) {
        $reasonText = ($target.reasons | Select-Object -Unique) -join "; "
        if ($DryRun) {
            Write-Step "Would stop PID $($target.processId) $($target.processName): $reasonText"
            continue
        }

        Write-Step "Stopping PID $($target.processId) $($target.processName): $reasonText"
        Stop-ProcessById -ProcessId $target.processId
    }
}

function Wait-PortsReleased {
    param([int[]]$Ports)

    if ($DryRun -or $Ports.Count -eq 0) {
        return
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $remaining = Get-ListenersForPorts -Ports $Ports
        if ($remaining.Count -eq 0) {
            return
        }

        foreach ($listener in $remaining) {
            if ($listener.ProcessId -ne $PID) {
                Write-Step "Port $($listener.Port) is still listening; stopping PID $($listener.ProcessId)"
                Stop-ProcessById -ProcessId $listener.ProcessId
            }
        }
        Start-Sleep -Seconds 1
    }

    $remainingAfterTimeout = Get-ListenersForPorts -Ports $Ports
    if ($remainingAfterTimeout.Count -gt 0) {
        $summary = ($remainingAfterTimeout | ForEach-Object { "$($_.Port)/PID $($_.ProcessId)" }) -join ", "
        throw "Timed out waiting for dev ports to close: $summary"
    }
}

$state = Read-DevProcessState
$stateMatches = Test-StateBelongsToWorkspace -State $state
$portsToStop = @()

if ($stateMatches) {
    if ($state.backendPort) {
        $portsToStop += [int]$state.backendPort
    }
    if ($state.frontendPort) {
        $portsToStop += [int]$state.frontendPort
    }

    foreach ($entry in @($state.processes)) {
        if ($entry.pid) {
            Add-StopTarget -ProcessId ([int]$entry.pid) -Reason "recorded launcher process: $($entry.name)"
        }
    }
    if ($state.launcherPid) {
        Add-StopTarget -ProcessId ([int]$state.launcherPid) -Reason "recorded launcher process"
    }
}

if (-not $StateOnly) {
    $portsToStop += $BackendPorts
    $portsToStop += $FrontendPorts
}

$portsToStop = @($portsToStop | Where-Object { $_ -gt 0 } | Select-Object -Unique)
if ($portsToStop.Count -gt 0) {
    Add-ListenersForPorts -Ports $portsToStop
}

Stop-Targets
Wait-PortsReleased -Ports $portsToStop

if ((-not $DryRun) -and $stateMatches -and (Test-Path $ProcessStatePath)) {
    Remove-Item -LiteralPath $ProcessStatePath -Force -ErrorAction SilentlyContinue
}

Write-Step "Done."
