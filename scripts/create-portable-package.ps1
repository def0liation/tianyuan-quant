[CmdletBinding()]
param(
    [string]$OutputPath,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptPath = $PSCommandPath
if (-not $ScriptPath) {
    $ScriptPath = $MyInvocation.MyCommand.Path
}
$ScriptDir = Split-Path -Parent ([System.IO.Path]::GetFullPath($ScriptPath))
$Root = Split-Path -Parent $ScriptDir
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Resolve-DesktopDirectory {
    $desktopCandidates = @()
    $desktopCandidates += [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    $desktopCandidates += [Environment]::GetFolderPath("Desktop")
    foreach ($registryPath in @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
    )) {
        try {
            $desktopValue = (Get-ItemProperty -LiteralPath $registryPath -Name Desktop -ErrorAction Stop).Desktop
            if ($desktopValue) {
                $desktopCandidates += [Environment]::ExpandEnvironmentVariables($desktopValue)
            }
        }
        catch {
        }
    }
    if ($env:USERPROFILE) {
        $desktopCandidates += Join-Path $env:USERPROFILE "Desktop"
        $desktopCandidates += Join-Path $env:USERPROFILE "OneDrive\Desktop"
    }
    foreach ($oneDriveRoot in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
        if ($oneDriveRoot) {
            $desktopCandidates += Join-Path $oneDriveRoot "Desktop"
        }
    }
    $projectAncestor = Get-Item -LiteralPath $Root -ErrorAction SilentlyContinue
    while ($projectAncestor) {
        if ($projectAncestor.Name -ieq "Desktop") {
            $desktopCandidates += $projectAncestor.FullName
            break
        }
        $projectAncestor = $projectAncestor.Parent
    }
    foreach ($candidate in ($desktopCandidates | Where-Object { $_ } | Select-Object -Unique)) {
        $fullCandidate = [System.IO.Path]::GetFullPath($candidate)
        if (Test-Path -LiteralPath $fullCandidate -PathType Container) {
            return $fullCandidate
        }
    }

    throw "Could not resolve the current user's Desktop path."
}

function Resolve-DesktopZipPath {
    param(
        [string]$RequestedPath,
        [string]$Desktop,
        [string]$Timestamp
    )

    if (-not $RequestedPath) {
        return (Join-Path $Desktop "super-portable-$Timestamp.zip")
    }

    $fileName = [System.IO.Path]::GetFileName($RequestedPath)
    if (-not $fileName) {
        throw "OutputPath must be a .zip file name or a .zip path directly on Desktop."
    }
    if ([System.IO.Path]::GetExtension($fileName).ToLowerInvariant() -ne ".zip") {
        throw "OutputPath must point to a .zip file: $RequestedPath"
    }

    if (-not [System.IO.Path]::IsPathRooted($RequestedPath)) {
        return (Join-Path $Desktop $fileName)
    }

    $fullPath = [System.IO.Path]::GetFullPath($RequestedPath)
    $parent = [System.IO.Path]::GetDirectoryName($fullPath)
    if (-not $parent) {
        throw "OutputPath must be a .zip file directly on Desktop: $RequestedPath"
    }

    $fullDesktop = [System.IO.Path]::GetFullPath($Desktop).TrimEnd("\")
    $fullParent = [System.IO.Path]::GetFullPath($parent).TrimEnd("\")
    if (-not ($fullParent -ieq $fullDesktop)) {
        throw "OutputPath must be written directly to Desktop. Pass only a file name, or a path under $Desktop."
    }

    return $fullPath
}

$Desktop = Resolve-DesktopDirectory
$OutputPath = Resolve-DesktopZipPath -RequestedPath $OutputPath -Desktop $Desktop -Timestamp $Timestamp
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($OutputPath).ToLowerInvariant() -ne ".zip") {
    throw "OutputPath must point to a .zip file: $OutputPath"
}

$PackageName = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
$StageRoot = Join-Path $Root ".tmp\portable-package"
$StageProject = Join-Path $StageRoot $PackageName

function Write-Step {
    param([string]$Message)
    Write-Host "[portable-package] $Message" -ForegroundColor Cyan
}

function Get-FullPath {
    param([string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Test-IsUnderRoot {
    param(
        [string]$Path,
        [string]$Parent
    )

    $fullPath = (Get-FullPath $Path).TrimEnd("\")
    $fullParent = (Get-FullPath $Parent).TrimEnd("\")
    return $fullPath -ieq $fullParent -or $fullPath.StartsWith("$fullParent\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-RelativePath {
    param([string]$Path)

    $fullRoot = (Get-FullPath $Root).TrimEnd("\") + "\"
    $fullPath = Get-FullPath $Path
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside project root: $Path"
    }
    return $fullPath.Substring($fullRoot.Length)
}

function Get-RelativePathFromBase {
    param(
        [string]$Path,
        [string]$BasePath
    )

    $fullBase = (Get-FullPath $BasePath).TrimEnd("\") + "\"
    $fullPath = Get-FullPath $Path
    if (-not $fullPath.StartsWith($fullBase, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside base path: $Path"
    }
    return $fullPath.Substring($fullBase.Length)
}

function Convert-ToPortablePath {
    param([string]$RelativePath)
    return ($RelativePath -replace "\\", "/").TrimStart("/")
}

function Test-PortableExclude {
    param(
        [string]$RelativePath,
        [bool]$IsDirectory
    )

    $portable = Convert-ToPortablePath $RelativePath
    $leaf = [System.IO.Path]::GetFileName($RelativePath)
    $lower = $portable.ToLowerInvariant()
    $leafLower = $leaf.ToLowerInvariant()

    if ($lower -eq ".env.example") {
        return $false
    }

    if ($leafLower -eq ".env" -or $leafLower.StartsWith(".env.")) {
        return $true
    }

    if ($IsDirectory) {
        $excludedDirs = @(
            ".git",
            ".logs",
            ".playwright-cli",
            ".pytest_cache",
            ".tmp",
            ".uv-cache",
            ".uv-runtime-cache",
            ".venv",
            ".codex-security-scans",
            "backend/.pytest_cache",
            "backend/logs",
            "backend/history",
            "backend/.uv-cache",
            "backend/.uv-launcher-cache",
            "backend/.uv-runtime-cache",
            "backend/.venv",
            "backend/__pycache__",
            "backend/app/storage",
            "backend/storage",
            "deploy/backups",
            "deploy/backend-storage",
            "deploy/db",
            "dist",
            "frontend/dist",
            "frontend/logs",
            "frontend/node_modules",
            "histories",
            "history",
            "logs",
            "node_modules",
            "output",
            "runtime",
            "storage"
        )

        foreach ($dir in $excludedDirs) {
            if ($lower -eq $dir -or $lower.StartsWith("$dir/")) {
                return $true
            }
        }

        if ($leafLower -eq "__pycache__") {
            return $true
        }
    }

    if (-not $IsDirectory) {
        if ($leafLower.EndsWith(".pyc") -or $leafLower.EndsWith(".pyo")) {
            return $true
        }
        if ($leafLower.EndsWith(".log")) {
            return $true
        }
        if (
            $leafLower.EndsWith(".db") -or
            $leafLower.EndsWith(".db-journal") -or
            $leafLower.EndsWith(".db-shm") -or
            $leafLower.EndsWith(".db-wal") -or
            $leafLower.EndsWith(".sqlite") -or
            $leafLower.EndsWith(".sqlite3")
        ) {
            return $true
        }
        if ($leafLower.EndsWith(".tmp")) {
            return $true
        }
    }

    return $false
}

function Copy-PortableSourceTree {
    param(
        [string]$SourceDir,
        [string]$DestinationDir
    )

    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $SourceDir -Force) {
        $relative = Get-RelativePath $item.FullName
        if (Test-PortableExclude -RelativePath $relative -IsDirectory $item.PSIsContainer) {
            continue
        }

        $target = Join-Path $DestinationDir $item.Name
        if ($item.PSIsContainer) {
            Copy-PortableSourceTree -SourceDir $item.FullName -DestinationDir $target
        }
        else {
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

function Get-PortableSourceFiles {
    param([string]$SourceDir)

    $files = @()
    foreach ($item in Get-ChildItem -LiteralPath $SourceDir -Force) {
        $relative = Get-RelativePath $item.FullName
        if (Test-PortableExclude -RelativePath $relative -IsDirectory $item.PSIsContainer) {
            continue
        }
        if ($item.PSIsContainer) {
            $files += Get-PortableSourceFiles -SourceDir $item.FullName
        }
        else {
            $files += $item
        }
    }
    return $files
}

function Invoke-RobocopyCopy {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        throw "Missing source directory: $Source"
    }

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $null = & robocopy $Source $Destination /E /NFL /NDL /NJH /NJS /NP
    $exitCode = $LASTEXITCODE
    if ($exitCode -gt 7) {
        throw "Robocopy failed from $Source to $Destination with exit code $exitCode."
    }
}

function Resolve-NodeSource {
    if ($env:PORTABLE_NODE_SOURCE -and (Test-Path $env:PORTABLE_NODE_SOURCE)) {
        $candidate = Get-FullPath $env:PORTABLE_NODE_SOURCE
        if (Test-Path -LiteralPath (Join-Path $candidate "node.exe") -PathType Leaf) {
            return $candidate
        }
        throw "PORTABLE_NODE_SOURCE must point to a directory containing node.exe: $candidate"
    }

    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidate = Split-Path -Parent $command.Source
        if (Test-Path -LiteralPath (Join-Path $candidate "node.exe") -PathType Leaf) {
            return $candidate
        }
    }

    $programFilesNode = "C:\Program Files\nodejs"
    if (Test-Path -LiteralPath (Join-Path $programFilesNode "node.exe") -PathType Leaf) {
        return $programFilesNode
    }

    throw "Could not find node.exe. Set PORTABLE_NODE_SOURCE to a portable Node directory."
}

function Resolve-PythonSource {
    if ($env:PORTABLE_PYTHON_SOURCE -and (Test-Path $env:PORTABLE_PYTHON_SOURCE)) {
        $candidate = Get-FullPath $env:PORTABLE_PYTHON_SOURCE
        if (Test-Path -LiteralPath (Join-Path $candidate "python.exe") -PathType Leaf) {
            return $candidate
        }
        throw "PORTABLE_PYTHON_SOURCE must point to a directory containing python.exe: $candidate"
    }

    $codexPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python"
    if (Test-Path (Join-Path $codexPython "python.exe")) {
        return $codexPython
    }

    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) {
        $candidate = Split-Path -Parent $command.Source
        if (Test-Path -LiteralPath (Join-Path $candidate "python.exe") -PathType Leaf) {
            return $candidate
        }
    }

    throw "Could not find python.exe. Set PORTABLE_PYTHON_SOURCE to a portable Python directory."
}

function Find-BackendSitePackages {
    $candidateRoots = @(
        (Join-Path $Root ".uv-runtime-cache\archive-v0"),
        (Join-Path $Root "backend\.uv-runtime-cache\archive-v0")
    )

    $candidates = @()
    foreach ($candidateRoot in $candidateRoots) {
        if (-not (Test-Path $candidateRoot)) {
            continue
        }
        foreach ($dir in Get-ChildItem -LiteralPath $candidateRoot -Directory -ErrorAction SilentlyContinue) {
            $sitePackages = Join-Path $dir.FullName "Lib\site-packages"
            if (
                (Test-Path (Join-Path $sitePackages "fastapi")) -and
                (Test-Path (Join-Path $sitePackages "uvicorn")) -and
                (Test-Path (Join-Path $sitePackages "pydantic_core"))
            ) {
                $candidates += [pscustomobject]@{
                    Path = $sitePackages
                    LastWriteTime = $dir.LastWriteTime
                }
            }
        }
    }

    $venvSitePackages = Join-Path $Root "backend\.venv\Lib\site-packages"
    if (
        (Test-Path (Join-Path $venvSitePackages "fastapi")) -and
        (Test-Path (Join-Path $venvSitePackages "uvicorn")) -and
        (Test-Path (Join-Path $venvSitePackages "pydantic_core"))
    ) {
        $candidates += [pscustomobject]@{
            Path = $venvSitePackages
            LastWriteTime = (Get-Item $venvSitePackages).LastWriteTime
        }
    }

    $selected = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $selected) {
        throw "Could not find cached backend Python site-packages. Start the app once on this machine, then rerun packaging."
    }

    return $selected.Path
}

function Test-TextScanCandidate {
    param(
        [string]$Path,
        [string]$BasePath
    )

    $relative = Convert-ToPortablePath (Get-RelativePathFromBase -Path $Path -BasePath $BasePath)
    $lower = $relative.ToLowerInvariant()
    $leaf = [System.IO.Path]::GetFileName($Path).ToLowerInvariant()

    if ($lower -eq ".env.example") {
        return $true
    }

    if ($leaf -eq ".env" -or $leaf.StartsWith(".env.")) {
        return $false
    }

    $ignoredPrefixes = @(
        ".git/",
        ".logs/",
        ".playwright-cli/",
        ".pytest_cache/",
        ".tmp/",
        ".uv-cache/",
        ".uv-runtime-cache/",
        ".venv/",
        ".codex-security-scans/",
        "backend/.pytest_cache/",
        "backend/logs/",
        "backend/history/",
        "backend/.uv-cache/",
        "backend/.uv-launcher-cache/",
        "backend/.uv-runtime-cache/",
        "backend/.venv/",
        "backend/app/storage/",
        "backend/storage/",
        "deploy/backups/",
        "deploy/backend-storage/",
        "deploy/db/",
        "dist/",
        "frontend/dist/",
        "frontend/logs/",
        "frontend/node_modules/",
        "histories/",
        "history/",
        "logs/",
        "node_modules/",
        "output/",
        "runtime/",
        "storage/"
    )

    foreach ($prefix in $ignoredPrefixes) {
        if ($lower.StartsWith($prefix)) {
            return $false
        }
    }

    if ($lower.Contains("/node_modules/") -or $lower.Contains("/__pycache__/")) {
        return $false
    }

    $extension = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
    $textExtensions = @(
        ".cmd",
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".ps1",
        ".py",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml"
    )

    if ($textExtensions -contains $extension) {
        return $true
    }

    return $leaf -eq ".env.example" -or $leaf -eq ".gitignore" -or $leaf -eq ".dockerignore"
}

function Test-ScanSkipDirectory {
    param([string]$RelativePath)

    $lower = (Convert-ToPortablePath $RelativePath).ToLowerInvariant()
    $leaf = [System.IO.Path]::GetFileName($RelativePath).ToLowerInvariant()
    $ignoredDirs = @(
        ".git",
        ".logs",
        ".playwright-cli",
        ".pytest_cache",
        ".tmp",
        ".uv-cache",
        ".uv-runtime-cache",
        ".venv",
        ".codex-security-scans",
        "backend/.pytest_cache",
        "backend/logs",
        "backend/history",
        "backend/.uv-cache",
        "backend/.uv-launcher-cache",
        "backend/.uv-runtime-cache",
        "backend/.venv",
        "backend/app/storage",
        "backend/storage",
        "deploy/backups",
        "deploy/backend-storage",
        "deploy/db",
        "dist",
        "frontend/dist",
        "frontend/logs",
        "frontend/node_modules",
        "histories",
        "history",
        "logs",
        "node_modules",
        "output",
        "runtime",
        "storage"
    )

    foreach ($dir in $ignoredDirs) {
        if ($lower -eq $dir -or $lower.StartsWith("$dir/")) {
            return $true
        }
    }

    return $leaf -eq "__pycache__"
}

function Get-SecretScanFiles {
    param([string]$BasePath)

    $files = @()
    foreach ($item in Get-ChildItem -LiteralPath $BasePath -Force -ErrorAction SilentlyContinue) {
        $relative = Get-RelativePathFromBase -Path $item.FullName -BasePath $BasePath
        if ($item.PSIsContainer) {
            if (Test-ScanSkipDirectory -RelativePath $relative) {
                continue
            }
            $files += Get-SecretScanFiles -BasePath $item.FullName
        }
        else {
            $files += $item
        }
    }

    return $files
}

function Test-PlaceholderSecretValue {
    param([string]$Value)

    $trimmed = $Value.Trim().Trim('"').Trim("'")
    if (-not $trimmed) {
        return $true
    }

    $lower = $trimmed.ToLowerInvariant()
    $placeholders = @(
        "changeme",
        "change-me",
        "example",
        "placeholder",
        "replace-me",
        "test",
        "test-token",
        "your-api-key",
        "your-token"
    )
    if ($placeholders -contains $lower) {
        return $true
    }
    if ($lower.StartsWith("your_") -or $lower.StartsWith("your-")) {
        return $true
    }

    return $false
}

function Invoke-SecretScan {
    param([string]$BasePath)

    $findings = @()
    $envPattern = [regex]'^\s*(LLM_API_KEY|OPENAI_API_KEY|TUSHARE_TOKEN|MARKET_DATA_API_KEY|API_WRITE_TOKEN|SUPER_API_WRITE_TOKEN|AGENT_RUNTIME_SECRET_KEY|AGENT_RUNTIME_SECRET_KEY_PREVIOUS)\s*=\s*(.*?)\s*(?:#.*)?$'
    $openAiPattern = [regex]'sk-(proj-)?[A-Za-z0-9_-]{40,}'
    $bearerPattern = [regex]'Bearer\s+[A-Za-z0-9._-]{30,}'

    foreach ($file in Get-SecretScanFiles -BasePath $BasePath) {
        if (-not (Test-TextScanCandidate -Path $file.FullName -BasePath $BasePath)) {
            continue
        }
        if ($file.Length -gt 2MB) {
            continue
        }

        $relative = Convert-ToPortablePath (Get-RelativePathFromBase -Path $file.FullName -BasePath $BasePath)
        try {
            $content = [System.IO.File]::ReadAllText($file.FullName)
        }
        catch {
            continue
        }

        foreach ($line in ($content -split "`r?`n")) {
            $match = $envPattern.Match($line)
            if ($match.Success -and (-not (Test-PlaceholderSecretValue -Value $match.Groups[2].Value))) {
                $findings += [pscustomobject]@{ Path = $relative; Rule = "non_empty_secret_env_assignment" }
                break
            }
        }

        if ($openAiPattern.IsMatch($content)) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "openai_key_shape" }
        }
        if ($bearerPattern.IsMatch($content)) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "bearer_token_shape" }
        }
    }

    return $findings
}

function Invoke-ForbiddenPathAudit {
    param([string]$BasePath)

    $findings = @()
    foreach ($file in Get-ChildItem -LiteralPath $BasePath -Recurse -Force -File -ErrorAction SilentlyContinue) {
        $relative = Convert-ToPortablePath (Get-RelativePathFromBase -Path $file.FullName -BasePath $BasePath)
        $lower = $relative.ToLowerInvariant()
        $leaf = [System.IO.Path]::GetFileName($relative).ToLowerInvariant()

        if ($lower -eq ".env.example") {
            continue
        }

        if ($leaf -eq ".env" -or $leaf.StartsWith(".env.")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "env_file" }
        }
        if ($lower.StartsWith("backend/app/storage/") -or $lower.StartsWith("storage/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_storage" }
        }
        if ($lower.StartsWith("backend/storage/") -or $lower.StartsWith("deploy/backend-storage/") -or $lower.StartsWith("deploy/db/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_storage" }
        }
        if ($lower.StartsWith(".logs/") -or $lower.StartsWith("logs/") -or $lower.StartsWith("backend/logs/") -or $lower.StartsWith("frontend/logs/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_logs" }
        }
        if ($lower.StartsWith("history/") -or $lower.StartsWith("histories/") -or $lower.StartsWith("backend/history/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_history" }
        }
        if (
            $lower.StartsWith("runtime/") -and
            (-not (
                $lower.StartsWith("runtime/node/") -or
                $lower.StartsWith("runtime/python/") -or
                $lower.StartsWith("runtime/python-deps/")
            ))
        ) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "unexpected_runtime_path" }
        }
        if ($leaf -in @("agent_runtime.json", "agent_runtime.secrets.json", "agent_runtime.secret.key")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "agent_runtime_secret_state" }
        }
        if (
            $leaf.EndsWith(".db") -or
            $leaf.EndsWith(".sqlite") -or
            $leaf.EndsWith(".sqlite3") -or
            $leaf.EndsWith(".log")
        ) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_artifact" }
        }
    }

    return $findings
}

