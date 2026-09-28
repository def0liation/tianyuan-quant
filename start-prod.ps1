param(
    [switch]$Build,
    [switch]$Open
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

New-Item -ItemType Directory -Force -Path ".\deploy\db" | Out-Null
New-Item -ItemType Directory -Force -Path ".\deploy\backend-storage" | Out-Null

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "Created .env from .env.example."
    throw "Fill API_WRITE_TOKEN before starting production. Fill LLM_API_KEY and TUSHARE_TOKEN when needed."
}

$apiWriteToken = $env:API_WRITE_TOKEN
if (-not $apiWriteToken) {
    $apiWriteToken = (Get-Content ".\.env" | ForEach-Object {
        if ($_ -match '^\s*API_WRITE_TOKEN\s*=\s*(.+?)\s*$') { $Matches[1].Trim().Trim('"').Trim("'") }
    } | Select-Object -First 1)
}
if (-not $apiWriteToken) {
    throw "API_WRITE_TOKEN is required for production strict auth. Set it in .env or the current environment before running start-prod.ps1."
}

$argsList = @("compose", "-f", "docker-compose.prod.yml", "--env-file", ".env", "up", "-d")
if ($Build) {
    $argsList += "--build"
}

docker @argsList

Write-Host "Frontend: http://localhost:5174"
Write-Host "Backend health: http://localhost:8000/api/health"

if ($Open) {
    Start-Process "http://localhost:5174"
}
