param(
  [string[]]$Scenarios = @("platform", "signalops", "research-backtest", "portfolio-live-plugin"),
  [int]$BackendPortStart = 8866,
  [int]$FrontendPortStart = 5896
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$smokeScript = Join-Path $PSScriptRoot "smoke-strict-auth-browser.ps1"
if (-not (Test-Path -LiteralPath $smokeScript)) {
  throw "Strict-auth browser smoke wrapper was not found: $smokeScript"
}
$powershellCommand = Get-Command powershell.exe -ErrorAction SilentlyContinue
if (-not $powershellCommand) {
  throw "powershell.exe was not found on PATH."
}

$validScenarios = @("platform", "signalops", "research-backtest", "portfolio-live-plugin")
$selectedScenarios = @($Scenarios | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() })
if ($selectedScenarios.Count -eq 0) {
  throw "At least one strict-auth browser scenario must be selected."
}

foreach ($scenario in $selectedScenarios) {
  if ($validScenarios -notcontains $scenario) {
    throw "Unknown strict-auth browser scenario '$scenario'. Valid scenarios: $($validScenarios -join ', ')"
  }
}

$startedAt = Get-Date
$summary = @()
for ($index = 0; $index -lt $selectedScenarios.Count; $index++) {
  $scenario = $selectedScenarios[$index]
  $scenarioBackendStart = $BackendPortStart + ($index * 100)
  $scenarioFrontendStart = $FrontendPortStart + ($index * 100)
  $scenarioStartedAt = Get-Date
  Write-Output "strict-auth scenario matrix start: $scenario"
  & $powershellCommand.Source `
    -NoProfile `
    -ExecutionPolicy Bypass `
    -File $smokeScript `
    -Scenario $scenario `
    -BackendPortStart $scenarioBackendStart `
    -FrontendPortStart $scenarioFrontendStart
  if ($LASTEXITCODE -ne 0) {
    throw "strict-auth scenario matrix failed at $scenario with exit code $LASTEXITCODE"
  }
  $elapsed = [Math]::Round(((Get-Date) - $scenarioStartedAt).TotalSeconds, 1)
  $summary += [pscustomobject]@{
    scenario = $scenario
    seconds = $elapsed
  }
  Write-Output "strict-auth scenario matrix ok: $scenario (${elapsed}s)"
}

$totalSeconds = [Math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
Write-Output "ok strict-auth browser scenario matrix $($selectedScenarios -join ',') (${totalSeconds}s)"
$summary | Format-Table -AutoSize | Out-String | Write-Output