function Invoke-PlannedPortablePathAudit {
    param([object[]]$SourceFiles)

    $findings = @()
    foreach ($file in $SourceFiles) {
        $relative = Convert-ToPortablePath (Get-RelativePath $file.FullName)
        $lower = $relative.ToLowerInvariant()
        $leaf = [System.IO.Path]::GetFileName($relative).ToLowerInvariant()

        if ($lower -eq ".env.example") {
            continue
        }

        if ($leaf -eq ".env" -or $leaf.StartsWith(".env.")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "env_file" }
        }
        if (
            $lower.StartsWith("backend/app/storage/") -or
            $lower.StartsWith("backend/storage/") -or
            $lower.StartsWith("deploy/backend-storage/") -or
            $lower.StartsWith("deploy/db/") -or
            $lower.StartsWith("storage/")
        ) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_storage" }
        }
        if ($lower.StartsWith(".logs/") -or $lower.StartsWith("logs/") -or $lower.StartsWith("backend/logs/") -or $lower.StartsWith("frontend/logs/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_logs" }
        }
        if ($lower.StartsWith("history/") -or $lower.StartsWith("histories/") -or $lower.StartsWith("backend/history/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_history" }
        }
        if ($lower.StartsWith("runtime/")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "preexisting_runtime_tree" }
        }
        if ($leaf -in @("agent_runtime.json", "agent_runtime.secrets.json", "agent_runtime.secret.key")) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "agent_runtime_secret_state" }
        }
        if (
            $leaf.EndsWith(".db") -or
            $leaf.EndsWith(".sqlite") -or
            $leaf.EndsWith(".sqlite3") -or
            $leaf.EndsWith(".log")
        ) {
            $findings += [pscustomobject]@{ Path = $relative; Rule = "runtime_artifact" }
        }
    }

    return $findings
}

