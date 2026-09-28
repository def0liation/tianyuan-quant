param(
  [string]$DrillRoot = ".tmp\storage-offhost-restore-drill"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$allowedDrillRoot = Join-Path $projectRoot ".tmp\storage-offhost-restore-drill"

function Resolve-ProjectPath([string]$PathValue) {
  $candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) {
    $PathValue
  } else {
    Join-Path $projectRoot $PathValue
  }
  return [System.IO.Path]::GetFullPath($candidate)
}

function Assert-UnderRoot([string]$PathValue, [string]$RootValue, [string]$Label) {
  $fullPath = [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\')
  $fullRoot = [System.IO.Path]::GetFullPath($RootValue).TrimEnd('\')
  if ($fullPath.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
      $fullPath.StartsWith($fullRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    return
  }
  throw "$Label must stay under $fullRoot"
}

function Get-RelativePath([string]$RootValue, [string]$PathValue) {
  $fullRoot = [System.IO.Path]::GetFullPath($RootValue).TrimEnd('\') + '\'
  $fullPath = [System.IO.Path]::GetFullPath($PathValue)
  if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path must stay under $fullRoot"
  }
  return $fullPath.Substring($fullRoot.Length).Replace('\', '/')
}

function Get-FileSha256([string]$PathValue) {
  return (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-StorageCategory([string]$RelativePath) {
  $normalized = $RelativePath.Replace('\', '/').ToLowerInvariant()
  if ($normalized -eq "agent_runtime.secrets.json") { return "secret_vault" }
  if ($normalized -eq "agent_runtime.secret.key") { return "secret_key" }
  if ($normalized.StartsWith("runs/")) { return "run_artifact" }
  if ($normalized.StartsWith("plugin_artifacts/")) { return "plugin_artifact" }
  return "backend_storage"
}

function Copy-DirectoryContents([string]$SourceDir, [string]$DestinationDir) {
  New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
  foreach ($child in Get-ChildItem -LiteralPath $SourceDir -Force) {
    Copy-Item -LiteralPath $child.FullName -Destination $DestinationDir -Recurse -Force
  }
}

function New-Manifest([string]$StorageRoot) {
  $files = Get-ChildItem -LiteralPath $StorageRoot -Recurse -File | Sort-Object FullName
  $items = @()
  foreach ($file in $files) {
    $relativePath = Get-RelativePath $StorageRoot $file.FullName
    $items += [pscustomobject][ordered]@{
      relative_path = $relativePath
      category = Get-StorageCategory $relativePath
      size_bytes = [int64]$file.Length
      sha256 = Get-FileSha256 $file.FullName
    }
  }
  return $items
}

function Assert-ManifestMatches([string]$StorageRoot, [array]$ManifestItems) {
  $actualItems = New-Manifest $StorageRoot
  if ($actualItems.Count -ne $ManifestItems.Count) {
    throw "Restored file count mismatch: expected $($ManifestItems.Count), got $($actualItems.Count)."
  }

  $actualByPath = @{}
  foreach ($item in $actualItems) {
    $actualByPath[[string]$item.relative_path] = $item
  }

  foreach ($expected in $ManifestItems) {
    $relativePath = [string]$expected.relative_path
    if (-not $actualByPath.ContainsKey($relativePath)) {
      throw "Restored storage is missing $relativePath."
    }
    $actual = $actualByPath[$relativePath]
    if ([string]$actual.sha256 -ne [string]$expected.sha256) {
      throw "Restored checksum mismatch for $relativePath."
    }
    if ([int64]$actual.size_bytes -ne [int64]$expected.size_bytes) {
      throw "Restored size mismatch for $relativePath."
    }
  }
}

$drillRootPath = Resolve-ProjectPath $DrillRoot
Assert-UnderRoot $drillRootPath $allowedDrillRoot "DrillRoot"

$runId = "run-{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
$runRoot = Join-Path $drillRootPath $runId
$sourceStorage = Join-Path $runRoot "source\deploy\backend-storage"
$localBundleRoot = Join-Path $runRoot "local-backup"
$localBundleStorage = Join-Path $localBundleRoot "backend-storage"
$offHostRoot = Join-Path $runRoot "simulated-offhost"
$offHostStorage = Join-Path $offHostRoot "backend-storage"
$restoreStorage = Join-Path $runRoot "restored\backend-storage"
New-Item -ItemType Directory -Force -Path $sourceStorage, $localBundleRoot, $offHostRoot, $restoreStorage | Out-Null

$runsDir = Join-Path $sourceStorage "runs"
$pluginDir = Join-Path $sourceStorage "plugin_artifacts\artifact-drill"
New-Item -ItemType Directory -Force -Path $runsDir, $pluginDir | Out-Null

$runtimeState = [ordered]@{
  version = 1
  active_profile_id = "profile-drill"
  profiles = @(
    [ordered]@{
      id = "profile-drill"
      provider = "openai"
      api_key_ref = "runtime-secret:v1:agent_runtime:profile-drill:api_key"
      api_key_masked = "sk-...drill"
    }
  )
}
$runtimeState | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $sourceStorage "agent_runtime.json") -Encoding UTF8

$vaultState = [ordered]@{
  version = 1
  updated_at = "2026-05-31T00:00:00+00:00"
  secrets = [ordered]@{
    "runtime-secret:v1:agent_runtime:profile-drill:api_key" = [ordered]@{
      alg = "HMAC-SHA256-STREAM"
      nonce = "drill-nonce"
      ciphertext = "drill-ciphertext"
      tag = "drill-tag"
      key_source = "LOCAL_KEY_FILE"
      updated_at = "2026-05-31T00:00:00+00:00"
    }
  }
}
$vaultState | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $sourceStorage "agent_runtime.secrets.json") -Encoding UTF8
Set-Content -LiteralPath (Join-Path $sourceStorage "agent_runtime.secret.key") -Value "drill-local-key-material-not-production" -Encoding UTF8

$jobState = [ordered]@{
  jobs = @(
    [ordered]@{
      job_id = "JOB_STORAGE_DRILL"
      run_id = "RUN_STORAGE_DRILL"
      status = "COMPLETED"
    }
  )
}
$jobState | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $sourceStorage "analysis_jobs.json") -Encoding UTF8
Set-Content -LiteralPath (Join-Path $sourceStorage "ops_events.jsonl") -Value '{"event_type":"storage_drill","level":"info"}' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $runsDir "RUN_STORAGE_DRILL.json") -Value '{"run_id":"RUN_STORAGE_DRILL","status":"COMPLETED"}' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $pluginDir "package.bin") -Value "plugin artifact drill payload" -Encoding UTF8

$manifestItems = New-Manifest $sourceStorage
$manifest = [ordered]@{
  status = "created"
  run_id = $runId
  created_at = (Get-Date).ToUniversalTime().ToString("o")
  scope = "backend-storage-secret-vault-key-drill"
  file_count = $manifestItems.Count
  total_bytes = [int64](($manifestItems | Measure-Object -Property size_bytes -Sum).Sum)
  items = $manifestItems
}
$localManifest = Join-Path $localBundleRoot "backend-storage-manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $localManifest -Encoding UTF8

Copy-DirectoryContents $sourceStorage $localBundleStorage
Copy-DirectoryContents $localBundleRoot $offHostRoot
Copy-DirectoryContents $offHostStorage $restoreStorage

$offHostManifest = Join-Path $offHostRoot "backend-storage-manifest.json"
if (-not (Test-Path -LiteralPath $offHostManifest)) {
  throw "Off-host manifest was not copied."
}
$copiedManifest = Get-Content -LiteralPath $offHostManifest -Raw | ConvertFrom-Json
Assert-ManifestMatches $offHostStorage $copiedManifest.items
Assert-ManifestMatches $restoreStorage $copiedManifest.items

$secretVaultPath = Join-Path $restoreStorage "agent_runtime.secrets.json"
$secretKeyPath = Join-Path $restoreStorage "agent_runtime.secret.key"
if (-not (Test-Path -LiteralPath $secretVaultPath)) { throw "Secret vault was not restored." }
if (-not (Test-Path -LiteralPath $secretKeyPath)) { throw "Secret key file was not restored." }

$categoryCounts = @{}
foreach ($item in $copiedManifest.items) {
  $category = [string]$item.category
  if (-not $categoryCounts.ContainsKey($category)) { $categoryCounts[$category] = 0 }
  $categoryCounts[$category] += 1
}

$result = [ordered]@{
  status = "ok"
  run_id = $runId
  source_storage = $sourceStorage
  local_bundle_storage = $localBundleStorage
  offhost_storage = $offHostStorage
  restored_storage = $restoreStorage
  manifest_file = $offHostManifest
  file_count = [int]$copiedManifest.file_count
  total_bytes = [int64]$copiedManifest.total_bytes
  category_counts = $categoryCounts
  copied = $true
  restored = $true
  verified = $true
  secret_vault_verified = $true
  secret_key_verified = $true
}

Write-Output ($result | ConvertTo-Json -Depth 6)