function Test-PortableRuntime {
    param([string]$PackageRoot)

    $nodeExe = Join-Path $PackageRoot "runtime\node\node.exe"
    $pythonExe = Join-Path $PackageRoot "runtime\python\python.exe"
    $pythonDeps = Join-Path $PackageRoot "runtime\python-deps"
    $vitePackage = Join-Path $PackageRoot "frontend\node_modules\vite\package.json"
    $reactPackage = Join-Path $PackageRoot "frontend\node_modules\react\package.json"

    foreach ($path in @($nodeExe, $pythonExe, $pythonDeps, $vitePackage, $reactPackage)) {
        if (-not (Test-Path $path)) {
            throw "Portable package is missing required runtime file: $path"
        }
    }

    & $nodeExe --version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Portable node.exe did not run successfully."
    }

    $previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        $env:PYTHONPATH = $pythonDeps
        & $pythonExe -c "import fastapi, uvicorn, pydantic_core, sqlalchemy, aiosqlite, alembic, openpyxl, tushare, akshare; print('portable python deps ok')" *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Portable Python dependencies failed import validation."
        }
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

$nodeSource = Resolve-NodeSource
$pythonSource = Resolve-PythonSource
$pythonDepsSource = Find-BackendSitePackages
$frontendNodeModules = Join-Path $Root "frontend\node_modules"

if (-not (Test-Path (Join-Path $frontendNodeModules "vite\package.json"))) {
    throw "Missing frontend node_modules. Run npm.cmd --prefix frontend install before packaging."
}

$sourceFiles = Get-PortableSourceFiles -SourceDir $Root
Write-Step "Output zip: $OutputPath"
Write-Step "Node source: $nodeSource"
Write-Step "Python source: $pythonSource"
Write-Step "Python deps source: $pythonDepsSource"
Write-Step "Portable source files: $($sourceFiles.Count)"

if ($DryRun) {
    $scanFindings = Invoke-SecretScan -BasePath $Root
    if ($scanFindings.Count -gt 0) {
        Write-Host "Secret scan failed:" -ForegroundColor Red
        $scanFindings | Select-Object -Unique Path, Rule | Format-Table -AutoSize
        throw "Dry run stopped because potential secrets were found."
    }
    Write-Step "Dry run passed. No zip was created."
    return
}

$stageFull = Get-FullPath $StageRoot
if (-not (Test-IsUnderRoot -Path $stageFull -Parent $Root)) {
    throw "Refusing to clean staging path outside project root: $stageFull"
}

if (Test-Path $StageRoot) {
    Write-Step "Cleaning staging directory"
    Remove-Item -LiteralPath $StageRoot -Recurse -Force
}

if (Test-Path $OutputPath) {
    throw "Output file already exists: $OutputPath"
}

New-Item -ItemType Directory -Force -Path $StageProject | Out-Null

Write-Step "Copying portable source"
Copy-PortableSourceTree -SourceDir $Root -DestinationDir $StageProject

Write-Step "Copying frontend node_modules"
Invoke-RobocopyCopy -Source $frontendNodeModules -Destination (Join-Path $StageProject "frontend\node_modules")

Write-Step "Copying Node runtime"
Invoke-RobocopyCopy -Source $nodeSource -Destination (Join-Path $StageProject "runtime\node")

Write-Step "Copying Python runtime"
Invoke-RobocopyCopy -Source $pythonSource -Destination (Join-Path $StageProject "runtime\python")

Write-Step "Copying Python dependencies"
Invoke-RobocopyCopy -Source $pythonDepsSource -Destination (Join-Path $StageProject "runtime\python-deps")

Write-Step "Validating portable runtime"
Test-PortableRuntime -PackageRoot $StageProject

Write-Step "Auditing package paths"
$pathFindings = Invoke-ForbiddenPathAudit -BasePath $StageProject
if ($pathFindings.Count -gt 0) {
    Write-Host "Forbidden paths found:" -ForegroundColor Red
    $pathFindings | Select-Object -Unique Path, Rule | Format-Table -AutoSize
    throw "Package audit stopped because forbidden runtime paths were found."
}

Write-Step "Scanning package source for secrets"
$secretFindings = Invoke-SecretScan -BasePath $StageProject
if ($secretFindings.Count -gt 0) {
    Write-Host "Secret scan failed:" -ForegroundColor Red
    $secretFindings | Select-Object -Unique Path, Rule | Format-Table -AutoSize
    throw "Package audit stopped because potential secrets were found."
}

Write-Step "Creating zip on Desktop"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
Compress-Archive -LiteralPath $StageProject -DestinationPath $OutputPath -CompressionLevel Optimal

Write-Step "Portable package created: $OutputPath"
