param(
  [int]$Port = 4177,
  [string[]]$Routes = @(),
  [string[]]$SignalOpsRequiredText = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$frontendRoot = Join-Path $repoRoot "frontend"
$distIndex = Join-Path $frontendRoot "dist\index.html"
$routeManifest = Join-Path $frontendRoot "src\routeManifest.json"
$logDir = Join-Path $repoRoot ".logs"
$manifest = Get-Content -LiteralPath $routeManifest -Raw -Encoding UTF8 | ConvertFrom-Json

if (-not $Routes -or $Routes.Count -eq 0) {
  $manifestRoutes = @()
  foreach ($group in $manifest.navGroups) {
    foreach ($item in $group.items) {
      $manifestRoutes += [string]$item.path
    }
  }
  foreach ($route in $manifest.researchRoutes) {
    $manifestRoutes += [string]$route
  }
  foreach ($redirect in $manifest.redirects) {
    $manifestRoutes += [string]$redirect.from
  }
  foreach ($route in $manifest.legacyRoutes) {
    $manifestRoutes += [string]$route
  }
  $Routes = $manifestRoutes | Sort-Object -Unique
}

if (-not $SignalOpsRequiredText -or $SignalOpsRequiredText.Count -eq 0) {
  $SignalOpsRequiredText = @(
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("57O757uf6Ieq5Yqo6L+Q6KGM")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5omT5byA5a6h5p+l56qX5Y+j")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5a6h5p+l56qX5Y+j")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5b6F5a6h5p+l")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6YCa6L+H5a6h5p+l")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6amz5Zue5bu66K6u")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("57un57ut6KeC5a+f")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6KaB5rGC6KGl5LiB")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("6L6555WM6K6+572u")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5byC5bi45o6l566h")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5LuF5qih5ouf77ya5piv")),
    [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("55yf5a6e5Lqk5piT77ya5ZCm"))
  )
}

function Assert-ResearchBridgeDocBoundaryMarkers {
  param(
    [array]$MarkerSources
  )

  foreach ($markerSource in $MarkerSources) {
    $sourceName = [string]$markerSource["Name"]
    $sourceText = [string]$markerSource["Text"]

    foreach ($marker in $markerSource["Markers"]) {
      if (-not $sourceText.Contains($marker)) {
        throw "$sourceName is missing the Research bridge strong-conclusion marker: $marker"
      }
    }
  }
}

function Assert-TypeScriptInterfaceBoundaryMarkers {
  param(
    [string]$Source,
    [string]$InterfaceName,
    [string[]]$Markers
  )

  $escapedInterfaceName = [regex]::Escape($InterfaceName)
  $interfacePattern = "export\s+interface\s+" + $escapedInterfaceName + "\s*\{(?<body>[\s\S]*?)\r?\n\}"
  $interfaceMatch = [regex]::Match($Source, $interfacePattern)
  if (-not $interfaceMatch.Success) {
    throw "types source is missing interface $InterfaceName"
  }

  $interfaceBody = $interfaceMatch.Groups["body"].Value
  foreach ($marker in $Markers) {
    if (-not $interfaceBody.Contains($marker)) {
      throw "$InterfaceName is missing literal Research bridge boundary marker: $marker"
    }
  }
}

$auditPageSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\audit\AuditLogPage.tsx") -Raw -Encoding UTF8
$auditClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\auditClient.ts") -Raw -Encoding UTF8
$appSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\App.tsx") -Raw -Encoding UTF8
$appShellSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\layout\AppShell.tsx") -Raw -Encoding UTF8
$sidebarSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\layout\Sidebar.tsx") -Raw -Encoding UTF8
$topBarSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\layout\TopBar.tsx") -Raw -Encoding UTF8
$materialSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\common\Material.tsx") -Raw -Encoding UTF8
$indexCssSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\index.css") -Raw -Encoding UTF8
$postcssConfigSource = Get-Content -LiteralPath (Join-Path $frontendRoot "postcss.config.js") -Raw -Encoding UTF8
$errorBoundarySource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\common\ErrorBoundary.tsx") -Raw -Encoding UTF8
$frontendSafetyGuardSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\guards\frontendSafetyGuard.ts") -Raw -Encoding UTF8
$analysisClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\analysisClient.ts") -Raw -Encoding UTF8
$backendStoreSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\store\useBackendStore.ts") -Raw -Encoding UTF8
$agentRuntimeClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\agentRuntimeClient.ts") -Raw -Encoding UTF8
$httpClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\httpClient.ts") -Raw -Encoding UTF8
$backtestClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\backtestClient.ts") -Raw -Encoding UTF8
$portfolioClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\portfolioClient.ts") -Raw -Encoding UTF8
$caseLibraryClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\caseLibraryClient.ts") -Raw -Encoding UTF8
$knowledgeClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\knowledgeClient.ts") -Raw -Encoding UTF8
$knowledgePageSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\knowledge\KnowledgeIterationPage.tsx") -Raw -Encoding UTF8
$researchClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\researchClient.ts") -Raw -Encoding UTF8
$typesSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\types\index.ts") -Raw -Encoding UTF8
$researchBridgeTypeBoundaryMarkers = @(
  "evidence_usage: 'supporting_only'",
  "supporting_only: true",
  "simulation_only: true",
  "is_real_trade: false",
  "strong_conclusion_allowed: false"
)
foreach ($researchBridgeInterface in @("ResearchBacktestVerdictInputsResponse", "ResearchSignalOpsEvidenceResponse")) {
  Assert-TypeScriptInterfaceBoundaryMarkers -Source $typesSource -InterfaceName $researchBridgeInterface -Markers $researchBridgeTypeBoundaryMarkers
}
$runCompareSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\compare\RunComparePage.tsx") -Raw -Encoding UTF8
$analysisStoreSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\store\useAnalysisStore.ts") -Raw -Encoding UTF8
$dashboardSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\dashboard\DashboardPage.tsx") -Raw -Encoding UTF8
$dashboardWorkbenchSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\utils\dashboardWorkbench.ts") -Raw -Encoding UTF8
$dataProvenanceSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\utils\dataProvenance.ts") -Raw -Encoding UTF8
$agentCanonicalSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\utils\agentCanonical.ts") -Raw -Encoding UTF8
$newTaskSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\task\NewTaskPage.tsx") -Raw -Encoding UTF8
$executionSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\execution\ExecutionPage.tsx") -Raw -Encoding UTF8
$permissionSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\permission\PermissionMatrixPage.tsx") -Raw -Encoding UTF8
$runHydrationSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\hooks\useCurrentRunHydration.ts") -Raw -Encoding UTF8
$historySelectorSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\history\HistorySelector.tsx") -Raw -Encoding UTF8
$runHistoryHelperSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\utils\runHistory.ts") -Raw -Encoding UTF8
$operatorContextSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\store\operatorContext.ts") -Raw -Encoding UTF8
$streamClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\streamClient.ts") -Raw -Encoding UTF8
$liveRunSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\live\LiveRunConsole.tsx") -Raw -Encoding UTF8
$dataReliabilitySource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\dataReliability\DataReliabilityPage.tsx") -Raw -Encoding UTF8
$dataReliabilityClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\dataReliabilityClient.ts") -Raw -Encoding UTF8
$dataPipelineClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\dataPipelineClient.ts") -Raw -Encoding UTF8
$dataCompressionSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\data\DataCompressionPage.tsx") -Raw -Encoding UTF8
$klineClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\klineClient.ts") -Raw -Encoding UTF8
$globalMarketClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\globalMarketClient.ts") -Raw -Encoding UTF8
$globalMarketPageSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\globalMarket\GlobalMarketPage.tsx") -Raw -Encoding UTF8
$backendStatusSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\backend\BackendStatusPage.tsx") -Raw -Encoding UTF8
$agentRuntimeSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\agents\AgentRuntimeSection.tsx") -Raw -Encoding UTF8
$settingsSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\settings\SettingsPage.tsx") -Raw -Encoding UTF8
$signalOpsSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\signalops\SignalOpsPage.tsx") -Raw -Encoding UTF8
$signalOpsClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\signalopsClient.ts") -Raw -Encoding UTF8
$technicalKlineSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\technical\TechnicalKlinePage.tsx") -Raw -Encoding UTF8
$technicalKlineCaseGovernanceSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\technical\TechnicalKlineCaseGovernanceCard.tsx") -Raw -Encoding UTF8
$technicalKlineClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\technicalKlineClient.ts") -Raw -Encoding UTF8
$guardrailHubSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\guardrail\GuardrailHubPage.tsx") -Raw -Encoding UTF8
$quantCoreSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\quantCore\QuantCorePage.tsx") -Raw -Encoding UTF8
$backtestSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\backtest\BacktestPage.tsx") -Raw -Encoding UTF8
$portfolioSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\portfolio\PortfolioPage.tsx") -Raw -Encoding UTF8
$caseLibrarySource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\caseLibrary\CaseLibraryPage.tsx") -Raw -Encoding UTF8
$knowledgeVersionsSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\evaluation\KnowledgeVersionsPage.tsx") -Raw -Encoding UTF8
$evaluationSandboxSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\evaluation\EvaluationSandboxPage.tsx") -Raw -Encoding UTF8
$backendTuningSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\tuning\BackendTuningPage.tsx") -Raw -Encoding UTF8
$configVersionsSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\config\ConfigVersionsPage.tsx") -Raw -Encoding UTF8
$configClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\configClient.ts") -Raw -Encoding UTF8
$pluginRegistrySource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\plugins\PluginRegistryPage.tsx") -Raw -Encoding UTF8
$pluginClientSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\api\pluginClient.ts") -Raw -Encoding UTF8
$agentDagSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\dag\AgentDagPage.tsx") -Raw -Encoding UTF8
$agentDebateSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\debate\AgentDebatePage.tsx") -Raw -Encoding UTF8
$finalWriterSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\final\FinalWriterPage.tsx") -Raw -Encoding UTF8
$antiConclusionSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\final\AntiConclusionPage.tsx") -Raw -Encoding UTF8
$researchLoopsSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\research\ResearchLoopsPage.tsx") -Raw -Encoding UTF8
$researchTracesSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\components\research\ResearchTracesPage.tsx") -Raw -Encoding UTF8
$researchClosureBrowserSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-research-closure-browser.mjs") -Raw -Encoding UTF8
$researchClosureLiveSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-research-closure-live.ps1") -Raw -Encoding UTF8
$strictAuthBrowserSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-strict-auth-browser.mjs") -Raw -Encoding UTF8
$strictAuthBrowserWrapperSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-strict-auth-browser.ps1") -Raw -Encoding UTF8
$strictAuthSmokeRequirementsPath = Join-Path $repoRoot "backend\requirements-smoke.txt"
$strictAuthSmokeRequirementsSource = if (Test-Path -LiteralPath $strictAuthSmokeRequirementsPath) {
  Get-Content -LiteralPath $strictAuthSmokeRequirementsPath -Raw -Encoding UTF8
} else {
  ""
}
$strictAuthBrowserMatrixSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-strict-auth-browser-matrix.ps1") -Raw -Encoding UTF8
$preMergeValidationSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\pre-merge-validation.ps1") -Raw -Encoding UTF8
$testBackendSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\test-backend.ps1") -Raw -Encoding UTF8
$analysisWorkerSmokeSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-analysis-worker.ps1") -Raw -Encoding UTF8
$analysisWorkerScriptSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\analysis-worker.ps1") -Raw -Encoding UTF8
$packageSource = Get-Content -LiteralPath (Join-Path $repoRoot "package.json") -Raw -Encoding UTF8
$frontendResponsiveSmokeSource = Get-Content -LiteralPath (Join-Path $repoRoot "scripts\smoke-frontend-responsive.mjs") -Raw -Encoding UTF8
$frontendRedesignGuideSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\FRONTEND_REDESIGN_GUIDE.md") -Raw -Encoding UTF8
$developmentGuideSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\DEVELOPMENT_GUIDE.md") -Raw -Encoding UTF8
$testingGuideSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\TESTING_GUIDE.md") -Raw -Encoding UTF8
$apiContractSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\API_CONTRACT.md") -Raw -Encoding UTF8
$projectAssessmentSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\PROJECT_DEVELOPMENT_ASSESSMENT.md") -Raw -Encoding UTF8
$quantImprovementPlanSource = Get-Content -LiteralPath (Join-Path $repoRoot "docs\QUANT_SYSTEM_IMPROVEMENT_PLAN.md") -Raw -Encoding UTF8
$researchBridgeDocMarkerSources = @(
  @{
    Name = "DEVELOPMENT_GUIDE"
    Text = $developmentGuideSource
    Markers = @("MFE/MAE-only evidence", "strong_conclusion_allowed=false")
  }
  @{
    Name = "API_CONTRACT"
    Text = $apiContractSource
    Markers = @("strong_conclusion_allowed=false")
  }
  @{
    Name = "TESTING_GUIDE"
    Text = $testingGuideSource
    Markers = @(
      "strong_conclusion_allowed=false",
      'SignalOps tick evidence reaches `ResearchVerdictInputs` as supporting-only evidence while preserving `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false`'
    )
  }
  @{
    Name = "PROJECT_DEVELOPMENT_ASSESSMENT"
    Text = $projectAssessmentSource
    Markers = @("strong_conclusion_allowed=false")
  }
  @{
    Name = "QUANT_SYSTEM_IMPROVEMENT_PLAN"
    Text = $quantImprovementPlanSource
    Markers = @("strong_conclusion_allowed=false")
  }
)
Assert-ResearchBridgeDocBoundaryMarkers -MarkerSources $researchBridgeDocMarkerSources
$analysisJobStoreSource = Get-Content -LiteralPath (Join-Path $repoRoot "backend\app\core\analysis_job_store.py") -Raw -Encoding UTF8
$scenarioTemplatesSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\utils\scenarioTemplates.ts") -Raw -Encoding UTF8
$mockScenariosSource = Get-Content -LiteralPath (Join-Path $frontendRoot "src\mock\scenarios.ts") -Raw -Encoding UTF8
if (-not $postcssConfigSource.Contains("const postcss = require('postcss')") -or
    -not $postcssConfigSource.Contains("const tailwindcss = require('tailwindcss')") -or
    -not $postcssConfigSource.Contains("const autoprefixer = require('autoprefixer')") -or
    -not $postcssConfigSource.Contains("tailwindGeneratedSourcePath = require.resolve('tailwindcss/package.json')") -or
    -not $postcssConfigSource.Contains("fallbackSourceInput = postcss.parse('', { from: tailwindGeneratedSourcePath }).source.input") -or
    -not $postcssConfigSource.Contains("function tailwindGeneratedSourcePlugin") -or
    -not $postcssConfigSource.Contains("postcssPlugin: 'super-tailwind-generated-source'") -or
    -not $postcssConfigSource.Contains("root.walkDecls((declaration)") -or
    -not $postcssConfigSource.Contains("declaration.source?.input?.file") -or
    -not $postcssConfigSource.Contains("declaration.source = {") -or
    -not $postcssConfigSource.Contains("plugins: [tailwindcss(), autoprefixer(), tailwindGeneratedSourcePlugin()]")) {
  throw "PostCSS generated source fallback is missing; Vite URL rewrite warnings may hide real asset issues"
}
if (-not $frontendSafetyGuardSource.Contains("export function paperTradingBoundaryViolation") -or
    -not $frontendSafetyGuardSource.Contains("paperTrading.simulation_only === false") -or
    -not $frontendSafetyGuardSource.Contains("paperTrading.is_real_trade === true") -or
    -not $frontendSafetyGuardSource.Contains("namespace !== SIM_ORDER_NAMESPACE") -or
    -not $frontendSafetyGuardSource.Contains("!action.startsWith('SIM_')") -or
    -not $frontendSafetyGuardSource.Contains("paperTradingBoundaryViolation(run.paperTrading) === null") -or
    -not $analysisClientSource.Contains("function assertPaperTradingBoundary") -or
    -not $analysisClientSource.Contains("paperTrading.simulation_only === false") -or
    -not $analysisClientSource.Contains("paperTrading.is_real_trade === true") -or
    -not $analysisClientSource.Contains("assertPaperTradingBoundary(value.paperTrading as Record<string, unknown>)") -or
    -not $analysisClientSource.Contains("function assertPortfolioRunBoundary") -or
    -not $analysisClientSource.Contains("function isStrongEvidenceValue") -or
    -not $analysisClientSource.Contains("normalized === 'RESEARCH_GRADE'") -or
    -not $analysisClientSource.Contains("normalized === 'PRIMARY_EVIDENCE_READY'") -or
    -not $analysisClientSource.Contains("assertPortfolioRunBoundary(value.portfolio as Record<string, unknown>)") -or
    -not $analysisClientSource.Contains("function assertAgentNodeBoundary") -or
    -not $analysisClientSource.Contains("agent node must declare simulation-only evidence boundary") -or
    -not $analysisClientSource.Contains("agent node evidence must stay simulation-only and non-strong") -or
    -not $analysisClientSource.Contains("function assertQuantCoreBoundary") -or
    -not $analysisClientSource.Contains("quantCore must declare read-only simulation boundary") -or
    -not $analysisClientSource.Contains("quantCore evidence must stay read-only, simulation-only, and non-strong") -or
    -not $analysisClientSource.Contains("analysis run node") -or
    -not $analysisClientSource.Contains("portfolio evidence must stay supporting-only and simulation-only") -or
    -not $analysisClientSource.Contains('paperTrading ${label} action must use SIM_*') -or
    -not $typesSource.Contains("status: 'PENDING' | 'ACTIVE' | 'WARN' | 'SKIPPED'") -or
    -not $typesSource.Contains("evidenceUsage?: 'supporting_only'") -or
    -not $typesSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $typesSource.Contains("evidenceStrength: 'LOW' | 'MEDIUM' | 'PENDING'") -or
    $typesSource.Contains("evidenceStrength: 'SUPPORTING_ONLY' | 'LOW' | 'MEDIUM' | 'PENDING'") -or
    -not $typesSource.Contains("simulationOnly: boolean") -or
    -not $typesSource.Contains("isRealTrade: boolean") -or
    -not $typesSource.Contains("strongConclusionAllowed?: boolean") -or
    -not $typesSource.Contains("strongConclusionAllowed: boolean") -or
    -not $typesSource.Contains("actionBoundary: 'READ_ONLY_NO_PERMISSION_CHANGE'") -or
    -not $typesSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $typesSource.Contains("simulation_only: boolean") -or
    -not $typesSource.Contains("is_real_trade: boolean") -or
    -not $typesSource.Contains("allowed_order_namespace?: 'SIM_*'") -or
    -not $typesSource.Contains('latest_action?: `SIM_${string}`') -or
    -not $mockScenariosSource.Contains("simulation_only: true, is_real_trade: false, allowed_order_namespace: 'SIM_*', latest_action: 'SIM_HOLD'")) {
  throw "frontendSafetyGuard is missing executable paper-trading simulation-only / SIM_* boundary checks"
}
$newTaskImportQualityText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5a+85YWl6LSo6YeP5a2Y5Zyo"))
$newTaskCurrentSymbolAbsentText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5b2T5YmN6IKh56Wo5LiN5Zyo5omA6YCJ5b+r54Wn5Lit"))
$newTaskBrokerImportTemplateText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5Yi45ZWG5a+85YWl5qih5p2/"))
$newTaskBrokerTemplateWarningText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5Yi45ZWG5qih5p2/6K2m5ZGK"))
$newTaskPreTaskRiskPromptText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5Lu75Yqh5YmN5oyB5LuT6aOO6Zmp5o+Q56S6"))
$dashboardResearchSamplePermissionText = [string]::Concat([char[]](0x7814,0x7A76,0x5B9E,0x9A8C,0x5BA4,0x6837,0x4F8B,0x91CD,0x5EFA,0x9700,0x8981,0x7814,0x7A76,0x5458,0x6743,0x9650))
$backendExpiredLeaseText = [string]::Concat([char[]](0x4E2A,0x8FC7,0x671F,0x79DF,0x7EA6))
$backendHealthTrendText = [string]::Concat([char[]](0x5065,0x5EB7,0x8D8B,0x52BF))
$backendSourceErrorsText = [string]::Concat([char[]](0x6570,0x636E,0x6E90,0x9519,0x8BEF))
$researchWorkflowPermissionText = [string]::Concat([char[]](0x7814,0x7A76,0x5B9E,0x9A8C,0x5BA4,0x5DE5,0x4F5C,0x6D41,0x5199,0x5165,0x9700,0x8981,0x7814,0x7A76,0x5458,0x6743,0x9650))
$bottomRedirect = @($manifest.redirects | Where-Object { $_.from -eq "/bottom-research" -and $_.to -eq "/quant-core" })
$quantEngineRedirect = @($manifest.redirects | Where-Object { $_.from -eq "/quant-engine" -and $_.to -eq "/quant-core" })
$scenarioRedirect = @($manifest.redirects | Where-Object { $_.from -eq "/scenario" -and $_.to -eq "/quant-core" })
$navPaths = @()
foreach ($group in $manifest.navGroups) {
  foreach ($item in $group.items) {
    $navPaths += [string]$item.path
  }
}
$guardrailLegacyRoutes = @("/dvg-gate", "/risk", "/trade-micro")
$tsxFiles = Get-ChildItem -LiteralPath (Join-Path $frontendRoot "src") -Recurse -File -Filter "*.tsx"
$badgeImportHits = @($tsxFiles | Select-String -SimpleMatch -Pattern "from '../common/Badge'", "from './common/Badge'")
$cardImportHits = @($tsxFiles | Select-String -SimpleMatch -Pattern "from '../common/Card'", "from './common/Card'")
$materialImportHits = @($tsxFiles | Select-String -SimpleMatch -Pattern "from '../common/Material'", "from './common/Material'")

if ($auditPageSource -notmatch "api/auditClient" -or $auditPageSource -notmatch "getAuditLog\(currentRun\.runId\)") {
  throw "AuditLogPage is not wired to frontend/src/api/auditClient.ts"
}
if (-not $auditClientSource.Contains("assertAuditLogEvents") -or
    -not $auditClientSource.Contains("assertAuditLogEvent") -or
    -not $auditClientSource.Contains("requireString(event, 'timestamp'") -or
    -not $auditClientSource.Contains("requireString(event, 'runId'") -or
    -not $auditClientSource.Contains("requireString(event, 'eventType'") -or
    -not $auditClientSource.Contains("requireString(event, 'statusBefore'") -or
    -not $auditClientSource.Contains("requireString(event, 'statusAfter'") -or
    -not $auditClientSource.Contains("requireString(event, 'inputHash'") -or
    -not $auditClientSource.Contains("requireString(event, 'outputHash'") -or
    -not $auditClientSource.Contains("requireString(event, 'auditId'") -or
    -not $auditClientSource.Contains(".then(assertAuditLogEvents)") -or
    -not $auditClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/audit`')) {
  throw "auditClient is missing audit log event response guards"
}
if ($analysisClientSource -notmatch "getAuditLogFromAuditClient") {
  throw "analysisClient.getAuditLog is not delegated to auditClient.getAuditLog"
}
if (-not $analysisClientSource.Contains("failureReasons?:") -or
    -not $analysisClientSource.Contains("sampleFailures?:") -or
    -not $analysisClientSource.Contains("successRate?:") -or
    -not $analysisClientSource.Contains("ProductionHealthTrend") -or
    -not $analysisClientSource.Contains("trend?: ProductionHealthTrend") -or
    -not $analysisClientSource.Contains("longTrend?: ProductionHealthTrend") -or
    -not $analysisClientSource.Contains("llmSuccessRateDelta?:") -or
    -not $analysisClientSource.Contains("totalTokens?:")) {
  throw "analysisClient productionHealth LLM metric type is missing success/failure/trend fields"
}
if (-not $analysisClientSource.Contains("assertBackendHealth") -or
    -not $analysisClientSource.Contains("assertStartupStatus") -or
    -not $analysisClientSource.Contains("assertBackendMetrics") -or
    -not $analysisClientSource.Contains("assertProductionHealthWindow") -or
    -not $analysisClientSource.Contains("assertProductionHealthMetric") -or
    -not $analysisClientSource.Contains("assertProductionHealthTrend") -or
    -not $analysisClientSource.Contains("request<unknown>('/health')") -or
    -not $analysisClientSource.Contains("request<unknown>('/startup/status', { timeoutMs: options.timeoutMs })") -or
    -not $analysisClientSource.Contains("request<unknown>('/metrics', { timeoutMs: 30000 }).then(assertBackendMetrics)") -or
    -not $backendStoreSource.Contains("getBackendHealth, getStartupStatus") -or
    -not $backendStoreSource.Contains("getStartupStatus({ timeoutMs: 3000 })") -or
    $backendStoreSource.Contains("request<BackendHealth>") -or
    $backendStoreSource.Contains("request<StartupStatus>")) {
  throw "Backend health/startup/metrics clients are missing unknown-first response guards or store wiring"
}
if ($analysisClientSource -notmatch "assertAnalysisRun" -or $analysisClientSource -notmatch "assertAnalysisRunSummary") {
  throw "analysisClient is missing analysis run response-shape guards"
}
if (-not $auditPageSource.Contains("function mergeAuditLogEvents") -or
    -not $auditPageSource.Contains("const { currentRun, liveEvents, loadRunHistory } = useAnalysisStore()") -or
    -not $auditPageSource.Contains("useCachedResource<AuditLogEvent[]>(auditKey") -or
    -not $auditPageSource.Contains("mergeAuditLogEvents(currentRun.runId, fetchedAudit, currentRun.auditLog, liveEvents)")) {
  throw "AuditLogPage must merge API audit logs (via useCachedResource) with current-run and stream-derived live events"
}
if (-not $analysisClientSource.Contains("assertCreateAnalysisResponse") -or
    -not $analysisClientSource.Contains("assertStartAnalysisResponse") -or
    -not $analysisClientSource.Contains("assertAnalysisRunJobActionResponse") -or
    -not $analysisClientSource.Contains("assertAnalysisJobs") -or
    -not $analysisClientSource.Contains("assertAnalysisJobSummary") -or
    -not $analysisClientSource.Contains("assertAgentNodes") -or
    -not $analysisClientSource.Contains("assertAgentNode") -or
    -not $analysisClientSource.Contains("assertAnalysisDebateResponse") -or
    -not $analysisClientSource.Contains("assertFinalReportAsset") -or
    -not $analysisClientSource.Contains("assertDeleteAnalysisRunResponse") -or
    -not $analysisClientSource.Contains("request<unknown>('/analysis/runs',") -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/start`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/cancel`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/retry`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/job`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/jobs?${search.toString()}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/jobs/summary?${search.toString()}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/nodes`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/nodes/${nodeId}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/debate`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}/report`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/reports${suffix}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/${runId}`')) {
  throw "analysisClient analysis lifecycle/job/node/report clients are missing unknown-first response guards"
}
if (-not $analysisClientSource.Contains("assertRunCompareResult") -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/runs/compare?') -or
    -not $analysisClientSource.Contains("return assertRunCompareResult(result)")) {
  throw "analysisClient.compareAnalysisRuns is missing run-compare response-shape guards"
}
if (-not $knowledgeClientSource.Contains("assertKnowledgeSummary") -or
    -not $knowledgeClientSource.Contains("assertKnowledgeItem") -or
    -not $knowledgeClientSource.Contains("assertKnowledgeItemList") -or
    -not $knowledgeClientSource.Contains("assertStringArray(item.evidence") -or
    -not $knowledgeClientSource.Contains("assertStringArray(item.guardrail_notes") -or
    -not $knowledgeClientSource.Contains("assertStringArray(item.tags") -or
    -not $knowledgeClientSource.Contains("assertKnowledgeItemBoundary") -or
    -not $knowledgeClientSource.Contains("function isStrongEvidenceValue") -or
    -not $knowledgeClientSource.Contains("normalized === 'RESEARCH_GRADE'") -or
    -not $knowledgeClientSource.Contains("normalized === 'PRIMARY_EVIDENCE_READY'") -or
    -not $knowledgeClientSource.Contains("export interface CreateKnowledgeItemPayload") -or
    -not $knowledgeClientSource.Contains("source_run_id?: string") -or
    -not $knowledgeClientSource.Contains("requireBoolean(item, 'source_run_verified', 'knowledge item')") -or
    -not $knowledgeClientSource.Contains("export function knowledgeSubmissionConfidence") -or
    -not $knowledgeClientSource.Contains("function sanitizeCreateKnowledgeItemPayload") -or
    -not $knowledgeClientSource.Contains("const sourceRunId = payload.source_run_id?.trim()") -or
    -not $knowledgeClientSource.Contains("sanitized.source_run_id = sourceRunId") -or
    -not $knowledgeClientSource.Contains("delete sanitized.source_run_id") -or
    -not $knowledgeClientSource.Contains("if (normalized === 'HIGH' || normalized === 'MEDIUM') return 'MEDIUM'") -or
    -not $knowledgeClientSource.Contains("return 'LOW'") -or
    $knowledgeClientSource.Contains("return normalized === 'LOW' ? 'LOW' : 'MEDIUM'") -or
    -not $knowledgeClientSource.Contains("body: JSON.stringify(sanitizeCreateKnowledgeItemPayload(payload))") -or
    -not $knowledgeClientSource.Contains("normalized.includes('STRONG')") -or
    -not $knowledgeClientSource.Contains("normalized.includes('PRIMARY')") -or
    -not $knowledgeClientSource.Contains("knowledge evidence must not become a strong conclusion") -or
    -not $knowledgeClientSource.Contains("assertNumberRecord(summary.categories") -or
    -not $knowledgeClientSource.Contains(".then(assertKnowledgeSummary)") -or
    -not $knowledgeClientSource.Contains(".then(assertKnowledgeItemList)") -or
    -not $knowledgeClientSource.Contains(".then(assertKnowledgeItem)") -or
    -not $knowledgeClientSource.Contains("request<unknown>('/knowledge/summary')") -or
    -not $knowledgeClientSource.Contains("request<unknown>('/knowledge/items'") -or
    -not $typesSource.Contains("source_run_verified: boolean") -or
    -not $knowledgeClientSource.Contains('request<unknown>(`/knowledge/items/${itemId}/review`') -or
    -not $knowledgeClientSource.Contains('request<unknown>(`/knowledge/from-run/${runId}`')) {
  throw "knowledgeClient is missing Knowledge summary/item response guards"
}
if (-not $knowledgePageSource.Contains("useOperatorContext()") -or
    -not $knowledgePageSource.Contains("useSearchParams") -or
    -not $knowledgePageSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $knowledgePageSource.Contains("const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)") -or
    -not $knowledgePageSource.Contains("const runId = isLinkedRunPending ? '' : linkedRunId || currentRunId || currentRun?.runId") -or
    $knowledgePageSource.Contains("const runId = currentRunId ?? currentRun?.runId") -or
    -not $knowledgePageSource.Contains("if (isLinkedRunPending)") -or
    -not $knowledgePageSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $knowledgePageSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $knowledgePageSource.Contains("canWriteKnowledgeItems") -or
    -not $knowledgePageSource.Contains("canArchiveKnowledgeItems") -or
    -not $knowledgePageSource.Contains("knowledgeWriteDisabledReason") -or
    -not $knowledgePageSource.Contains("knowledgeArchiveDisabledReason") -or
    -not $knowledgePageSource.Contains("if (!canWriteKnowledgeItems)") -or
    -not $knowledgePageSource.Contains("if (action === 'ARCHIVE' && !canArchiveKnowledgeItems)") -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-write-role"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-write-disabled-reason"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-archive-disabled-reason"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-current-run-id"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-current-run-loading"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-generate-from-run"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-create-manual"') -or
    -not $knowledgePageSource.Contains('knowledge-review-approve-') -or
    -not $knowledgePageSource.Contains('knowledge-review-reject-') -or
    -not $knowledgePageSource.Contains('knowledge-archive-item-')) {
  throw "KnowledgeIterationPage is missing researcher/admin-gated Knowledge write controls"
}
if (-not $knowledgePageSource.Contains("function knowledgeEvidenceStrengthLabel") -or
    -not $knowledgePageSource.Contains("function knowledgeItemBlocker") -or
    -not $knowledgePageSource.Contains("function knowledgeItemNextAction") -or
    -not $knowledgePageSource.Contains("type KnowledgeDraftEvidenceStrength = 'LOW'") -or
    $knowledgePageSource.Contains("type KnowledgeDraftEvidenceStrength = 'SUPPORTING_ONLY'") -or
    -not $knowledgePageSource.Contains("function buildManualKnowledgeGovernance") -or
    -not $knowledgePageSource.Contains("knowledgeSubmissionConfidence") -or
    -not $knowledgePageSource.Contains("const evidenceStrength: KnowledgeDraftEvidenceStrength = 'LOW'") -or
    $knowledgePageSource.Contains(": 'SUPPORTING_ONLY'") -or
    -not $knowledgePageSource.Contains("confidence: knowledgeSubmissionConfidence(confidence)") -or
    -not $knowledgePageSource.Contains("source_run_id: runId || undefined") -or
    -not $knowledgePageSource.Contains("disabled={saving || !title.trim() || !thesis.trim() || !canWriteKnowledgeItems || isLinkedRunPending}") -or
    $knowledgePageSource.Contains('<option value="HIGH">HIGH</option>') -or
    -not $knowledgePageSource.Contains("function reviewGateEvidenceStrength") -or
    -not $knowledgePageSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW')") -or
    -not $knowledgePageSource.Contains("['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $knowledgePageSource.Contains("'RESEARCH_GRADE'") -or
    -not $knowledgePageSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $knowledgePageSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $knowledgePageSource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN', 'SUPPORTING_ONLY'].includes(normalized)) return normalized") -or
    $knowledgePageSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = '')") -or
    -not $knowledgePageSource.Contains("const apiStrength = reviewGateEvidenceStrength(item.evidence_strength)") -or
    -not $knowledgePageSource.Contains("item.source_run_id && item.source_run_verified") -or
    -not $knowledgePageSource.Contains("item.source_run_id && !item.source_run_verified") -or
    -not $knowledgePageSource.Contains("item.evidence.length === 0") -or
    -not $knowledgePageSource.Contains("item.guardrail_notes.length === 0") -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-governance"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-governance-id"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-evidence-strength"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-blocker"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-next-action"') -or
    -not $knowledgePageSource.Contains('data-testid="knowledge-draft-simulation-boundary"') -or
    -not $knowledgePageSource.Contains("simulation_only=true / is_real_trade=false / SIM_* / evidence_usage=supporting_only / strong_conclusion_allowed=false") -or
    -not $knowledgePageSource.Contains("knowledge-item-governance-") -or
    -not $knowledgePageSource.Contains("knowledge-item-id-") -or
    -not $knowledgePageSource.Contains("knowledge-item-evidence-strength-") -or
    -not $knowledgePageSource.Contains("knowledge-item-blocker-") -or
    -not $knowledgePageSource.Contains("knowledge-item-next-action-") -or
    -not $knowledgePageSource.Contains("knowledge-item-simulation-boundary-") -or
    -not $knowledgePageSource.Contains("simulation_only={String(item.simulation_only)} / is_real_trade={String(item.is_real_trade)} / evidence_usage={item.evidence_usage} / strong_conclusion_allowed={String(item.strong_conclusion_allowed)} / SIM_* / source_run_verified={String(item.source_run_verified)}") -or
    -not $knowledgePageSource.Contains("source_run_verified={String(item.source_run_verified)}") -or
    -not $knowledgePageSource.Contains("'verified' : 'unverified'") -or
    -not $strictAuthBrowserSource.Contains("assertKnowledgeItemReviewBoundaryVisible") -or
    -not $strictAuthBrowserSource.Contains("Knowledge item visible review boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Knowledge visible review boundary") -or
    -not $typesSource.Contains("evidence_usage: KnowledgeEvidenceUsage") -or
    -not $typesSource.Contains("strong_conclusion_allowed: boolean")) {
  throw "KnowledgeIterationPage is missing visible item ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $dataPipelineClientSource.Contains("assertCompressionOverview") -or
    -not $dataPipelineClientSource.Contains("assertDataQualityScore") -or
    -not $dataPipelineClientSource.Contains("assertRunCompressionSummary") -or
    -not $dataPipelineClientSource.Contains("assertDataFingerprint") -or
    -not $dataPipelineClientSource.Contains("assertKnowledgeDistillationGroup") -or
    -not $dataPipelineClientSource.Contains("assertKnowledgeDistillationGroupList") -or
    -not $dataPipelineClientSource.Contains("assertStringArray(fingerprint.canonical_keys") -or
    -not $dataPipelineClientSource.Contains("assertStringArray(summary.guardrail_summary") -or
    -not $dataPipelineClientSource.Contains("assertStringArray(summary.evidence_summary") -or
    -not $dataPipelineClientSource.Contains("assertNumberRecord(overview.retention_actions") -or
    -not $dataPipelineClientSource.Contains(".then(assertCompressionOverview)") -or
    -not $dataPipelineClientSource.Contains(".then(assertDataQualityScore)") -or
    -not $dataPipelineClientSource.Contains(".then(assertRunCompressionSummary)") -or
    -not $dataPipelineClientSource.Contains(".then(assertKnowledgeDistillationGroupList)") -or
    -not $dataPipelineClientSource.Contains('request<unknown>(`/data-pipeline/overview?limit=${limit}`') -or
    -not $dataPipelineClientSource.Contains('request<unknown>(`/data-pipeline/runs/${runId}/quality`') -or
    -not $dataPipelineClientSource.Contains('request<unknown>(`/data-pipeline/runs/${runId}/summary`') -or
    -not $dataPipelineClientSource.Contains('request<unknown>(`/data-pipeline/runs/${runId}/compress`') -or
    -not $dataPipelineClientSource.Contains('request<unknown>(`/data-pipeline/knowledge/distill')) {
  throw "dataPipelineClient is missing Data Compression response guards"
}
if (-not $dataCompressionSource.Contains("useOperatorContext()") -or
    -not $dataCompressionSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $dataCompressionSource.Contains("canWriteDataCompression") -or
    -not $dataCompressionSource.Contains("dataCompressionWriteDisabledReason") -or
    -not $dataCompressionSource.Contains("if (!canWriteDataCompression)") -or
    -not $dataCompressionSource.Contains('data-testid="data-compression-write-role"') -or
    -not $dataCompressionSource.Contains('data-testid="data-compression-write-disabled-reason"') -or
    -not $dataCompressionSource.Contains('data-testid="data-compression-write-summary"') -or
    -not $dataCompressionSource.Contains("disabled={!selectedRunId || saving || selectedRunCompressed || !canWriteDataCompression}")) {
  throw "DataCompressionPage is missing researcher-gated compression write controls"
}
if (-not $dataCompressionSource.Contains("type DataCompressionEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $dataCompressionSource.Contains("type DataCompressionEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $dataCompressionSource.Contains("'SUPPORTING_ONLY'") -or
    $dataCompressionSource.Contains("evidenceStrength = 'STRONG'") -or
    $dataCompressionSource.Contains("evidenceStrength = 'HIGH'") -or
    -not $dataCompressionSource.Contains("function buildDataCompressionGovernance") -or
    -not $dataCompressionSource.Contains("summary.quality.missing_critical_fields.length > 0") -or
    -not $dataCompressionSource.Contains("summary.evidence_summary.length === 0 || summary.guardrail_summary.length === 0") -or
    -not $dataCompressionSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $dataCompressionSource.Contains("strongConclusionAllowed: false") -or
    -not $dataCompressionSource.Contains("data-compression-run-governance-") -or
    -not $dataCompressionSource.Contains("data-compression-run-governance-id-") -or
    -not $dataCompressionSource.Contains("data-compression-run-evidence-strength-") -or
    -not $dataCompressionSource.Contains("data-compression-run-blocker-") -or
    -not $dataCompressionSource.Contains("data-compression-run-next-action-") -or
    -not $dataCompressionSource.Contains("data-compression-run-simulation-boundary-") -or
    -not $dataCompressionSource.Contains("simulation_only={String(compressionGovernance.simulationOnly)} / is_real_trade={String(compressionGovernance.isRealTrade)} / evidence_usage={compressionGovernance.evidenceUsage} / strong_conclusion_allowed={String(compressionGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("runDataCompressionReviewBoundaryScenario") -or
    -not $strictAuthBrowserSource.Contains("await runDataCompressionReviewBoundaryScenario(page)") -or
    -not $strictAuthBrowserSource.Contains("Data Compression request did not include the expected Authorization bearer token") -or
    -not $strictAuthBrowserSource.Contains("assertDataCompressionVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Compression visible review boundary")) {
  throw "DataCompressionPage is missing visible run ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $klineClientSource.Contains("assertKlineResponse") -or
    -not $klineClientSource.Contains("assertKlineRow") -or
    -not $klineClientSource.Contains("assertKlinePeriod") -or
    -not $klineClientSource.Contains("assertKlineRange") -or
    -not $klineClientSource.Contains("assertOptionalNumber(row, 'preClose'") -or
    -not $klineClientSource.Contains("ensureArray(response.rows, 'K-line rows').forEach(assertKlineRow)") -or
    -not $klineClientSource.Contains("response.status !== 'READY' && response.status !== 'FAILED'") -or
    -not $klineClientSource.Contains("response.dataMode !== 'LIVE' && response.dataMode !== 'UNAVAILABLE'") -or
    -not $klineClientSource.Contains(".then(assertKlineResponse)") -or
    -not $klineClientSource.Contains('request<unknown>(`/market-data/kline?${params.toString()}`')) {
  throw "klineClient is missing K-line response guards"
}
if (@($manifest.redirects | Where-Object { $_.from -eq "/market" -and $_.to -eq "/quant-core" }).Count -eq 0) {
  throw "routeManifest is missing /market -> /quant-core legacy redirect"
}
if (-not $appSource.Contains("function RedirectWithSearch({ to }: { to: string })") -or
    -not $appSource.Contains("const location = useLocation()") -or
    -not $appSource.Contains('to={`${to}${location.search}${location.hash}`}')) {
  throw "App legacy redirects must preserve query/hash for run-linked routes"
}
if (-not $strictAuthBrowserSource.Contains("runMarketLegacyRedirectScenario") -or
    -not $strictAuthBrowserSource.Contains("await runMarketLegacyRedirectScenario(page, seededRunId)") -or
    -not $strictAuthBrowserSource.Contains("Market legacy redirect run hydrate") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Market legacy redirect preserves run context")) {
  throw "Market legacy redirect is missing strict-auth browser run-context coverage"
}
if (-not $globalMarketClientSource.Contains("assertGlobalMarketOverviewPayload") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketKlineRow") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketFundFlowRow") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketSectorRankRow") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketSourceChainItem") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketConflict") -or
    -not $globalMarketClientSource.Contains("assertGlobalMarketArbitration") -or
    -not $globalMarketClientSource.Contains("assertRequiredNumberField(row, 'close'") -or
    -not $globalMarketClientSource.Contains("assertRequiredNumberField(row, 'netAmount'") -or
    -not $globalMarketClientSource.Contains("assertOptionalNullableNumberField(row, 'pctChange'") -or
    -not $globalMarketClientSource.Contains("assertOptionalScalarConflictValue(conflict, 'primaryValue'") -or
    -not $globalMarketClientSource.Contains("assertOptionalArrayField(payload, 'indices'") -or
    -not $globalMarketClientSource.Contains("indexRecord.rows.forEach((row, rowOffset)") -or
    -not $globalMarketClientSource.Contains("payload.fundFlow.rows.forEach((row, offset)") -or
    -not $globalMarketClientSource.Contains("payload.sectorRank.top.forEach((row, offset)") -or
    -not $globalMarketClientSource.Contains("assertOptionalObjectField(payload, 'fundFlow'") -or
    -not $globalMarketClientSource.Contains("assertOptionalObjectField(payload, 'sectorRank'") -or
    -not $globalMarketClientSource.Contains("assertOptionalObjectField(payload, 'temperature'") -or
    -not $globalMarketClientSource.Contains("assertArrayItemsString(payload.temperature.reasons") -or
    -not $globalMarketClientSource.Contains("normalizeGlobalMarketOverview(assertGlobalMarketOverviewPayload(payload))") -or
    -not $globalMarketClientSource.Contains("request<unknown>('/market-data/global?range=4m'")) {
  throw "globalMarketClient is missing global market overview response guards"
}
if (-not $globalMarketPageSource.Contains("buildAutoStockOpportunities") -or
    -not $globalMarketPageSource.Contains("AutoStockSelectorPanel") -or
    -not $globalMarketPageSource.Contains('data-testid="global-market-auto-stock-selector"') -or
    -not $globalMarketPageSource.Contains('data-testid="global-market-auto-stock-boundary"') -or
    -not $globalMarketPageSource.Contains('data-testid="global-market-auto-stock-candidate"') -or
    -not $globalMarketPageSource.Contains('data-testid="global-market-auto-stock-source"') -or
    -not $globalMarketPageSource.Contains('data-testid="global-market-auto-stock-top-score"') -or
    -not $globalMarketPageSource.Contains("simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("runGlobalMarketAutoStockBoundaryScenario") -or
    -not $strictAuthBrowserSource.Contains("await runGlobalMarketAutoStockBoundaryScenario(page)") -or
    -not $strictAuthBrowserSource.Contains("Global Market overview request did not include the expected Authorization bearer token") -or
    -not $strictAuthBrowserSource.Contains("global-market-auto-stock-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Global Market auto-stock review boundary")) {
  throw "GlobalMarketPage is missing auto stock selector research-only guardrails"
}
if (-not $appSource.Contains('path="/run-compare"') -or
    -not $runCompareSource.Contains("compareAnalysisRuns(left, right)") -or
    -not $runCompareSource.Contains("result.summary.map") -or
    -not $runCompareSource.Contains("result.diffs.map") -or
    -not $runCompareSource.Contains("setError(err instanceof Error ? err.message") -or
    -not $runCompareSource.Contains("function buildRunCompareGovernance") -or
    -not $runCompareSource.Contains("evidenceStrength: 'LOW'") -or
    -not $runCompareSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $runCompareSource.Contains("strongConclusionAllowed: false") -or
    $runCompareSource.Contains("evidenceStrength: 'SUPPORTING_ONLY'") -or
    -not $runCompareSource.Contains('data-testid="run-compare-governance"') -or
    -not $runCompareSource.Contains('data-testid="run-compare-governance-id"') -or
    -not $runCompareSource.Contains('data-testid="run-compare-evidence-strength"') -or
    -not $runCompareSource.Contains('data-testid="run-compare-blocker"') -or
    -not $runCompareSource.Contains('data-testid="run-compare-next-action"') -or
    -not $runCompareSource.Contains('data-testid="run-compare-simulation-boundary"') -or
    -not $runCompareSource.Contains("simulation_only={String(runCompareGovernance.simulationOnly)} / is_real_trade={String(runCompareGovernance.isRealTrade)} / evidence_usage={runCompareGovernance.evidenceUsage} / strong_conclusion_allowed={String(runCompareGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("runRunCompareReviewBoundaryScenario") -or
    -not $strictAuthBrowserSource.Contains("await runRunCompareReviewBoundaryScenario(page)") -or
    -not $strictAuthBrowserSource.Contains("/api/analysis/runs/compare") -or
    -not $strictAuthBrowserSource.Contains("Run Compare request did not include the expected Authorization bearer token") -or
    -not $strictAuthBrowserSource.Contains("assertRunCompareVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Run Compare visible review boundary") -or
    -not $runCompareSource.Contains("Audit Log")) {
  throw "RunComparePage is not wired to render guarded compare summaries/diffs, governance boundaries, and API errors"
}
foreach ($requiredResearchGuard in @(
  "assertResearchLoopDetail",
  "assertResearchIteration",
  "assertStringArray",
  "assertResearchEvidenceLink",
  "assertResearchFeedbackEvent",
  "assertResearchVerdictInputs",
  "assertResearchMetricComparisonRow",
  "assertResearchVerdictEvidence",
  "assertP2ClosedLoopSampleResponse",
  "assertSupportingOnlyResearchBridgeBoundary",
  "assertResearchBacktestVerdictInputsResponse",
  "assertResearchSignalOpsEvidenceResponse",
  "assertResearchTraceImportApiResponse",
  "assertResearchTraceImportIteration",
  "assertResearchActionSelection",
  "assertResearchHypothesisDraft"
)) {
  if ($researchClientSource -notmatch $requiredResearchGuard) {
    throw "researchClient is missing $requiredResearchGuard response-shape guard"
  }
}
if (-not $researchClientSource.Contains(".then(assertResearchLoopDetail)") -or
    -not $researchClientSource.Contains(".then(assertResearchVerdictInputs)") -or
    -not $researchClientSource.Contains("assertStringArray(loop.tags") -or
    -not $researchClientSource.Contains("assertStringArray(iteration.target_modules") -or
    -not $researchClientSource.Contains("assertStringArray(result.missing_reasons") -or
    -not $researchClientSource.Contains("assertStringArray(result.warnings, 'P2 closed-loop warnings')") -or
    -not $researchClientSource.Contains("assertStringArray(inputs.blocking_reasons") -or
    -not $researchClientSource.Contains("assertStringArray(inputs.quality_warnings") -or
    -not $researchClientSource.Contains("assertStringArray(result.provenance_chain") -or
    -not $researchClientSource.Contains("assertStringArray(result.warnings, 'research artifact materialization warnings')") -or
    -not $researchClientSource.Contains("assertStringArray(preview.tags") -or
    -not $researchClientSource.Contains("assertStringArray(result.warnings, 'research trace import warnings')") -or
    -not $researchClientSource.Contains("assertStringArray(selection.evidence") -or
    -not $researchClientSource.Contains("assertStringArray(draft.target_modules") -or
    -not $researchClientSource.Contains("assertStringArray(draft.targetModules") -or
    -not $researchClientSource.Contains("assertStringArray(draft.modules") -or
    -not $researchClientSource.Contains("['maturity_level', 'maturity_label', 'stage', 'next_action', 'next_action_label', 'evidence_strength']") -or
    -not $researchClientSource.Contains("assertReviewGateBoundary") -or
    -not $researchClientSource.Contains("workflow evidence must not become a strong conclusion") -or
    -not $researchClientSource.Contains("workflow evidence must use LOW review-gate strength instead of legacy SUPPORTING_ONLY") -or
    -not $researchClientSource.Contains("strength === 'SUPPORTING_ONLY'") -or
    -not $researchClientSource.Contains("workflow review must stay simulation-only") -or
    -not $researchClientSource.Contains("assertReviewGateEvidenceQuality") -or
    -not $researchClientSource.Contains("verdict evidence must stay review-gate strength") -or
    -not $researchClientSource.Contains("quality === 'RESEARCH_GRADE'") -or
    -not $researchClientSource.Contains("quality === 'PRIMARY_EVIDENCE_READY'") -or
    -not $researchClientSource.Contains("assertSupportingSignalOpsEvidenceQuality") -or
    -not $researchClientSource.Contains("SignalOps evidence must stay supporting-only and cannot become a strong conclusion") -or
    -not $researchClientSource.Contains("result.strong_conclusion_allowed !== false") -or
    -not $researchClientSource.Contains("assertSupportingOnlyResearchBridgeBoundary(result, 'research backtest verdict inputs')") -or
    -not $researchClientSource.Contains("assertSupportingOnlyResearchBridgeBoundary(result, 'research SignalOps evidence')") -or
    -not $researchClientSource.Contains(".forEach(assertResearchEvidenceLink)") -or
    -not $researchClientSource.Contains(".forEach(assertResearchFeedbackEvent)") -or
    -not $researchClientSource.Contains(".forEach(assertResearchMetricComparisonRow)") -or
    -not $researchClientSource.Contains(".forEach(assertResearchVerdictEvidence)") -or
    -not $researchClientSource.Contains(".then(assertP2ClosedLoopSampleResponse)") -or
    -not $researchClientSource.Contains(".then(assertResearchBacktestVerdictInputsResponse)") -or
    -not $researchClientSource.Contains(".then(assertResearchSignalOpsEvidenceResponse)") -or
    -not $researchClientSource.Contains("assertResearchActionSelection(result.action_selection)") -or
    -not $researchClientSource.Contains(".forEach(assertResearchHypothesisDraft)") -or
    -not $researchClientSource.Contains(".forEach(assertResearchTraceImportIteration)")) {
  throw "researchClient high-fanout Research Lab calls are not guarded before entering render state"
}
if (-not $researchTracesSource.Contains("parseTraceJsonObject") -or
    -not $researchTracesSource.Contains("JSON.parse(raw) as unknown") -or
    -not $researchTracesSource.Contains("Array.isArray(parsed)") -or
    -not $researchTracesSource.Contains("throw new Error(") -or
    -not $researchTracesSource.Contains("source.trim() || 'rd-agent'") -or
    -not $researchTracesSource.Contains("useOperatorContext()") -or
    -not $researchTracesSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $researchTracesSource.Contains("traceImportDisabledReason") -or
    -not $researchTracesSource.Contains("function buildTraceGovernance") -or
    -not $researchTracesSource.Contains("evidenceStrength: 'LOW'") -or
    $researchTracesSource.Contains("evidenceStrength: 'SUPPORTING_ONLY'") -or
    -not $researchTracesSource.Contains('data-testid="research-trace-import-role"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-import-disabled-reason"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-import-submit"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-governance"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-governance-id"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-evidence-strength"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-blocker"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-next-action"') -or
    -not $researchTracesSource.Contains('data-testid="research-trace-simulation-boundary"') -or
    -not $researchTracesSource.Contains("evidenceUsage: 'supporting_only'") -or
    -not $researchTracesSource.Contains("strongConclusionAllowed: false") -or
    -not $researchTracesSource.Contains("simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("runResearchTracesReviewBoundaryScenario") -or
    -not $strictAuthBrowserSource.Contains("await runResearchTracesReviewBoundaryScenario(page)") -or
    -not $strictAuthBrowserSource.Contains("assertResearchTraceVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("Research Traces request did not include the expected Authorization bearer token") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research Traces visible review boundary") -or
    -not $researchTracesSource.Contains("!canImportResearchTrace") -or
    $researchTracesSource.Contains("JSON.parse(traceText) as Record<string, unknown>")) {
  throw "ResearchTracesPage must validate imported trace JSON, gate imports, and render LOW trace governance"
}
if ($analysisStoreSource -notmatch "!state\.currentRun" -or $analysisStoreSource -notmatch "targetRunSummary" -or $analysisStoreSource -notmatch "runs\.find\(\(run\) => run\.runId === currentRunId\)") {
  throw "useAnalysisStore.loadRunHistory does not hydrate a latest/selected run when pages open without currentRun"
}
if ($dashboardSource -notmatch "fallbackToMock" -or
    $dashboardSource -notmatch "onClick=\{fallbackToMock\}" -or
    -not $dashboardSource.Contains('data-testid="dashboard-page"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-decision-workbench"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-current-run-id"') -or
    -not $dashboardSource.Contains("function buildDashboardRunGovernance") -or
    -not $dashboardSource.Contains("function dashboardRunEvidenceStrength") -or
    -not $dashboardSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW'") -or
    $dashboardSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW' | 'SUPPORTING_ONLY'") -or
    -not $dashboardSource.Contains("if (normalized === 'LOW') return 'LOW'") -or
    -not $dashboardSource.Contains("if (['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $dashboardSource.Contains("if (normalized === 'UNKNOWN') return 'SUPPORTING_ONLY'") -or
    -not $dashboardSource.Contains("['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $dashboardSource.Contains("['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    ($dashboardSource -match "function dashboardRunEvidenceStrength[\s\S]*?\r?\n\s*return 'MEDIUM'\r?\n\}") -or
    ($dashboardSource -match "function dashboardRunEvidenceStrength[\s\S]*?return 'SUPPORTING_ONLY'") -or
    -not $dashboardSource.Contains("const dashboardEvidenceStrength = hasBoundaryViolation || failedStatus ? 'LOW' : dashboardRunEvidenceStrength(provenance.level)") -or
    $dashboardSource.Contains("evidenceStrength: dashboardRunEvidenceStrength(provenance.level)") -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-governance"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-governance-id"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-evidence-strength"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-blocker"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-next-action"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-run-simulation-boundary"') -or
    -not $dashboardSource.Contains("evidenceUsage") -or
    -not $dashboardSource.Contains("strongConclusionAllowed") -or
    -not $dashboardSource.Contains("simulation_only={String(dashboardGovernance.simulationOnly)} / is_real_trade={String(dashboardGovernance.isRealTrade)} / evidence_usage={dashboardGovernance.evidenceUsage} / strong_conclusion_allowed={String(dashboardGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $typesSource.Contains("legacyCompatibilityOnly?: boolean") -or
    -not $typesSource.Contains("canonicalNode?: string") -or
    -not $typesSource.Contains("activeNode?: boolean") -or
    -not $agentCanonicalSource.Contains("export const LEGACY_AGENT_CANONICAL") -or
    -not $agentCanonicalSource.Contains("data_engine: 'data_reliability_engine'") -or
    -not $agentCanonicalSource.Contains("dvg_gate: 'guardrail_hub'") -or
    -not $agentCanonicalSource.Contains("market_technical_analyst: 'quant_core'") -or
    -not $agentCanonicalSource.Contains("export function canonicalAgentFor") -or
    -not $dashboardSource.Contains("import { canonicalAgentFor } from '../../utils/agentCanonical'") -or
    $dashboardSource.Contains("const LEGACY_AGENT_CANONICAL") -or
    -not $dashboardSource.Contains("function normalizeSortedAgent") -or
    -not $dashboardSource.Contains("function isDashboardCompatibilityOnly") -or
    -not $dashboardSource.Contains("const inferredCanonicalNode = canonicalAgentFor(agent.node)") -or
    -not $dashboardSource.Contains("activeNode: legacyCompatibilityOnly ? false : agent.activeNode ?? true") -or
    -not $dashboardSource.Contains("const activeCanonicalAgents = sortedAgents.filter((agent) => !isDashboardCompatibilityOnly(agent))") -or
    -not $dashboardSource.Contains("legacyCompatibilityOnly: ar.legacyCompatibilityOnly") -or
    -not $dashboardSource.Contains("canonicalNode: ar.canonicalNode") -or
    -not $dashboardSource.Contains("dashboard-agent-compatibility-") -or
    -not $dashboardSource.Contains('data-testid="dashboard-trade-boundary"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-data-provenance"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-evidence-spine"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-source-freshness"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-agent-chain"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-knowledge-regression"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-llm-live-call-health"') -or
    -not $dashboardSource.Contains('testId="dashboard-llm-live-call-success-rate"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-llm-live-call-trend"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-llm-live-call-failure-reason"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-research-closed-loop-entry"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-create-closed-loop-sample"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-research-closed-loop-role"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-research-closed-loop-disabled-reason"') -or
    -not $dashboardSource.Contains('data-testid="dashboard-research-closed-loop-current-step"') -or
    -not $dashboardSource.Contains("closedLoopStepLabels[actionableStep.key]") -or
    -not $dashboardSource.Contains("createP2ClosedLoopSample") -or
    -not $dashboardSource.Contains("useOperatorContext()") -or
    -not $dashboardSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $dashboardSource.Contains("disabled={creating || !canCreate}") -or
    -not $dashboardSource.Contains($dashboardResearchSamplePermissionText) -or
    -not $dashboardSource.Contains("getBackendMetrics()") -or
    -not $dashboardSource.Contains("llmCallFailureRate") -or
    -not $dashboardSource.Contains("metric?.successRate") -or
    -not $dashboardSource.Contains("health?.trend") -or
    -not $dashboardSource.Contains("health?.longTrend") -or
    -not $dashboardSource.Contains("signedPercentValue(trend?.llmSuccessRateDelta)") -or
    -not $dashboardSource.Contains("signedPercentValue(longTrend?.llmSuccessRateDelta)") -or
    -not $strictAuthBrowserSource.Contains("long 30d success +25.0%") -or
    -not $dashboardSource.Contains("failureReasons") -or
    -not $dashboardSource.Contains("buildDashboardWorkbench") -or
    -not $dashboardWorkbenchSource.Contains("run.dashboardSummary") -or
    -not $dashboardWorkbenchSource.Contains("tradeBoundary?.simulationOnly") -or
    -not $dashboardWorkbenchSource.Contains("tradeBoundary?.isRealTrade") -or
    -not $typesSource.Contains("dashboardSummary?: DashboardSummary") -or
    -not $typesSource.Contains("simulationOnly: boolean") -or
    -not $typesSource.Contains("isRealTrade: boolean") -or
    -not $dashboardSource.Contains('`simulationOnly=${String(workbench.summary.tradeBoundary.simulationOnly)}`') -or
    -not $dashboardSource.Contains('`isRealTrade=${String(workbench.summary.tradeBoundary.isRealTrade)}`') -or
    -not $dashboardSource.Contains("simulation_only=true") -or
    -not $dashboardSource.Contains("is_real_trade=false")) {
  throw "DashboardPage is not wired to the local mock fallback path"
}
if (-not $dashboardSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $dashboardSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $dashboardSource.Contains("currentRun?.runId !== linkedRunId") -or
    -not $dashboardSource.Contains('data-testid="dashboard-page-loading"')) {
  throw "DashboardPage must wait for URL-linked current run hydration before rendering stale run content"
}
if (-not $dataProvenanceSource.Contains("function reviewGateProvenanceLabel") -or
    -not $dataProvenanceSource.Contains("const label = reviewGateProvenanceLabel(level)")) {
  throw "Dashboard provenance summary must display review-gated evidence labels"
}
if (-not $newTaskSource.Contains("buildPortfolioPreflight") -or
    -not $newTaskSource.Contains('data-testid="new-task-portfolio-risk-preflight"') -or
    -not $newTaskSource.Contains('data-testid="new-task-portfolio-risk-boundary"') -or
    -not $newTaskSource.Contains("preflight_only=true / simulation_only=true / is_real_trade=false / evidence_usage=portfolio_context_only / strong_conclusion_allowed=false / SIM_*") -or
    -not $newTaskSource.Contains("topExposure(positions, 'industry')") -or
    -not $newTaskSource.Contains($newTaskImportQualityText) -or
    -not $newTaskSource.Contains($newTaskCurrentSymbolAbsentText) -or
    -not $newTaskSource.Contains($newTaskBrokerImportTemplateText) -or
    -not $newTaskSource.Contains($newTaskBrokerTemplateWarningText)) {
  throw "NewTaskPage is missing portfolio pre-task risk prompt linkage"
}
if (-not $newTaskSource.Contains("function buildAnalysisRunPreflightGovernance") -or
    -not $newTaskSource.Contains("selectedSnapshot?.qualityStatus") -or
    -not $newTaskSource.Contains("portfolioPreflight.level === 'HIGH'") -or
    -not $newTaskSource.Contains("llmHealthStatus === 'BLOCKED'") -or
    -not $newTaskSource.Contains("USER_INPUT_ONLY") -or
    -not $newTaskSource.Contains('data-testid="new-task-run-governance"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-context-id"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-evidence-strength"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-blocker"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-next-action"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-simulation-boundary"') -or
    -not $newTaskSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $newTaskSource.Contains("strongConclusionAllowed: false") -or
    -not $newTaskSource.Contains("simulation_only=true / is_real_trade=false / evidence_usage={runPreflightGovernance.evidenceUsage} / strong_conclusion_allowed={String(runPreflightGovernance.strongConclusionAllowed)} / SIM_*")) {
  throw "NewTaskPage is missing visible analysis-run ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $newTaskSource.Contains("useOperatorContext()") -or
    -not $newTaskSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $newTaskSource.Contains("canCreateAnalysisTask") -or
    -not $newTaskSource.Contains("newTaskRunDisabledReason") -or
    -not $newTaskSource.Contains("if (!canCreateAnalysisTask)") -or
    -not $newTaskSource.Contains('data-testid="new-task-run-role"') -or
    -not $newTaskSource.Contains('data-testid="new-task-run-disabled-reason"') -or
    -not $newTaskSource.Contains('data-testid="new-task-submit"') -or
    -not $newTaskSource.Contains("disabled={loading || !canCreateAnalysisTask}")) {
  throw "NewTaskPage is missing researcher-gated run creation controls"
}
if (-not $newTaskSource.Contains("getAgentRuntime()") -or
    -not $newTaskSource.Contains("formatLlmLiveCallStatus") -or
    -not $newTaskSource.Contains("last_live_call_at") -or
    -not $newTaskSource.Contains("llmReadinessMessage") -or
    -not $newTaskSource.Contains("last_call_success === true") -or
    -not $newTaskSource.Contains("last_call_success === false")) {
  throw "NewTaskPage is missing default LLM profile live-call status linkage"
}
if (-not $executionSource.Contains("type ExecutionEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $executionSource.Contains("type ExecutionEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $executionSource.Contains("'SUPPORTING_ONLY'") -or
    $executionSource.Contains("evidenceStrength = 'HIGH'") -or
    $executionSource.Contains("evidenceStrength: 'HIGH'") -or
    $executionSource.Contains("evidenceStrength = 'STRONG'") -or
    $executionSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $executionSource.Contains("function buildExecutionGovernance") -or
    -not $executionSource.Contains("actionNeedsManualConfirmation") -or
    -not $executionSource.Contains("paperTrading.simulation_only === true") -or
    -not $executionSource.Contains("paperTrading.is_real_trade === true") -or
    -not $executionSource.Contains("namespace !== 'SIM_*'") -or
    -not $executionSource.Contains("latestAction.startsWith('SIM_')") -or
    -not $executionSource.Contains("execution.executionReachability !== 'REACHABLE'") -or
    -not $executionSource.Contains("execution.allowedActions.some(actionNeedsManualConfirmation)") -or
    -not $executionSource.Contains('data-testid="execution-governance"') -or
    -not $executionSource.Contains('data-testid="execution-governance-id"') -or
    -not $executionSource.Contains('data-testid="execution-evidence-strength"') -or
    -not $executionSource.Contains('data-testid="execution-blocker"') -or
    -not $executionSource.Contains('data-testid="execution-next-action"') -or
    -not $executionSource.Contains('data-testid="execution-simulation-boundary"') -or
    -not $executionSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $executionSource.Contains("strongConclusionAllowed: false") -or
    -not $executionSource.Contains("simulation_only={String(executionGovernance.simulationOnly)} / is_real_trade={String(executionGovernance.isRealTrade)} / evidence_usage={executionGovernance.evidenceUsage} / strong_conclusion_allowed={String(executionGovernance.strongConclusionAllowed)} / SIM_*")) {
  throw "ExecutionPage is missing visible execution ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $permissionSource.Contains("type PermissionMatrixEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $permissionSource.Contains("type PermissionMatrixEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $permissionSource.Contains("'SUPPORTING_ONLY'") -or
    $permissionSource.Contains("evidenceStrength = 'HIGH'") -or
    $permissionSource.Contains("evidenceStrength: 'HIGH'") -or
    $permissionSource.Contains("evidenceStrength = 'STRONG'") -or
    $permissionSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $permissionSource.Contains("function buildPermissionMatrixGovernance") -or
    -not $permissionSource.Contains("finalActionNeedsFullPermission(finalAction)") -or
    -not $permissionSource.Contains("paperTrading.simulation_only === true") -or
    -not $permissionSource.Contains("paperTrading.is_real_trade === true") -or
    -not $permissionSource.Contains("namespace !== 'SIM_*'") -or
    -not $permissionSource.Contains("latestAction.startsWith('SIM_')") -or
    -not $permissionSource.Contains("run.dvg.allowedOutputLevel !== 'FULL'") -or
    -not $permissionSource.Contains("run.qiam.finalBuySuitability === 'BLOCK_BUY' || run.qiam.finalBuySuitability === 'REVIEW_ONLY'") -or
    -not $permissionSource.Contains("run.execution.executionReachability !== 'REACHABLE'") -or
    -not $permissionSource.Contains("run.killSwitch.active") -or
    -not $permissionSource.Contains("run.finalWriter?.humanConfirmationRequired !== true") -or
    -not $permissionSource.Contains('data-testid="permission-matrix-governance"') -or
    -not $permissionSource.Contains('data-testid="permission-matrix-governance-id"') -or
    -not $permissionSource.Contains('data-testid="permission-matrix-evidence-strength"') -or
    -not $permissionSource.Contains('data-testid="permission-matrix-blocker"') -or
    -not $permissionSource.Contains('data-testid="permission-matrix-next-action"') -or
    -not $permissionSource.Contains('data-testid="permission-matrix-simulation-boundary"') -or
    -not $permissionSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $permissionSource.Contains("strongConclusionAllowed: false") -or
    -not $permissionSource.Contains("simulation_only={String(permissionGovernance.simulationOnly)} / is_real_trade={String(permissionGovernance.isRealTrade)} / evidence_usage={permissionGovernance.evidenceUsage} / strong_conclusion_allowed={String(permissionGovernance.strongConclusionAllowed)} / SIM_*")) {
  throw "PermissionMatrixPage is missing visible permission ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $newTaskSource.Contains("const startResponse = await retryTransientTaskStep(() => startAnalysisRun(response.run_id)") -or
    -not $newTaskSource.Contains("startResponse.status === 'FAILED'") -or
    -not $newTaskSource.Contains('navigate(`/live-run?run_id=${encodeURIComponent(response.run_id)}`)') -or
    -not $newTaskSource.Contains("void retryTransientTaskStep(() => getAnalysisRun(response.run_id)") -or
    $newTaskSource.Contains("const run = await retryTransientTaskStep(() => getAnalysisRun(response.run_id)")) {
  throw "NewTaskPage must hand off to Live Run after start without blocking on initial detail hydration"
}
if (-not $agentRuntimeClientSource.Contains("assertAgentRuntimeConfig") -or
    -not $agentRuntimeClientSource.Contains("assertRuntimeBaseUrlSecurity") -or
    -not $agentRuntimeClientSource.Contains("assertOptionalString(security, 'code', 'runtime base URL security')") -or
    -not $agentRuntimeClientSource.Contains("assertOptionalString(security, 'host', 'runtime base URL security')") -or
    -not $agentRuntimeClientSource.Contains("assertOptionalString(security, 'reason', 'runtime base URL security')") -or
    -not $agentRuntimeClientSource.Contains("record.base_url_security") -or
    -not $agentRuntimeClientSource.Contains("assertAgentLLMProfile") -or
    -not $agentRuntimeClientSource.Contains("assertMarketDataProfile") -or
    -not $agentRuntimeClientSource.Contains("assertAgentDeployment") -or
    -not $agentRuntimeClientSource.Contains("assertLLMConfigTestResult") -or
    -not $agentRuntimeClientSource.Contains("assertMarketDataConfigTestResult") -or
    -not $agentRuntimeClientSource.Contains("assertDataSourceHealth") -or
    -not $agentRuntimeClientSource.Contains("assertDataSourceHealthList") -or
    -not $agentRuntimeClientSource.Contains("assertMarketDataAdapterConfig") -or
    -not $agentRuntimeClientSource.Contains("assertMarketDataStatusMatrix") -or
    -not $agentRuntimeClientSource.Contains(".then(assertAgentRuntimeConfig)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertLLMConfigTestResult)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertMarketDataConfigTestResult)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertDataSourceHealthList)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertMarketDataAdapterConfigList)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertMarketDataAdapterConfig)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertDataSourceHealth)") -or
    -not $agentRuntimeClientSource.Contains(".then(assertMarketDataStatusMatrix)") -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/runtime')") -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/runtime/test'") -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/runtime/validate-config'") -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/runtime/market-data/test'") -or
    -not $agentRuntimeClientSource.Contains('/agents/market-data/adapters${qs}') -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/market-data/adapters/config')") -or
    -not $agentRuntimeClientSource.Contains("request<unknown>('/agents/market-data/status')") -or
    -not $agentRuntimeClientSource.Contains("allow_trade_action must remain false") -or
    -not $agentRuntimeClientSource.Contains("final_decision_cap must remain NO_DIRECT_TRADE_ACTION")) {
  throw "agentRuntimeClient is missing runtime/profile/adapter response guards or no-direct-trade boundary checks"
}
if (-not $agentDagSource.Contains("type AgentDagEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $agentDagSource.Contains("evidenceStrength = 'STRONG'") -or
    $agentDagSource.Contains("evidenceStrength = 'HIGH'") -or
    $agentDagSource.Contains("type AgentDagEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $agentDagSource.Contains("return 'SUPPORTING_ONLY'") -or
    $agentDagSource.Contains("evidenceStrength = 'SUPPORTING_ONLY'")) {
  throw "Agent DAG evidence must not become a strong conclusion"
}
if (-not $agentDagSource.Contains("function normalizedEvidenceStrength") -or
    -not $agentDagSource.Contains("if (['UNKNOWN', 'SUPPORTING_ONLY', 'LOW', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    -not $agentDagSource.Contains("if (normalized === 'MEDIUM') return 'MEDIUM'") -or
    -not $agentDagSource.Contains("['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $agentDagSource.Contains("['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $agentDagSource.Contains("return 'LOW'") -or
    $agentDagSource.Contains("return null") -or
    $agentDagSource.Contains("normalizedEvidenceStrength(item.node.evidenceStrength) ?? 'MEDIUM'")) {
  throw "Agent DAG evidence normalization must explicitly review-gate strong and research-grade markers"
}
if (-not $agentDagSource.Contains("sourceCounts.llm") -or
    -not $agentDagSource.Contains("sourceCounts.degraded") -or
    -not $agentDagSource.Contains("compatibility: number") -or
    -not $agentDagSource.Contains("function buildAgentDagNodeGovernance") -or
    -not $agentDagSource.Contains("Compatibility-only alias; use") -or
    -not $agentDagSource.Contains("Mock/sample output cannot prove active Agent execution") -or
    -not $agentDagSource.Contains("Plugin observation is read-only and cannot act as executable DAG evidence") -or
    -not $agentDagSource.Contains("function buildAgentDagRunGovernance") -or
    -not $agentDagSource.Contains("sourceCounts.compatibility > 0") -or
    -not $agentDagSource.Contains("sourceCounts.mock > 0") -or
    -not $agentDagSource.Contains("sourceCounts.plugin > 0") -or
    -not $agentDagSource.Contains("const hasExecutableDagEvidence = sourceCounts.llm > 0 || sourceCounts.rule > 0") -or
    -not $agentDagSource.Contains("sourceCounts.compatibility > 0 || sourceCounts.mock > 0 || sourceCounts.plugin > 0") -or
    -not $agentDagSource.Contains("hasExecutableDagEvidence && evidenceScore >= 80") -or
    -not $agentDagSource.Contains("hasExecutableDagEvidence && (evidenceScore >= 50 || sourceReady > 0)") -or
    -not $agentDagSource.Contains("summary?.metrics") -or
    -not $agentDagSource.Contains("import { canonicalAgentFor } from '../../utils/agentCanonical'") -or
    $agentDagSource.Contains("const LEGACY_AGENT_CANONICAL") -or
    -not $agentDagSource.Contains("const inferredCanonicalNode = canonicalAgentFor(node.id)") -or
    -not $agentDagSource.Contains("|| Boolean(inferredCanonicalNode)") -or
    -not $agentDagSource.Contains("|| inferredCanonicalNode") -or
    -not $agentDagSource.Contains("legacyCompatibilityOnly") -or
    -not $agentDagSource.Contains("canonicalNode") -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-governance"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-context-id"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-evidence-strength"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-blocker"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-next-action"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-run-simulation-boundary"') -or
    -not $agentDagSource.Contains("simulation_only={String(runGovernance.simulationOnly)} / is_real_trade={String(runGovernance.isRealTrade)} / evidence_usage={runGovernance.evidenceUsage} / strong_conclusion_allowed={String(runGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $agentDagSource.Contains("LLM status:") -or
    -not $agentDagSource.Contains('data-testid="agent-dag-source-summary"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-metering-status"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-flow-canvas"') -or
    -not $agentDagSource.Contains('data-testid={`agent-dag-flow-node-${item.node.id}`}') -or
    -not $agentDagSource.Contains("data-source={item.source}") -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-detail"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-llm-count"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-degraded-count"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-rule-count"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-plugin-count"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-compatibility-count"') -or
    -not $agentDagSource.Contains('data-testid={`agent-dag-compatibility-${item.node.id}`}') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-compatibility"') -or
    -not $agentDagSource.Contains('agent-dag-row-compatibility-') -or
    -not $agentDagSource.Contains("data-source={selectedObservation.source}") -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-reason"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-governance"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-context-id"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-evidence-strength"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-blocker"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-next-action"') -or
    -not $agentDagSource.Contains('data-testid="agent-dag-selected-node-simulation-boundary"') -or
    -not $agentDagSource.Contains("simulation_only={String(selectedNodeGovernance.simulationOnly)} / is_real_trade={String(selectedNodeGovernance.isRealTrade)} / evidence_usage={selectedNodeGovernance.evidenceUsage} / strong_conclusion_allowed={String(selectedNodeGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $agentDagSource.Contains("nodesDraggable={false}") -or
    -not $agentDagSource.Contains("panOnDrag") -or
    -not $agentDagSource.Contains("onNodeClick={handleNodeClick}") -or
    -not $agentDagSource.Contains('role="button"') -or
    -not $agentDagSource.Contains("tabIndex={0}") -or
    -not $agentDagSource.Contains("aria-pressed={item.node.id === selectedFlowNodeId}") -or
    -not $agentDagSource.Contains("onKeyDown={(event)") -or
    -not $agentDagSource.Contains("selectedObservation") -or
    -not $agentDagSource.Contains('agent-dag-result-row-') -or
    -not $agentDagSource.Contains("profileFor(row, trace, runner)") -or
    -not $agentDagSource.Contains("usageTokens(runner.usage)") -or
    -not $agentDagSource.Contains("currentRun.tokenUsage?.metering_status") -or
    -not $agentDagSource.Contains("MOCK")) {
  throw "AgentDagPage is missing LLM output source and live-call evidence linkage"
}
if (-not $agentDebateSource.Contains("usageStats.llm") -or
    -not $agentDebateSource.Contains("usageStats.degraded") -or
    -not $agentDebateSource.Contains("LLM status:") -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-source-summary"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-metering-status"') -or
    -not $agentDebateSource.Contains('agent-debate-token-row-') -or
    -not $agentDebateSource.Contains("provider usage") -or
    -not $agentDebateSource.Contains("tokenUsage?.metering_status") -or
    -not $agentDebateSource.Contains("Mock/sample")) {
  throw "AgentDebatePage is missing token/LLM source evidence linkage"
}
if (-not $agentDebateSource.Contains("type AgentDebateEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $agentDebateSource.Contains("type AgentDebateEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $agentDebateSource.Contains("'SUPPORTING_ONLY'") -or
    $agentDebateSource.Contains("evidenceStrength = 'HIGH'") -or
    $agentDebateSource.Contains("evidenceStrength: 'HIGH'") -or
    $agentDebateSource.Contains("evidenceStrength = 'STRONG'") -or
    $agentDebateSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $agentDebateSource.Contains("function buildAgentDebateGovernance") -or
    -not $agentDebateSource.Contains("NODE_SUMMARY_FALLBACK_ONLY") -or
    -not $agentDebateSource.Contains("MOCK_OUTPUT_PRESENT") -or
    -not $agentDebateSource.Contains("NO_PROVIDER_USAGE") -or
    -not $agentDebateSource.Contains("paperTrading.simulation_only === true") -or
    -not $agentDebateSource.Contains("paperTrading.is_real_trade === true") -or
    -not $agentDebateSource.Contains("namespace !== 'SIM_*'") -or
    -not $agentDebateSource.Contains("latestAction.startsWith('SIM_')") -or
    -not $agentDebateSource.Contains("evidenceUsage") -or
    -not $agentDebateSource.Contains("strongConclusionAllowed") -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-governance"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-governance-id"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-evidence-strength"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-blocker"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-next-action"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-simulation-boundary"') -or
    -not $agentDebateSource.Contains("simulation_only={String(debateGovernance.simulationOnly)} / is_real_trade={String(debateGovernance.isRealTrade)} / evidence_usage={debateGovernance.evidenceUsage} / strong_conclusion_allowed={String(debateGovernance.strongConclusionAllowed)} / SIM_*")) {
  throw "AgentDebatePage is missing visible debate ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $strictAuthBrowserSource.Contains("runAgentDagDebateEvidenceScenario") -or
    -not $strictAuthBrowserSource.Contains("buildAgentDagFailureFixture") -or
    -not $strictAuthBrowserSource.Contains("buildAgentDagStateMatrixFixture") -or
    -not $strictAuthBrowserSource.Contains("react-flow__controls-zoomin") -or
    -not $strictAuthBrowserSource.Contains("react-flow__controls-fitview") -or
    -not $strictAuthBrowserSource.Contains("react-flow__pane") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG LLM evidence") -or
    -not $strictAuthBrowserSource.Contains("assertAgentDagVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("assertAgentDebateVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent Debate visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG viewport controls") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG viewport pan") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG node interaction") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG multi-node keyboard interaction") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG failure/degraded fixture") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent DAG state matrix fixture") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Agent Debate LLM evidence")) {
  throw "strict-auth browser smoke is missing Agent DAG/Debate LLM evidence coverage"
}
if (-not $strictAuthBrowserSource.Contains("Dashboard /api/metrics request did not include the expected Authorization bearer token") -or
    -not $strictAuthBrowserSource.Contains("dashboard-llm-live-call-health") -or
    -not $strictAuthBrowserSource.Contains("dashboard-llm-live-call-failure-reason") -or
    -not $strictAuthBrowserSource.Contains("assertDashboardVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Dashboard visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Dashboard LLM live-call health")) {
  throw "strict-auth browser smoke is missing Dashboard LLM live-call health coverage"
}
if ($appShellSource -notmatch "useCurrentRunHydration" -or $runHydrationSource -notmatch "refreshRun\(linkedRunId\)" -or $runHydrationSource -notmatch "loadRunHistory\(\)") {
  throw "AppShell is not wired to centralized current-run hydration"
}
if ($runHydrationSource -notmatch "NON_ANALYSIS_RUN_QUERY_ROUTES" -or $runHydrationSource -notmatch "/research-lab/backtest") {
  throw "current-run hydration does not protect non-analysis run_id routes"
}
$topBarHydrationMarkers = @(
  "function linkedAnalysisRunId",
  "NON_ANALYSIS_RUN_QUERY_ROUTES",
  "/research-lab/backtest",
  "isLinkedRunPending",
  "displayedRun = isLinkedRunPending ? undefined : currentRun",
  "topbar-current-run-id",
  "topbar-current-run-loading"
)
foreach ($marker in $topBarHydrationMarkers) {
  if (-not $topBarSource.Contains($marker)) {
    throw "TopBar must not expose a stale current-run context while URL-linked run hydration is pending: missing $marker"
  }
}
if ($historySelectorSource -notmatch "void loadHistory\(\)" -or $historySelectorSource -match "useEffect") {
  throw "HistorySelector should refresh on open and leave initial current-run hydration to AppShell"
}
if ($backendStoreSource -match "isCoreReady:\s*isBackendConnected\s*(,|\})" -or
    $backendStoreSource.Contains("isBackendConnected || startupStatus.coreReady") -or
    -not $backendStoreSource.Contains("isCoreReady: isBackendConnected && startupStatus.coreReady") -or
    -not $backendStoreSource.Contains("startupStatus: undefined, isCoreReady: false")) {
  throw "Backend health store must not mark core ready from /health alone"
}
if (-not $runHistoryHelperSource.Contains("isHiddenRunHistoryItem") -or
    -not $runHistoryHelperSource.Contains("visibleRunHistory") -or
    -not $runHistoryHelperSource.Contains("P2_CLOSED_LOOP_SAMPLE") -or
    -not $historySelectorSource.Contains("../../utils/runHistory") -or
    -not $historySelectorSource.Contains("visibleRunHistory(runHistory, { preserveRunIds: [currentRunId] })") -or
    -not $liveRunSource.Contains("../../utils/runHistory") -or
    -not $liveRunSource.Contains("const runId = deepLinkedRunId || currentRunId || currentRun?.runId") -or
    -not $liveRunSource.Contains("visibleRunHistory(runHistory, { preserveRunIds: [runId, deepLinkedRunId] })") -or
    -not $dataCompressionSource.Contains("../../utils/runHistory") -or
    -not $dataCompressionSource.Contains("visibleRunHistory(runHistory, { preserveRunIds: [selectedRunId, currentRunId] })")) {
  throw "Run history sample filtering should use the shared helper across global, live-run, and data-compression selectors"
}
if ($operatorContextSource -notmatch "setOperatorApiToken" -or
    $operatorContextSource -notmatch "Authorization = ``Bearer" -or
    -not $operatorContextSource.Contains("const API_TOKEN_STORAGE_KEY = 'super.operatorApiToken'") -or
    -not $operatorContextSource.Contains("window.sessionStorage.getItem(API_TOKEN_STORAGE_KEY)") -or
    -not $operatorContextSource.Contains("window.sessionStorage.setItem(API_TOKEN_STORAGE_KEY, token)") -or
    -not $operatorContextSource.Contains("window.sessionStorage.removeItem(API_TOKEN_STORAGE_KEY)") -or
    $operatorContextSource -match "localStorage\.setItem\(STORAGE_KEY, JSON\.stringify\(value\)" -or
    $operatorContextSource -match "localStorage\.setItem\(API_TOKEN_STORAGE_KEY") {
  throw "operatorContext is missing same-tab API token persistence or may persist token-bearing context to localStorage"
}
if ($streamClientSource -notmatch "authToken" -or
    $streamClientSource -notmatch "EventSourcePolyfill" -or
    $streamClientSource -notmatch "Authorization: ``Bearer" -or
    $streamClientSource -match "api_key" -or
    -not $streamClientSource.Contains("'RUN_STALE_RECOVERED'")) {
  throw "streamClient is missing header-based EventSource auth or still exposes query-token support"
}
if (-not $streamClientSource.Contains("assertStreamMessage") -or
    -not $streamClientSource.Contains("JSON.parse(event.data) as unknown") -or
    -not $streamClientSource.Contains("Unexpected SSE stream message: missing event_type")) {
  throw "streamClient is missing guarded EventSource message parsing"
}
if (-not $analysisStoreSource.Contains("function mergeLiveEvents") -or
    -not $analysisStoreSource.Contains("function runLiveEvents") -or
    -not $analysisStoreSource.Contains("streamEventsToAuditEvents(run.streamEvents, run.runId)") -or
    -not $analysisStoreSource.Contains('simulation_only=true / is_real_trade=false / evidence_usage=${evidenceUsage} / strong_conclusion_allowed=${strongConclusionAllowed} / ${namespace}') -or
    -not $analysisStoreSource.Contains("event.runId === runId") -or
    -not $analysisStoreSource.Contains("mergeLiveEvents(state.liveEvents, runLiveEvents(run), run.runId)") -or
    -not $analysisStoreSource.Contains("mergeLiveEvents(state.liveEvents, runLiveEvents(latestRun), latestRun.runId)") -or
    -not $analysisClientSource.Contains("assertRunStreamEvent") -or
    -not $analysisClientSource.Contains("function assertSimulationBoundaryPayload") -or
    -not $analysisClientSource.Contains('streamEvents ${index} payload must be an object') -or
    -not $analysisClientSource.Contains('assertSimulationBoundaryPayload(value.payload, `streamEvents ${index} payload`)') -or
    -not $analysisClientSource.Contains('${label} action must use SIM_*') -or
    -not $analysisClientSource.Contains("value.streamEvents") -or
    -not $typesSource.Contains("streamEvents?: RunStreamEvent[]")) {
  throw "analysis store is missing same-run live/stream event merge protection or guarded streamEvents contract"
}
if ($liveRunSource -notmatch "getOperatorApiToken" -or
    $liveRunSource -notmatch "authToken: streamAuthToken" -or
    -not $liveRunSource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $liveRunSource.Contains('const canCancelRun = canControlLiveRun && canCancelRunByStatus') -or
    -not $liveRunSource.Contains('const canRetryRun = canControlLiveRun && canRetryRunByStatus') -or
    -not $liveRunSource.Contains('simulation_only=true / is_real_trade=false / evidence_usage=${evidenceUsage} / strong_conclusion_allowed=${strongConclusionAllowed} / ${namespace}') -or
    -not $liveRunSource.Contains('if (!canControlLiveRun)') -or
    -not $liveRunSource.Contains('liveRunControlDisabledReason') -or
    -not $liveRunSource.Contains('data-testid="live-run-console"') -or
    -not $liveRunSource.Contains('data-testid="live-run-current-run-id"') -or
    -not $liveRunSource.Contains('data-testid="live-run-stream-status"') -or
    -not $liveRunSource.Contains('data-testid="live-run-job-lifecycle"') -or
    -not $liveRunSource.Contains('data-testid="live-run-control-role"') -or
    -not $liveRunSource.Contains('data-testid="live-run-control-disabled-reason"') -or
    -not $liveRunSource.Contains('data-testid="live-run-cancel-run"') -or
    -not $liveRunSource.Contains('data-testid="live-run-retry-run"') -or
    -not $liveRunSource.Contains('data-testid="live-run-final-action"') -or
    -not $liveRunSource.Contains('data-testid="live-run-stream-error"') -or
    -not $liveRunSource.Contains('live-run-event-${event.eventType}') -or
    -not $liveRunSource.Contains('data-status-after={event.statusAfter}') -or
    -not $liveRunSource.Contains("'RUN_STALE_RECOVERED'")) {
  throw "LiveRunConsole is missing stream auth or operator-gated run controls"
}
if (-not $finalWriterSource.Contains('data-testid="final-writer-page"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-page-loading"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-current-run-id"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-data-provenance"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-source-freshness"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-final-action"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-sections"') -or
    -not $finalWriterSource.Contains("useSearchParams") -or
    -not $finalWriterSource.Contains("refreshRun(linkedRunId)")) {
  throw "FinalWriterPage is missing stable report-chain browser hooks"
}
if (-not $finalWriterSource.Contains("type FinalWriterEvidenceStrength = 'LOW' | 'MEDIUM'") -or
    $finalWriterSource.Contains("type FinalWriterEvidenceStrength = 'SUPPORTING_ONLY'") -or
    $finalWriterSource.Contains("'SUPPORTING_ONLY'") -or
    $finalWriterSource.Contains("evidenceStrength = 'HIGH'") -or
    $finalWriterSource.Contains("evidenceStrength: 'HIGH'") -or
    $finalWriterSource.Contains("evidenceStrength = 'STRONG'") -or
    $finalWriterSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $finalWriterSource.Contains("function buildFinalWriterGovernance") -or
    -not $finalWriterSource.Contains("finalWriterActionNeedsReview(finalAction)") -or
    -not $finalWriterSource.Contains("paperTrading.simulation_only === true") -or
    -not $finalWriterSource.Contains("paperTrading.is_real_trade === true") -or
    -not $finalWriterSource.Contains("namespace !== 'SIM_*'") -or
    -not $finalWriterSource.Contains("latestAction.startsWith('SIM_')") -or
    -not $finalWriterSource.Contains("evidenceUsage") -or
    -not $finalWriterSource.Contains("strongConclusionAllowed") -or
    -not $finalWriterSource.Contains("finalWriter?.humanConfirmationRequired !== true") -or
    -not $finalWriterSource.Contains('data-testid="final-writer-governance"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-governance-id"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-evidence-strength"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-blocker"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-next-action"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-simulation-boundary"') -or
    -not $finalWriterSource.Contains("simulation_only={String(finalWriterGovernance.simulationOnly)} / is_real_trade={String(finalWriterGovernance.isRealTrade)} / evidence_usage={finalWriterGovernance.evidenceUsage} / strong_conclusion_allowed={String(finalWriterGovernance.strongConclusionAllowed)} / SIM_*")) {
  throw "FinalWriterPage is missing visible report ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $antiConclusionSource.Contains('data-testid="anti-conclusion-simulation-boundary"') -or
    -not $antiConclusionSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $antiConclusionSource.Contains("const linkedRunId = searchParams.get('run_id')?.trim() || ''") -or
    -not $antiConclusionSource.Contains("refreshRun(linkedRunId)") -or
    -not $antiConclusionSource.Contains('data-testid="anti-conclusion-page-loading"') -or
    -not $antiConclusionSource.Contains('data-testid="anti-conclusion-current-run-id"') -or
    -not $antiConclusionSource.Contains("simulation_only=true / is_real_trade=false / evidence_usage=anti_conclusion_review_only / strong_conclusion_allowed=false / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("assertAntiConclusionVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("AntiConclusion cold run hydrate") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser AntiConclusion cold deep link hydration") -or
    -not $strictAuthBrowserSource.Contains("anti-conclusion-simulation-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser AntiConclusion visible review boundary")) {
  throw "AntiConclusionPage is missing visible review-only simulation-boundary guardrails"
}
if ($backendStatusSource -notmatch "setOperatorApiToken" -or $backendStatusSource -notmatch "clearOperatorApiToken") {
  throw "BackendStatusPage is missing operator API token controls"
}
if (-not $backendStatusSource.Contains('data-testid="backend-operator-token-apply"') -or
    -not $backendStatusSource.Contains('data-testid="backend-operator-token-clear"') -or
    -not $strictAuthBrowserSource.Contains("backend-operator-token-apply") -or
    -not $strictAuthBrowserSource.Contains("backend-operator-token-clear") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser operator token reload persistence") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser operator token clear removes reload auth")) {
  throw "BackendStatusPage strict-auth token controls are missing reload or clear browser coverage"
}
if ($analysisClientSource -notmatch "getAnalysisJobAttempts" -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/jobs/attempts?') -or
    -not $analysisClientSource.Contains("return assertAnalysisJobAttempts(attempts)") -or
    -not $analysisClientSource.Contains('getAnalysisJobs') -or
    -not $analysisClientSource.Contains('getAnalysisJobSummary') -or
    -not $analysisClientSource.Contains('analysisJobSearchParams') -or
    -not $analysisClientSource.Contains("search.append('status', status)") -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/jobs?') -or
    -not $analysisClientSource.Contains('request<unknown>(`/analysis/jobs/summary?') -or
    -not $typesSource.Contains('external_queue_status?: AnalysisJobExternalQueueStatus') -or
    -not $typesSource.Contains('analysis_job_external_queue_status_v1') -or
    -not $typesSource.Contains('claim_status?: string') -or
    -not $typesSource.Contains('idempotency_scope?: string') -or
    -not $typesSource.Contains('audit_stream?: string') -or
    -not $typesSource.Contains('dead_letter_queue?: string') -or
    -not $typesSource.Contains('visibility_timeout_seconds?: number | null') -or
    -not $analysisJobStoreSource.Contains('EXTERNAL_QUEUE_STATUS_SCHEMA_VERSION = "analysis_job_external_queue_status_v1"') -or
    -not $analysisJobStoreSource.Contains('TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE') -or
    -not $analysisJobStoreSource.Contains('"claim_status": _safe_sidecar_text') -or
    -not $analysisJobStoreSource.Contains('"visibility_timeout_seconds": _safe_optional_sidecar_int') -or
    -not $analysisJobStoreSource.Contains('"external_queue_status": external_queue') -or
    -not $analysisClientSource.Contains("searchParams.set('offset'") -or
    $analysisClientSource -notmatch "assertAnalysisJobAttempt" -or
    $backendStatusSource -notmatch "AnalysisJobQueuePanel" -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-external-queue-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-external-queue-readiness"') -or
    -not $backendStatusSource.Contains("externalQueueBadgeStatus") -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-filter"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-page"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-total"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-prev"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-next"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-queue-refresh"') -or
    -not $backendStatusSource.Contains("ANALYSIS_JOB_STATUS_FILTERS") -or
    -not $backendStatusSource.Contains('backend-analysis-job-queue-row-') -or
    -not $backendStatusSource.Contains('backend-analysis-job-lease-') -or
    -not $backendStatusSource.Contains($backendExpiredLeaseText) -or
    $backendStatusSource -notmatch "AnalysisJobAttemptsPanel" -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-attempt-filter"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-attempt-apply"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-attempt-page"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-attempt-prev"') -or
    -not $backendStatusSource.Contains('data-testid="backend-analysis-job-attempt-next"') -or
    -not $backendStatusSource.Contains("setAppliedAttemptRunFilter") -or
    -not $backendStatusSource.Contains("setJobAttemptsOffset(0)") -or
    -not $backendStatusSource.Contains("ANALYSIS_JOB_PAGE_SIZE") -or
    -not $backendStatusSource.Contains("runId: normalizedRunId || undefined") -or
    -not $backendStatusSource.Contains("operator.apiTokenSet, operator.id, operator.role") -or
    -not $strictAuthBrowserWrapperSource.Contains('TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE') -or
    -not $strictAuthBrowserWrapperSource.Contains('claim_status = "READY"') -or
    -not $strictAuthBrowserSource.Contains('ok strict-auth browser Backend Status analysis job external queue readiness') -or
    -not $strictAuthBrowserSource.Contains('analysis-job-audit') -or
    -not $strictAuthBrowserSource.Contains('isAnalysisJobQueueSummaryResponse') -or
    -not $strictAuthBrowserSource.Contains('Backend Status analysis job external queue sidecar') -or
    $backendStatusSource -notmatch 'data-testid="backend-analysis-job-attempts"') {
  throw "BackendStatusPage is missing analysis job attempt diagnostics linkage"
}
if (-not $strictAuthBrowserSource.Contains("runBackendAttemptDiagnosticsScenario") -or
    -not $strictAuthBrowserSource.Contains("seedBackendAttemptDiagnosticsRun") -or
    -not $strictAuthBrowserSource.Contains("Backend Status attempt diagnostics load") -or
    -not $strictAuthBrowserSource.Contains("Backend Status attempt diagnostics filtered load") -or
    -not $strictAuthBrowserSource.Contains("Backend Status attempt diagnostics seeded count") -or
    -not $strictAuthBrowserSource.Contains("Backend Status seeded attempt row") -or
    -not $strictAuthBrowserSource.Contains("Backend Status analysis job queue load") -or
    -not $strictAuthBrowserSource.Contains("Backend Status analysis job queue retry load") -or
    -not $strictAuthBrowserSource.Contains("backend-analysis-job-queue-total") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status analysis job queue") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status attempt diagnostics")) {
  throw "strict-auth browser smoke is missing Backend Status attempt diagnostics coverage"
}
if (-not $strictAuthBrowserSource.Contains("runDashboardScenario") -or
    -not $strictAuthBrowserSource.Contains("Dashboard run history load") -or
    -not $strictAuthBrowserSource.Contains("Dashboard selected run load") -or
    -not $strictAuthBrowserSource.Contains("Dashboard knowledge regression load") -or
    -not $strictAuthBrowserSource.Contains("dashboard-decision-workbench") -or
    -not $strictAuthBrowserSource.Contains("dashboard-trade-boundary") -or
    -not $strictAuthBrowserSource.Contains("dashboard-data-provenance") -or
    -not $strictAuthBrowserSource.Contains("dashboard-evidence-spine") -or
    -not $strictAuthBrowserSource.Contains("dashboard-source-freshness") -or
    -not $strictAuthBrowserSource.Contains("Dashboard simulation-only boundary") -or
    -not $strictAuthBrowserSource.Contains("Dashboard non-real-trade boundary") -or
    -not $strictAuthBrowserSource.Contains("dashboard-research-closed-loop-entry") -or
    -not $strictAuthBrowserSource.Contains("dashboard-research-closed-loop-current-step") -or
    -not $strictAuthBrowserSource.Contains("dashboard-research-closed-loop-evidence-strength") -or
    -not $strictAuthBrowserSource.Contains("dashboard-research-closed-loop-blocker") -or
    -not $strictAuthBrowserSource.Contains("dashboard-research-closed-loop-next-action") -or
    -not $strictAuthBrowserSource.Contains("weak Backtest evidence review-gated") -or
    -not $strictAuthBrowserSource.Contains("Dashboard Research closed-loop sample creation") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Dashboard run/provenance/knowledge regression and closed-loop entry")) {
  throw "strict-auth browser smoke is missing Dashboard run/provenance/knowledge regression coverage"
}
if (-not $strictAuthBrowserSource.Contains("live-run task panels") -or
    -not $strictAuthBrowserSource.Contains("portfolioDefaultSymbol") -or
    -not $strictAuthBrowserSource.Contains("new-task-portfolio-risk-preflight") -or
    -not $strictAuthBrowserSource.Contains("assertNewTaskPortfolioRiskBoundary") -or
    -not $strictAuthBrowserSource.Contains("New Task portfolio preflight boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("assertNewTaskVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("await assertNewTaskVisibleBoundary(page)") -or
    -not $strictAuthBrowserSource.Contains("new-task-run-simulation-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser New Task visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("observedStreamRequests") -or
    -not $strictAuthBrowserSource.Contains("page.on('request', streamRequestHandler)") -or
    -not $strictAuthBrowserSource.Contains($newTaskPreTaskRiskPromptText) -or
    -not $strictAuthBrowserSource.Contains($newTaskBrokerImportTemplateText) -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser New Task portfolio risk boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser New Task portfolio risk preflight") -or
    -not $strictAuthBrowserSource.Contains("New Task symbol remained empty after portfolio-context fallback") -or
    -not $strictAuthBrowserSource.Contains("buildLiveRunTerminalFixture") -or
    -not $strictAuthBrowserSource.Contains("RUN_LIVE_STALE_RECOVERED_BROWSER_SMOKE") -or
    -not $strictAuthBrowserSource.Contains("terminal fixture load") -or
    -not $strictAuthBrowserSource.Contains("terminal visible stream boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser live-run terminal stream event") -or
    -not $strictAuthBrowserSource.Contains("Final Writer report load") -or
    -not $strictAuthBrowserSource.Contains("/final?run_id=") -or
    -not $strictAuthBrowserSource.Contains("retrying SPA final route without reloading auth state") -or
    -not $strictAuthBrowserSource.Contains("pageApiJson") -or
    -not $strictAuthBrowserSource.Contains("using page API fallback") -or
    -not $strictAuthBrowserSource.Contains("using direct API fallback") -or
    -not $strictAuthBrowserSource.Contains("isRetryableFetchError") -or
    -not $strictAuthBrowserSource.Contains("retrying direct API call") -or
    -not $strictAuthBrowserSource.Contains("timed out after") -or
    -not $strictAuthBrowserSource.Contains("final-writer-current-run-id") -or
    -not $strictAuthBrowserSource.Contains("final-writer-data-provenance") -or
    -not $strictAuthBrowserSource.Contains("final-writer-source-freshness") -or
    -not $strictAuthBrowserSource.Contains("assertFinalWriterVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Final Writer visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser final report chain") -or
    -not $strictAuthBrowserSource.Contains("runAuditLogScenario") -or
    -not $strictAuthBrowserSource.Contains("Audit Log run audit load") -or
    -not $strictAuthBrowserSource.Contains("PORTFOLIO_SNAPSHOT_ATTACHED") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Audit Log run audit")) {
  throw "strict-auth browser smoke is missing New Task -> Live Run -> Final report coverage"
}
if (-not $strictAuthBrowserSource.Contains("SCENARIO_GROUPS") -or
    -not $strictAuthBrowserSource.Contains("selectedScenarioGroups") -or
    -not $strictAuthBrowserSource.Contains("scenario group platform") -or
    -not $strictAuthBrowserSource.Contains("scenario group signalops") -or
    -not $strictAuthBrowserSource.Contains("scenario group research-backtest") -or
    -not $strictAuthBrowserSource.Contains("scenario group portfolio-live-plugin") -or
    -not $strictAuthBrowserWrapperSource.Contains("[string]`$Scenario") -or
    -not $strictAuthBrowserWrapperSource.Contains("STRICT_AUTH_BROWSER_SCENARIO") -or
    -not $strictAuthBrowserWrapperSource.Contains("TIANYUAN_UV_CACHE_DIR") -or
    -not $strictAuthBrowserWrapperSource.Contains('[int]$MaxAttempts = 60') -or
    -not $strictAuthBrowserWrapperSource.Contains("TIANYUAN_STRICT_AUTH_BACKEND_HEALTH_ATTEMPTS") -or
    -not $strictAuthBrowserWrapperSource.Contains('Resolve-PositiveIntEnv "TIANYUAN_STRICT_AUTH_BACKEND_HEALTH_ATTEMPTS" 360') -or
    -not $strictAuthBrowserWrapperSource.Contains('Wait-ForJson "$backendUrl/api/health" "backend health" $backendProcess $backendHealthAttempts') -or
    -not (Test-Path -LiteralPath $strictAuthSmokeRequirementsPath) -or
    -not $strictAuthBrowserWrapperSource.Contains('$smokeRequirements = Join-Path $backendRoot "requirements-smoke.txt"') -or
    -not $strictAuthBrowserWrapperSource.Contains('$requirements = if (Test-Path -LiteralPath $smokeRequirements) { $smokeRequirements } else { Join-Path $backendRoot "requirements.txt" }') -or
    -not $strictAuthSmokeRequirementsSource.Contains("fastapi==0.104.1") -or
    -not $strictAuthSmokeRequirementsSource.Contains("uvicorn[standard]==0.24.0") -or
    $strictAuthSmokeRequirementsSource.Contains("scipy") -or
    $strictAuthSmokeRequirementsSource.Contains("scikit-learn") -or
    $strictAuthSmokeRequirementsSource.Contains("akshare") -or
    $strictAuthSmokeRequirementsSource.Contains("tushare") -or
    -not $strictAuthBrowserWrapperSource.Contains("TIANYUAN_ANALYSIS_JOBS_FILE") -or
    -not $strictAuthBrowserWrapperSource.Contains("Normalize-ProcessPathEnvironment") -or
    -not $packageSource.Contains("smoke:strict-auth-browser:platform") -or
    -not $packageSource.Contains("smoke:strict-auth-browser:signalops") -or
    -not $packageSource.Contains("smoke:strict-auth-browser:research-backtest") -or
    -not $packageSource.Contains("smoke:strict-auth-browser:portfolio-live-plugin") -or
    -not $packageSource.Contains("smoke:strict-auth-browser:matrix") -or
    -not $packageSource.Contains("smoke:analysis-worker") -or
    -not $packageSource.Contains("smoke:closed-loop-participation") -or
    -not $packageSource.Contains("validate:module-participation") -or
    -not $packageSource.Contains("validate:phase1-3") -or
    -not $packageSource.Contains("validate:premerge") -or
    -not $strictAuthBrowserMatrixSource.Contains("portfolio-live-plugin") -or
    -not $strictAuthBrowserMatrixSource.Contains("strict-auth scenario matrix ok") -or
    -not $strictAuthBrowserMatrixSource.Contains("-Scenario `$scenario") -or
    -not $strictAuthBrowserMatrixSource.Contains("-ExecutionPolicy Bypass") -or
    -not $strictAuthBrowserSource.Contains("navigateToResearchLoopsPage") -or
    -not $strictAuthBrowserSource.Contains("Research SignalOps prerequisite Research route") -or
    -not $preMergeValidationSource.Contains("test:backend") -or
    -not $preMergeValidationSource.Contains("[switch]`$SkipAnalysisWorkerSmoke") -or
    -not $preMergeValidationSource.Contains("analysis worker smoke") -or
    -not $preMergeValidationSource.Contains("smoke:analysis-worker") -or
    -not $preMergeValidationSource.Contains("[switch]`$SkipClosedLoopParticipation") -or
    -not $preMergeValidationSource.Contains("closed-loop participation smoke") -or
    -not $preMergeValidationSource.Contains("smoke:closed-loop-participation") -or
    -not $preMergeValidationSource.Contains("typecheck") -or
    -not $preMergeValidationSource.Contains("lint") -or
    -not $preMergeValidationSource.Contains("build") -or
    -not $preMergeValidationSource.Contains("smoke:frontend") -or
    -not $preMergeValidationSource.Contains("[switch]`$SkipResponsiveSmoke") -or
    -not $preMergeValidationSource.Contains("frontend responsive smoke") -or
    -not $preMergeValidationSource.Contains("smoke:frontend:responsive") -or
    -not $preMergeValidationSource.Contains("smoke:strict-auth-browser:matrix") -or
    -not $testBackendSource.Contains("TIANYUAN_BACKEND_TEST_PYTHON") -or
    -not $testBackendSource.Contains('$RepoVenvPython = Join-Path $Root ".venv\Scripts\python.exe"') -or
    -not $testBackendSource.Contains("function Test-UsablePython") -or
    -not $testBackendSource.Contains("function Resolve-BackendPythonOverride") -or
    -not $testBackendSource.Contains('$UseDirectPython = $false') -or
    -not $testBackendSource.Contains('if ($BackendPythonOverride)') -or
    -not $testBackendSource.Contains('elseif (Test-UsablePython $RepoVenvPython)') -or
    -not $testBackendSource.Contains('& $PythonExe @PytestCommandArgs') -or
    -not $testBackendSource.Contains('if (-not $UseDirectPython -and -not (Get-Command uv.exe') -or
    -not $analysisWorkerSmokeSource.Contains("TIANYUAN_ANALYSIS_WORKER_CLI_TIMEOUT_SECONDS") -or
    -not $analysisWorkerSmokeSource.Contains('$powershellCommand = Get-Command powershell.exe') -or
    -not $analysisWorkerSmokeSource.Contains('analysis-worker.ps1') -or
    $analysisWorkerSmokeSource.Contains('"worker:analysis"') -or
    -not $analysisWorkerSmokeSource.Contains("function Stop-ProcessTree") -or
    -not $analysisWorkerSmokeSource.Contains('ParentProcessId -eq $ProcessId') -or
    -not $analysisWorkerSmokeSource.Contains('$workerProcess.WaitForExit($workerTimeoutMs)') -or
    -not $analysisWorkerSmokeSource.Contains('$workerProcess.Refresh()') -or
    -not $analysisWorkerSmokeSource.Contains('$workerExitCode = $workerProcess.ExitCode') -or
    -not $analysisWorkerSmokeSource.Contains("analysis worker CLI smoke timed out") -or
    -not $analysisWorkerSmokeSource.Contains('Stop-ProcessTree -ProcessId $workerProcess.Id') -or
    -not $analysisWorkerScriptSource.Contains("TIANYUAN_UV_CACHE_DIR") -or
    -not $analysisWorkerScriptSource.Contains('$env:UV_CACHE_DIR = $UvCacheDir') -or
    -not $analysisWorkerScriptSource.Contains("TIANYUAN_BACKEND_TEST_PYTHON") -or
    -not $analysisWorkerScriptSource.Contains('$RepoVenvPython = Join-Path $Root ".venv\Scripts\python.exe"') -or
    -not $analysisWorkerScriptSource.Contains("function Test-UsablePython") -or
    -not $analysisWorkerScriptSource.Contains("function Resolve-WorkerPythonOverride") -or
    -not $analysisWorkerScriptSource.Contains('$UseDirectPython = $false') -or
    -not $analysisWorkerScriptSource.Contains('if ($WorkerPythonOverride)') -or
    -not $analysisWorkerScriptSource.Contains('elseif (Test-UsablePython $RepoVenvPython)') -or
    -not $analysisWorkerScriptSource.Contains('& $PythonExe @PythonWorkerArgs') -or
    -not $analysisWorkerScriptSource.Contains('if (-not $UseDirectPython -and -not (Get-Command uv.exe') -or
    -not $preMergeValidationSource.Contains("& `$npmCommand.Source @(`$step.Args)")) {
  throw "strict-auth browser smoke scenario-group split is missing wrapper, package, or runtime guards"
}
if (-not $analysisWorkerSmokeSource.Contains("TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS") -or
    -not $analysisWorkerSmokeSource.Contains('$previousSqliteJobTimeout = $env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS') -or
    -not $analysisWorkerSmokeSource.Contains('$env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS = "2"') -or
    -not $analysisWorkerSmokeSource.Contains('$env:TIANYUAN_SQLITE_JOB_TIMEOUT_SECONDS = $previousSqliteJobTimeout')) {
  throw "analysis worker smoke must isolate SQLite job timeout for locked-database retries"
}
if (-not $backendStatusSource.Contains("healthTrendRows") -or
    -not $backendStatusSource.Contains("['24h', '7d', '30d']") -or
    -not $backendStatusSource.Contains($backendHealthTrendText) -or
    -not $backendStatusSource.Contains($backendSourceErrorsText) -or
    -not $backendStatusSource.Contains("llmFailureReasonRows") -or
    -not $backendStatusSource.Contains("failureReasons") -or
    -not $backendStatusSource.Contains("sampleFailures") -or
    -not $backendStatusSource.Contains("ProductionHealthWindow") -or
    -not $backendStatusSource.Contains("signedPercentLabel(trend?.llmSuccessRateDelta)") -or
    -not $backendStatusSource.Contains("signedPercentLabel(longTrend?.llmSuccessRateDelta)") -or
    -not $backendStatusSource.Contains("loadProductionHealth") -or
    -not $backendStatusSource.Contains('data-testid="backend-production-health-llm-failure-reasons"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-health-refresh"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-health-trend-deltas"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-health-trends"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-health-source-errors"') -or
    -not $strictAuthBrowserSource.Contains("Backend Status production health trend deltas") -or
    -not $strictAuthBrowserSource.Contains("vs 30d") -or
    -not $strictAuthBrowserSource.Contains("cross-page production health trend fixture") -or
    -not $researchClosureBrowserSource.Contains("verifyBackendStatusProductionHealth") -or
    -not $researchClosureBrowserSource.Contains("backend-production-health-llm-failure-reasons") -or
    -not $researchClosureBrowserSource.Contains("ok browser backend production health LLM failure reasons") -or
    -not $researchClosureBrowserSource.Contains("ok browser backend production health trends")) {
  throw "BackendStatusPage is missing production health 24h/7d/30d trend, LLM failure reason, or source-error linkage"
}
if (-not $strictAuthBrowserSource.Contains("assertPermissionMatrixVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("await assertPermissionMatrixVisibleBoundary(page)") -or
    -not $strictAuthBrowserSource.Contains("permission-matrix-simulation-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Permission Matrix visible review boundary")) {
  throw "strict-auth browser smoke is missing Permission Matrix visible review boundary coverage"
}
if (-not $strictAuthBrowserSource.Contains("assertExecutionVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("await assertExecutionVisibleBoundary(page)") -or
    -not $strictAuthBrowserSource.Contains("execution-simulation-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Execution visible review boundary")) {
  throw "strict-auth browser smoke is missing Execution visible review boundary coverage"
}
if (-not $strictAuthBrowserSource.Contains("assertGuardrailHubVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("await assertGuardrailHubVisibleBoundary(page)") -or
    -not $strictAuthBrowserSource.Contains("guardrail-hub-simulation-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Guardrail Hub visible review boundary")) {
  throw "strict-auth browser smoke is missing Guardrail Hub visible review boundary coverage"
}
if (-not $analysisClientSource.Contains("getProductionAlertStatus") -or
    -not $analysisClientSource.Contains("getProductionAlertExport") -or
    -not $analysisClientSource.Contains("handoffProductionAlertExport") -or
    -not $analysisClientSource.Contains("ProductionAlertExportHandoff") -or
    -not $analysisClientSource.Contains("dispatchProductionAlerts") -or
    -not $analysisClientSource.Contains("assertProductionAlertChannelStatus") -or
    -not $analysisClientSource.Contains("assertProductionAlertExportBundle") -or
    -not $analysisClientSource.Contains("assertProductionAlertExportHandoff") -or
    -not $analysisClientSource.Contains("assertProductionAlertDispatchResult") -or
    -not $analysisClientSource.Contains("assertProductionAlertEvent") -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/alerts/status?limit=${limit}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/alerts/export?limit=${limit}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/alerts/export/handoff?limit=${limit}`') -or
    -not $analysisClientSource.Contains("request<unknown>('/ops/alerts/dispatch'") -or
    -not $analysisClientSource.Contains(".then(assertProductionAlertChannelStatus)") -or
    -not $analysisClientSource.Contains(".then(assertProductionAlertExportBundle)") -or
    -not $analysisClientSource.Contains(".then(assertProductionAlertExportHandoff)") -or
    -not $analysisClientSource.Contains(".then(assertProductionAlertDispatchResult)") -or
    -not $analysisClientSource.Contains("/ops/alerts/export") -or
    -not $analysisClientSource.Contains("/ops/alerts/export/handoff") -or
    -not $analysisClientSource.Contains("'/ops/alerts/dispatch'") -or
    -not $backendStatusSource.Contains("production_alert_outbox_export_v1") -or
    -not $backendStatusSource.Contains("production_alert_outbox_export_handoff_v1") -or
    -not $backendStatusSource.Contains("ProductionAlertChannelPanel") -or
    -not $backendStatusSource.Contains("getProductionAlertStatus(10)") -or
    -not $backendStatusSource.Contains("getProductionAlertExport(50)") -or
    -not $backendStatusSource.Contains("handoffProductionAlertExport(50)") -or
    -not $backendStatusSource.Contains("dispatchProductionAlerts()") -or
    -not $backendStatusSource.Contains("canHandoffProductionAlertExport") -or
    -not $backendStatusSource.Contains("productionAlertAdminDisabledReason") -or
    -not $backendStatusSource.Contains("productionAlertAdminDisabledReason") -or
    -not $backendStatusSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-channel"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-provider"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-retry"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-export-ready"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-admin-role"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-admin-disabled-reason"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-export-endpoint"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-export"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-export-result"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-handoff"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-handoff-result"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-handoff-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-handoff-integrity"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-shipper-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-shipper-readiness"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-rule-policy"') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-rule-provider-acceptance"') -or
    -not $backendStatusSource.Contains("production_alert_rule_policy_v1") -or
    -not $backendStatusSource.Contains("production_alert_rule_provider_acceptance_v1") -or
    -not $backendStatusSource.Contains("matches_latest_inventory") -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-dispatch"') -or
    -not $backendStatusSource.Contains('adminDisabledReason={productionAlertAdminDisabledReason}') -or
    -not $backendStatusSource.Contains('title={adminDisabledReason}') -or
    -not $backendStatusSource.Contains('data-testid="backend-production-alert-latest"') -or
    -not $strictAuthBrowserWrapperSource.Contains("PRODUCTION_ALERT_EXPORT_HANDOFF_DIR") -or
    -not $strictAuthBrowserWrapperSource.Contains("PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE") -or
    -not $strictAuthBrowserSource.Contains("production_alert_outbox_export_handoff_v1") -or
    -not $strictAuthBrowserSource.Contains("production_alert_outbox_export_handoff_status_v1") -or
    -not $strictAuthBrowserSource.Contains("production_alert_outbox_export_handoff_inventory_v1") -or
    -not $strictAuthBrowserSource.Contains("production_alert_outbox_export_shipper_status_v1") -or
    -not $strictAuthBrowserSource.Contains("production-alert-events") -or
    -not $strictAuthBrowserSource.Contains("Backend Status production alert shipper readiness") -or
    -not $strictAuthBrowserSource.Contains("production_alert_rule_policy_v1") -or
    -not $strictAuthBrowserSource.Contains("production_alert_rule_provider_acceptance_v1") -or
    -not $strictAuthBrowserSource.Contains("backend-production-alert-rule-policy") -or
    -not $strictAuthBrowserSource.Contains("backend-production-alert-rule-provider-acceptance") -or
    -not $strictAuthBrowserSource.Contains("production_alert_outbox_export_handoff_manifest_v1") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status production alert rule provider acceptance") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status production alert export handoff") -or
    -not $analysisClientSource.Contains("external_provider") -or
    -not $analysisClientSource.Contains("external_delivery_status") -or
    -not $analysisClientSource.Contains("external_delivery_attempt_limit") -or
    -not $analysisClientSource.Contains("delivery_attempt_count") -or
    -not $analysisClientSource.Contains("ProductionAlertRulePolicy") -or
    -not $analysisClientSource.Contains("alert_rule_policy") -or
    -not $analysisClientSource.Contains("provider_acceptance") -or
    -not $analysisClientSource.Contains("matches_policy") -or
    -not $analysisClientSource.Contains("alert_rule_id") -or
    -not $analysisClientSource.Contains("external_aggregation_ready") -or
    -not $analysisClientSource.Contains("handoff_status") -or
    -not $analysisClientSource.Contains("checksum_mismatch_count") -or
    -not $analysisClientSource.Contains("shipper_status") -or
    -not $analysisClientSource.Contains("remote_object_key") -or
    -not $analysisClientSource.Contains("retention_status") -or
    -not $analysisClientSource.Contains("custody_status") -or
    -not $analysisClientSource.Contains("kms_key_ref") -or
    -not $analysisClientSource.Contains("search_index") -or
    -not $analysisClientSource.Contains("search_index_ready") -or
    -not $analysisClientSource.Contains("latest_bundle_checksum") -or
    -not $analysisClientSource.Contains("redaction_policy")) {
  throw "BackendStatusPage is missing production alert channel status/dispatch/export/handoff linkage"
}
if (-not $analysisClientSource.Contains("getOpsLogStatus") -or
    -not $analysisClientSource.Contains("queryOpsLogs") -or
    -not $analysisClientSource.Contains("getOpsLogExport") -or
    -not $analysisClientSource.Contains("handoffOpsLogExport") -or
    -not $analysisClientSource.Contains("OpsLogQueryResult") -or
    -not $analysisClientSource.Contains("OpsLogExportHandoff") -or
    -not $analysisClientSource.Contains("assertOpsLogStatus") -or
    -not $analysisClientSource.Contains("assertOpsLogQueryResult") -or
    -not $analysisClientSource.Contains("assertOpsLogExportBundle") -or
    -not $analysisClientSource.Contains("assertOpsLogExportHandoff") -or
    -not $analysisClientSource.Contains("assertOpsLogEvent") -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/logs/status?${search.toString()}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/logs/query?${search.toString()}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/logs/export?${search.toString()}`') -or
    -not $analysisClientSource.Contains('request<unknown>(`/ops/logs/export/handoff?${search.toString()}`') -or
    -not $analysisClientSource.Contains(".then(assertOpsLogStatus)") -or
    -not $analysisClientSource.Contains(".then(assertOpsLogQueryResult)") -or
    -not $analysisClientSource.Contains(".then(assertOpsLogExportBundle)") -or
    -not $analysisClientSource.Contains(".then(assertOpsLogExportHandoff)") -or
    -not $analysisClientSource.Contains("/ops/logs/status?") -or
    -not $analysisClientSource.Contains("/ops/logs/query?") -or
    -not $analysisClientSource.Contains("/ops/logs/export?") -or
    -not $analysisClientSource.Contains("/ops/logs/export/handoff?") -or
    -not $analysisClientSource.Contains("external_aggregation_ready") -or
    -not $analysisClientSource.Contains("retention_policy") -or
    -not $analysisClientSource.Contains("remote_object_key") -or
    -not $analysisClientSource.Contains("retention_status") -or
    -not $analysisClientSource.Contains("custody_status") -or
    -not $analysisClientSource.Contains("kms_key_ref") -or
    -not $analysisClientSource.Contains("search_index") -or
    -not $analysisClientSource.Contains("search_index_ready") -or
    -not $analysisClientSource.Contains("max_age_days") -or
    -not $analysisClientSource.Contains("handoff_status") -or
    -not $analysisClientSource.Contains("prune_on_read_or_write") -or
    -not $backendStatusSource.Contains("OpsLogPanel") -or
    -not $backendStatusSource.Contains("canHandoffOpsLogExport") -or
    -not $backendStatusSource.Contains("opsLogHandoffDisabledReason") -or
    -not $backendStatusSource.Contains("opsLogHandoffDisabledReason") -or
    -not $backendStatusSource.Contains("getOpsLogStatus(10)") -or
    -not $backendStatusSource.Contains("queryOpsLogs({ limit: 20") -or
    -not $backendStatusSource.Contains("getOpsLogExport(50)") -or
    -not $backendStatusSource.Contains("handoffOpsLogExport(50)") -or
    -not $backendStatusSource.Contains("time_based_retention_enabled") -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-export-ready"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff-role"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff-disabled-reason"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-export-endpoint"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-query-endpoint"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-query-text"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-query"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-query-result"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-export"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-export-result"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff-result"') -or
    -not $backendStatusSource.Contains('handoffDisabledReason={opsLogHandoffDisabledReason}') -or
    -not $backendStatusSource.Contains('title={handoffDisabledReason}') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-handoff-integrity"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-shipper-status"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-shipper-readiness"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-retention-policy"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-latest"') -or
    -not $backendStatusSource.Contains('data-testid="backend-ops-log-refresh"') -or
    -not $strictAuthBrowserWrapperSource.Contains("OPS_LOG_EXPORT_HANDOFF_DIR") -or
    -not $strictAuthBrowserSource.Contains("ops_log_export_handoff_v1") -or
    -not $strictAuthBrowserSource.Contains("ops_log_query_v1") -or
    -not $strictAuthBrowserSource.Contains("ops_log_export_handoff_status_v1") -or
    -not $strictAuthBrowserSource.Contains("ops_log_export_handoff_inventory_v1") -or
    -not $strictAuthBrowserSource.Contains("ops_log_export_shipper_status_v1") -or
    -not $strictAuthBrowserSource.Contains("ops-log-events") -or
    -not $strictAuthBrowserSource.Contains("remote_object_key") -or
    -not $strictAuthBrowserSource.Contains("Backend Status ops log shipper readiness") -or
    -not $strictAuthBrowserSource.Contains("ops_log_export_handoff_manifest_v1") -or
    -not $strictAuthBrowserSource.Contains("deployment_owned_after_handoff") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status ops log query") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backend Status ops log export handoff")) {
  throw "BackendStatusPage is missing ops event log status/export/handoff interaction linkage"
}
$dataReliabilityNetworkTimeoutText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("572R57uc5oiW5o6l5Y+j6LaF5pe2"))
if (-not $dataReliabilitySource.Contains("DataFreshnessSummary") -or
    -not $dataReliabilitySource.Contains("RunReliabilityEvidence") -or
    -not $dataReliabilitySource.Contains("useOperatorContext()") -or
    -not $dataReliabilitySource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $dataReliabilitySource.Contains("canRunDataReliabilityChecks") -or
    -not $dataReliabilitySource.Contains("dataReliabilityCheckDisabledReason") -or
    -not $dataReliabilitySource.Contains("if (!canRunDataReliabilityChecks)") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-page"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-diagnostic-boundary"') -or
    -not $dataReliabilitySource.Contains("diagnostic_only=true / simulation_only=true / is_real_trade=false / evidence_usage=monitoring_only / strong_conclusion_allowed=false / order_namespace=none") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-check-role"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-check-disabled-reason"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-adapter-check"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-symbol-check"') -or
    -not $dataReliabilitySource.Contains("disabled={loading || !canRunDataReliabilityChecks}") -or
    -not $dataReliabilitySource.Contains('data-testid={`data-reliability-symbol-diagnosis-${item.category}`}') -or
    -not $dataReliabilitySource.Contains("diagnosisLabel(item.diagnosis) || item.diagnosis") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-freshness-summary"') -or
    -not $dataReliabilitySource.Contains('testId="data-reliability-latest-check"') -or
    -not $dataReliabilitySource.Contains('testId="data-reliability-latest-failure"') -or
    -not $dataReliabilitySource.Contains('testId="data-reliability-fallback-count"') -or
    -not $dataReliabilitySource.Contains('testId="data-reliability-slowest-check"') -or
    -not $dataReliabilitySource.Contains("DataAdapterEvents") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-adapter-events"') -or
    -not $dataReliabilitySource.Contains("DataExternalMonitorStatus") -or
    -not $dataReliabilitySource.Contains("safeDisplayText") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-external-monitor-status"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-run-evidence-empty"') -or
    -not $dataReliabilitySource.Contains("buildDashboardProvenanceSummary(currentRun)") -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-current-run-id"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-data-provenance"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-source-freshness"') -or
    -not $dataReliabilitySource.Contains('data-testid="data-reliability-fallback-chain"') -or
    -not $dataReliabilitySource.Contains("provenanceSummary.freshnessItems") -or
    -not $dataReliabilityClientSource.Contains("DataReliabilityExternalMonitorStatus") -or
    -not $dataReliabilityClientSource.Contains("DataReliabilityEventItem") -or
    -not $dataReliabilityClientSource.Contains("/data-reliability/events") -or
    -not $dataReliabilitySource.Contains("fallbackUsed") -or
    -not $dataReliabilitySource.Contains("liveDataUsable") -or
    -not $strictAuthBrowserSource.Contains("runDataReliabilityScenario") -or
    -not $strictAuthBrowserSource.Contains("assertDataReliabilityDiagnosticBoundary") -or
    -not $strictAuthBrowserSource.Contains("Data Reliability diagnostic boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("**/api/data-reliability/adapters/check") -or
    -not $strictAuthBrowserSource.Contains("data-reliability-adapter-check") -or
    -not $strictAuthBrowserSource.Contains("adapterCheckRequested") -or
    -not $strictAuthBrowserSource.Contains("Data Reliability adapter-check write reload") -or
    -not $strictAuthBrowserSource.Contains("**/api/data-reliability/symbol-check") -or
    -not $strictAuthBrowserSource.Contains("data-reliability-symbol-diagnosis-realtime_quote") -or
    -not $strictAuthBrowserSource.Contains("NETWORK_TIMEOUT") -or
    -not $strictAuthBrowserSource.Contains($dataReliabilityNetworkTimeoutText) -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability diagnostic boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability symbol-check timeout diagnosis") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability freshness/fallback summary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability adapter event trail") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability external monitoring retention") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Data Reliability provenance/freshness")) {
  throw "DataReliabilityPage is missing source freshness/fallback/provenance coverage"
}
$dataReliabilityClientBoundaryMarkers = @(
  "assertDataReliabilitySnapshot",
  "assertDataReliabilitySummary",
  "assertDataReliabilityAdapter",
  "assertDataReliabilityMatrix",
  "assertDataReliabilityHistoryItem",
  "assertDataReliabilityEventItem",
  "assertDataReliabilityExternalMonitorStatus",
  "assertSymbolHealthResult",
  "request<unknown>('/data-reliability/snapshot'",
  "request<unknown>('/data-reliability/summary'",
  "request<unknown>('/data-reliability/adapters'",
  "request<unknown>('/data-reliability/adapters/check'",
  "request<unknown>('/data-reliability/matrix'",
  "request<unknown>('/data-reliability/symbol-check'",
  "timeoutMs: 45000",
  "request<unknown>('/data-reliability/history')",
  "request<unknown>('/data-reliability/events')",
  "}).then(assertDataReliabilitySnapshot)",
  "}).then(assertDataReliabilitySummary)",
  "}).then(assertDataReliabilityMatrix)",
  "}).then(assertSymbolHealthResult)",
  "ensureArray(items, 'data reliability adapters').map",
  "ensureArray(items, 'data reliability adapter check results').map",
  "ensureArray(items, 'data reliability history').map(assertDataReliabilityHistoryItem)",
  "ensureArray(items, 'data reliability events').map(assertDataReliabilityEventItem)",
  "data_reliability_external_monitor_status_v1"
)
foreach ($marker in $dataReliabilityClientBoundaryMarkers) {
  if (-not $dataReliabilityClientSource.Contains($marker)) {
    throw ("Data Reliability API client is missing snapshot/event/external-monitor response guard: " + $marker)
  }
}
if ($dataReliabilityClientSource.Contains("timeoutMs: 120000")) {
  throw "Data Reliability symbol-check client timeout must stay bounded near the backend row-level timeout"
}
if (-not $agentRuntimeSource.Contains("useOperatorContext") -or
    -not $agentRuntimeSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-write-role"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-write-disabled-reason"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-save-llm-profile"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-save-apply-all"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-validate-llm-profile"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-test-llm-profile"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-save-routing"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-apply-default-all"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-market-route-summary"') -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-market-source-summary"') -or
    -not $agentRuntimeSource.Contains("RUNTIME_LOAD_RETRY_DELAYS_MS") -or
    -not $agentRuntimeSource.Contains('data-testid="agent-runtime-load-retry"') -or
    -not $agentRuntimeSource.Contains("function guardRuntimeWrite") -or
    -not $agentRuntimeSource.Contains("if (!guardRuntimeWrite") -or
    -not $agentRuntimeSource.Contains("disabled={runtimeActionDisabled}") -or
    -not $agentRuntimeSource.Contains("disabled={!canManageRuntime}")) {
  throw "AgentRuntimeSection is missing visible role-aware admin gating for runtime writes"
}
if (-not $agentRuntimeSource.Contains("ServerBaseUrlSecurity") -or
    -not $agentRuntimeSource.Contains('testId="agent-runtime-llm-base-url-security"') -or
    -not $agentRuntimeSource.Contains("security.status") -or
    -not $agentRuntimeSource.Contains("allowedHosts")) {
  throw "AgentRuntimeSection is missing server base_url security evidence"
}
if ($agentRuntimeSource.Contains('<Card title="行情数据 API">') -or
    $agentRuntimeSource.Contains('data-testid="agent-runtime-save-market-profile"') -or
    $agentRuntimeSource.Contains('data-testid="agent-runtime-test-market-profile"')) {
  throw "AgentRuntimeSection should keep market data configuration consolidated in Settings data-source controls"
}
if (-not $settingsSource.Contains("Promise.allSettled") -or
    $settingsSource.Contains("const [list, configs] = await Promise.all([") -or
    -not $settingsSource.Contains('data-testid="settings-adapter-refresh-all"') -or
    -not $settingsSource.Contains('data-testid="settings-adapter-load-error"') -or
    -not $settingsSource.Contains('data-testid="settings-adapter-list"') -or
    -not $strictAuthBrowserSource.Contains("runSettingsAdapterPartialLoadScenario") -or
    -not $strictAuthBrowserSource.Contains("settings adapter config fixture unavailable") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Settings adapter partial-load")) {
  throw "SettingsPage adapter refresh is missing partial-load error preservation guards"
}
if (-not $settingsSource.Contains("useOperatorContext") -or
    -not $settingsSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $settingsSource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $settingsSource.Contains('data-testid="settings-data-source-config-role"') -or
    -not $settingsSource.Contains('data-testid="settings-data-source-config-disabled-reason"') -or
    -not $settingsSource.Contains('data-testid="settings-data-source-check-role"') -or
    -not $settingsSource.Contains('data-testid="settings-data-source-check-disabled-reason"') -or
    -not $settingsSource.Contains('data-testid="settings-data-source-token-input"') -or
    -not $settingsSource.Contains('data-testid="settings-data-source-save"') -or
    -not $settingsSource.Contains('settings-data-source-test-') -or
    -not $settingsSource.Contains('settings-data-source-toggle-') -or
    -not $settingsSource.Contains('settings-adapter-config-toggle-') -or
    -not $settingsSource.Contains('settings-adapter-check-') -or
    -not $settingsSource.Contains('settings-adapter-enabled-') -or
    -not $settingsSource.Contains('settings-adapter-save-config-') -or
    -not $settingsSource.Contains("function guardSettingsConfigWrite") -or
    -not $settingsSource.Contains("function guardSettingsActiveCheck") -or
    -not $settingsSource.Contains("if (!guardSettingsConfigWrite") -or
    -not $settingsSource.Contains("if (!guardSettingsActiveCheck") -or
    -not $settingsSource.Contains("disabled={dataSourceSaveDisabled}") -or
    -not $settingsSource.Contains("disabled={adapterRefreshDisabled}") -or
    -not $settingsSource.Contains("disabled={!canManageSettingsConfig}") -or
    -not $settingsSource.Contains("disabled={checkingAdapter === adapter.adapterId || !adapter.installed || !adapter.enabled || !canRunSettingsChecks}")) {
  throw "SettingsPage data-source and adapter write/check actions must stay behind visible role-aware guards"
}
if (-not $technicalKlineSource.Contains("useOperatorContext") -or
    -not $technicalKlineSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $technicalKlineSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-governance-role"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-governance-disabled-reason"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-case-disabled-reason"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-save-governance"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-rollback-governance"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-record-current-case"') -or
    -not $technicalKlineSource.Contains('data-testid="technical-kline-simulation-boundary"') -or
    -not $technicalKlineSource.Contains("simulation_only=true / is_real_trade=false / evidence_usage=technical_kline_review_only / strong_conclusion_allowed=false / SIM_*") -or
    -not $technicalKlineSource.Contains("function guardGovernanceWrite") -or
    -not $technicalKlineSource.Contains("if (!canRecordCase)") -or
    -not $technicalKlineSource.Contains("disabled={governanceLoading || !canManageGovernance}") -or
    -not $technicalKlineSource.Contains("disabled={caseRecording || !canRecordCase}")) {
  throw "TechnicalKlinePage is missing visible role-aware governance/case write gating"
}
if (-not $technicalKlineClientSource.Contains("caseLibraryCaseId") -or
    -not $technicalKlineSource.Contains("saved.caseLibraryCaseId") -or
    -not $technicalKlineSource.Contains("analysis_status: String(currentRun.technicalKline?.status") -or
    -not $technicalKlineSource.Contains("technical_bias: String(currentRun.technicalKline?.technicalBias")) {
  throw "TechnicalKline case sedimentation is missing Case Library linkage evidence"
}
if (-not $quantCoreSource.Contains("function buildQuantCoreGovernance") -or
    -not $quantCoreSource.Contains("canonical quant_core.coreInterpretation") -or
    -not $quantCoreSource.Contains("function quantEvidenceStrength") -or
    -not $quantCoreSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW'") -or
    $quantCoreSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW' | 'SUPPORTING_ONLY'") -or
    -not $quantCoreSource.Contains("if (normalized === 'LOW' || normalized === 'MEDIUM') return normalized") -or
    -not $quantCoreSource.Contains("['RESEARCH_GRADE', 'PRIMARY_EVIDENCE_READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $quantCoreSource.Contains("['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $quantCoreSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $quantCoreSource.Contains("if (normalized === 'SUPPORTING_ONLY' || normalized === 'LOW' || normalized === 'MEDIUM') return normalized") -or
    $quantCoreSource.Contains("evidenceStrength = 'SUPPORTING_ONLY'") -or
    -not ($quantCoreSource -match "if \(!interpretation\)\s*\{\s*evidenceStrength = 'LOW'") -or
    -not $quantCoreSource.Contains("const weakInterpretationStatus =") -or
    -not $quantCoreSource.Contains("const reviewGateBlocked = boundaryBroken") -or
    -not $quantCoreSource.Contains("|| weakInterpretationStatus") -or
    -not $quantCoreSource.Contains("|| warnings.length > 0") -or
    -not $quantCoreSource.Contains("|| missingData.length > 0") -or
    $quantCoreSource.Contains("interpretationStatus === 'PASS' || interpretationStatus === 'WARN'") -or
    $quantCoreSource.Contains("evidenceStrength = 'STRONG'") -or
    $quantCoreSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $quantCoreSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $quantCoreSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $quantCoreSource.Contains("currentRun?.runId !== linkedRunId") -or
    -not $quantCoreSource.Contains('data-testid="quant-core-page-loading"') -or
    -not $quantCoreSource.Contains("arrayText(core?.missingData)") -or
    -not $quantCoreSource.Contains("dashboardSummary?.tradeBoundary?.simulationOnly") -or
    -not $quantCoreSource.Contains("const boundaryBroken = !simulationOnly || isRealTrade") -or
    -not $quantCoreSource.Contains("if (boundaryBroken)") -or
    -not $quantCoreSource.Contains("QuantCore simulation-only boundary violated") -or
    -not $quantCoreSource.Contains('data-testid="quant-core-governance"') -or
    -not $quantCoreSource.Contains('data-testid="quant-core-governance-id"') -or
    -not $quantCoreSource.Contains('data-testid="quant-core-evidence-strength"') -or
    -not $quantCoreSource.Contains('data-testid="quant-core-blocker"') -or
    -not $quantCoreSource.Contains('data-testid="quant-core-next-action"') -or
    -not $quantCoreSource.Contains('data-testid="quant-core-simulation-boundary"') -or
    -not $quantCoreSource.Contains("simulation_only={String(quantGovernance.simulationOnly)} / is_real_trade={String(quantGovernance.isRealTrade)} / evidence_usage={quantGovernance.evidenceUsage} / strong_conclusion_allowed={String(quantGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("assertQuantCoreVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser QuantCore visible review boundary")) {
  throw "QuantCorePage is missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $quantCoreSource.Contains("TechnicalKlineCaseGovernanceCard") -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-case-governance"') -or
    -not $technicalKlineCaseGovernanceSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-card-case-role"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-card-case-disabled-reason"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-case-governance-simulation-boundary"') -or
    -not $technicalKlineCaseGovernanceSource.Contains("simulation_only=true / is_real_trade=false / evidence_usage=technical_kline_review_only / strong_conclusion_allowed=false / SIM_*") -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-case-impact"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-current-config-impact"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-representative-case-set"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-parameter-version-review"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-parameter-version-delta"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-long-window-regression"') -or
    -not $technicalKlineCaseGovernanceSource.Contains("caseImpact") -or
    -not $technicalKlineCaseGovernanceSource.Contains("representativeCaseSet") -or
    -not $technicalKlineCaseGovernanceSource.Contains("parameterVersionReview") -or
    -not $technicalKlineCaseGovernanceSource.Contains("longWindowRegression") -or
    -not $technicalKlineClientSource.Contains("TechnicalKlineCaseImpact") -or
    -not $technicalKlineClientSource.Contains("representativeCaseSet") -or
    -not $technicalKlineClientSource.Contains("parameterVersionReview") -or
    -not $technicalKlineClientSource.Contains("longWindowRegression") -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-case-classification"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-record-case"') -or
    -not $technicalKlineCaseGovernanceSource.Contains('data-testid="technical-kline-case-message"') -or
    -not $technicalKlineCaseGovernanceSource.Contains("if (!canRecordCase)") -or
    -not $technicalKlineCaseGovernanceSource.Contains("disabled={recording || loading || !governance || !canRecordCase}") -or
    -not $technicalKlineCaseGovernanceSource.Contains("recordTechnicalKlineCase") -or
    -not $technicalKlineCaseGovernanceSource.Contains("caseLibraryCaseId") -or
    -not $strictAuthBrowserSource.Contains("runTechnicalKlineCaseGovernanceScenario") -or
    -not $strictAuthBrowserSource.Contains("assertTechnicalKlineVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("Technical Kline visible boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("technical_kline_representative_case_set_v1") -or
    -not $strictAuthBrowserSource.Contains("technical_kline_long_window_regression_v1") -or
    -not $strictAuthBrowserSource.Contains("review_long_window_parameter_regression") -or
    -not $strictAuthBrowserSource.Contains("READY_FOR_REVIEW") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Technical Kline visible review boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Technical Kline Case Library sedimentation")) {
  throw "QuantCore is missing active Technical Kline Case Library sedimentation linkage or role gating"
}
if (-not $guardrailHubSource.Contains("function buildGuardrailGovernance") -or
    -not $guardrailHubSource.Contains("guardrail.synthesizedFromLegacy") -or
    -not $guardrailHubSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW'") -or
    $guardrailHubSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW' | 'SUPPORTING_ONLY'") -or
    -not $guardrailHubSource.Contains("let evidenceStrength: GuardrailGovernance['evidenceStrength'] = 'LOW'") -or
    $guardrailHubSource.Contains("evidenceStrength = 'SUPPORTING_ONLY'") -or
    -not $guardrailHubSource.Contains("status === 'PASS' && dvgReliability === 'HIGH' && dvgOutputLevel === 'FULL' && executionReachability === 'REACHABLE' && warnings.length === 0 && !riskHit") -or
    $guardrailHubSource.Contains("status === 'PASS' || status === 'WARN' || status === 'REVIEW_ONLY'") -or
    $guardrailHubSource.Contains("evidenceStrength = 'STRONG'") -or
    $guardrailHubSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $guardrailHubSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $guardrailHubSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $guardrailHubSource.Contains("currentRun?.runId !== linkedRunId") -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-page-loading"') -or
    -not $guardrailHubSource.Contains("dashboardSummary?.tradeBoundary?.simulationOnly") -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-governance"') -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-governance-id"') -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-evidence-strength"') -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-blocker"') -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-next-action"') -or
    -not $guardrailHubSource.Contains('data-testid="guardrail-hub-simulation-boundary"') -or
    -not $guardrailHubSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $guardrailHubSource.Contains("strongConclusionAllowed: false") -or
    -not $guardrailHubSource.Contains("simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*")) {
  throw "GuardrailHubPage is missing visible canonical/legacy ID/evidence/blocker/next-action simulation-boundary guardrails"
}
$technicalKlineClientBoundaryMarkers = @(
  "assertTechnicalKlineAnalysis",
  "assertTechnicalSignalBacktest",
  "assertTechnicalKlinePrompt",
  "assertTechnicalKlineGovernance",
  "assertTechnicalKlineCaseRecord",
  "assertTechnicalKlineCaseImpact",
  "assertTechnicalKlineRepresentativeCaseSet",
  "assertTechnicalKlineParameterVersionReview",
  "assertTechnicalKlineLongWindowRegression",
  "assertReviewOnlyBoundary",
  "assertNoTradePolicy",
  "REVIEW_ONLY_NO_TRADE_ACTION",
  "NO_DIRECT_TRADE_ACTION",
  'request<unknown>(`/technical-kline/analysis?${params.toString()}`',
  'request<unknown>(`/technical-kline/signal-backtest?${params.toString()}`',
  "request<unknown>('/technical-kline/prompt')",
  'request<unknown>(`/technical-kline/governance${query ?',
  "request<unknown>('/technical-kline/governance'",
  "request<unknown>('/technical-kline/governance/rollback'",
  "request<unknown>('/technical-kline/cases'",
  "}).then(assertTechnicalKlineAnalysis)",
  "}).then(assertTechnicalSignalBacktest)",
  "}).then(assertTechnicalKlineGovernance)",
  "}).then(assertTechnicalKlineCaseRecord)"
)
foreach ($marker in $technicalKlineClientBoundaryMarkers) {
  if (-not $technicalKlineClientSource.Contains($marker)) {
    throw ("Technical Kline API client is missing governance/no-trade response guard: " + $marker)
  }
}
if (-not $backtestSource.Contains('data-testid="backtest-research-grade-score"') -or
    -not $backtestSource.Contains('data-testid="backtest-validation-protocol"') -or
    -not $backtestSource.Contains('data-testid="backtest-validation-detail"') -or
    -not $backtestSource.Contains('data-testid="backtest-validation-out-of-sample"') -or
    -not $backtestSource.Contains('data-testid="backtest-validation-benchmark"') -or
    -not $backtestSource.Contains('data-testid="backtest-validation-package-hashes"') -or
    -not $backtestSource.Contains("validationProtocol.outOfSample") -or
    -not $backtestSource.Contains("validationProtocol.requiredForResearchGrade") -or
    -not $backtestSource.Contains("meta.researchGradeScore.components") -or
    -not $backtestSource.Contains("meta.validationProtocol.packageHashes?.dataPackageHash") -or
    -not $backtestSource.Contains("meta.evidenceStrength?.researchUsage") -or
    -not $strictAuthBrowserSource.Contains("backtest-validation-detail")) {
  throw "BacktestPage is missing research-grade score display linkage"
}
$backtestClientBoundaryMarkers = @(
  "assertSnakeSimulationBoundary",
  "assertCamelSimulationBoundary",
  "assertBacktestReportBoundary",
  "function assertBacktestEvidenceBoundary",
  "function isStrongBacktestEvidenceValue",
  "normalized === 'RESEARCH_GRADE'",
  "normalized === 'PRIMARY_EVIDENCE_READY'",
  "normalized.includes('STRONG')",
  "normalized.includes('PRIMARY')",
  "report.evidence_strength",
  "report.research_grade_score",
  "evidence.research_usage",
  "researchGrade.research_usage",
  "evidence.weak_sample",
  "researchGrade.supporting_only",
  "evidence.can_support_research_verdict",
  "assertBacktestEvidenceBoundary(sampleEvidence",
  "report provenance",
  "supporting-only evidence must not become a strong conclusion",
  "evidence must not become primary_evidence",
  "assertBacktestParameterScanResponse",
  "assertBacktestParameterScanJob",
  "assertBacktestParameterScanJobHandoff",
  "assertBacktestExperimentPackage",
  "assertSignalOpsExperimentResponse",
  "assertSignalOpsRandomValidationJob",
  "assertBacktestDeleteResult",
  "assertBacktestSummary",
  'request<unknown>(`${BACKTEST_API_BASE}/runs`',
  'request<unknown>(`${BACKTEST_API_BASE}/parameter-scan`',
  'request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs`',
  'request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}`',
  'request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}/cancel`',
  'request<unknown>(`${BACKTEST_API_BASE}/parameter-scan/jobs/${jobId}/handoff`',
  "request<unknown>(path, { signal: options.signal })",
  'request<unknown>(`${BACKTEST_API_BASE}/signalops-sample`',
  'request<unknown>(`${BACKTEST_API_BASE}/signalops-experiment`',
  'request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs`',
  'request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs/${jobId}`',
  'request<unknown>(`${BACKTEST_API_BASE}/signalops-random-validation/jobs/${jobId}/cancel`',
  'request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}`',
  'request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/trades`',
  'request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/signals`',
  'request<unknown>(`${BACKTEST_API_BASE}/runs/${runId}/experiment-package`',
  'request<unknown>(`${BACKTEST_API_BASE}/summary`',
  "}).then(assertBacktestParameterScanResponse)",
  "}).then(assertBacktestParameterScanJob)",
  "}).then(assertBacktestParameterScanJobHandoff)",
  "}).then(assertBacktestExperimentPackage)",
  "}).then(assertSignalOpsExperimentResponse)",
  "}).then(assertSignalOpsRandomValidationJob)",
  "method: 'DELETE' }).then(assertBacktestDeleteResult)",
  "}).then(assertBacktestSummary)",
  "ensureArray(items, 'backtest parameter scan history').map(assertBacktestParameterScanHistoryItem)",
  "ensureArray(items, 'backtest signals').map(assertBacktestSignalItem)"
)
foreach ($marker in $backtestClientBoundaryMarkers) {
  if (-not $backtestClientSource.Contains($marker)) {
    throw ("Backtest API client is missing parameter-scan simulation boundary guard: " + $marker)
  }
}
$backtestSimBuyLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x4E70, 0x5165))
$backtestSimSellLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x5356, 0x51FA))
$backtestSimCloseLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x5E73, 0x4ED3))
$backtestSimHoldLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x6301, 0x6709))
$backtestSimTBuyLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x505A)) + " T " + [string]::Concat([char[]](0x4E70, 0x56DE))
$backtestSimTSellLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x505A)) + " T " + [string]::Concat([char[]](0x5356, 0x51FA))
$backtestSimShortLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x505A, 0x7A7A))
$backtestSimCoverLabel = [string]::Concat([char[]](0x6A21, 0x62DF, 0x56DE, 0x8865))
foreach ($marker in @(
  "SIM_BUY: '$backtestSimBuyLabel'",
  "SIM_SELL: '$backtestSimSellLabel'",
  "SIM_CLOSE: '$backtestSimCloseLabel'",
  "SIM_HOLD: '$backtestSimHoldLabel'",
  "SIM_T_BUY: '$backtestSimTBuyLabel'",
  "SIM_T_SELL: '$backtestSimTSellLabel'",
  "SIM_SHORT: '$backtestSimShortLabel'",
  "SIM_COVER: '$backtestSimCoverLabel'"
)) {
  if (-not $backtestSource.Contains($marker)) {
    throw ("Backtest SignalOps action labels must keep explicit simulation wording: " + $marker)
  }
}
if (-not $backtestSource.Contains("function buildBacktestRunGovernance") -or
    -not $backtestSource.Contains("reportMeta?.evidenceStrength") -or
    -not $backtestSource.Contains("reportMeta?.researchGradeScore") -or
    -not $backtestSource.Contains("reportMeta?.evidence_strength") -or
    -not $backtestSource.Contains("reportMeta?.research_grade_score") -or
    -not $backtestSource.Contains("evidence.research_usage") -or
    -not $backtestSource.Contains("researchGrade.research_usage") -or
    -not $backtestSource.Contains("evidence.weak_sample") -or
    -not $backtestSource.Contains("researchGrade.supporting_only") -or
    -not $backtestSource.Contains("evidence.can_support_research_verdict") -or
    -not $backtestSource.Contains("selectedRun?.parameters") -or
    -not $backtestSource.Contains("function normalizeEvidenceLevel") -or
    -not $backtestSource.Contains("['STRONG', 'HIGH', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $backtestSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    -not $backtestSource.Contains("'RESEARCH_GRADE'") -or
    -not $backtestSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    $backtestSource.Contains("researchBand === 'RESEARCH_GRADE'") -or
    -not ($backtestSource -match "else if \(supportingOnly\)\s*\{\s*evidenceStrength = 'LOW'") -or
    ($backtestSource -match "else if \(supportingOnly\)\s*\{\s*evidenceStrength = 'SUPPORTING_ONLY'") -or
    -not $backtestSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW'") -or
    $backtestSource.Contains("evidenceStrength: 'MEDIUM' | 'LOW' | 'SUPPORTING_ONLY'") -or
    $backtestSource.Contains("evidenceStrength = 'STRONG'") -or
    $backtestSource.Contains("evidenceStrength: 'STRONG'") -or
    -not $backtestSource.Contains("Backtest simulation-only boundary violated") -or
    -not $backtestSource.Contains("supporting_only evidence") -or
    -not $backtestSource.Contains("evidenceUsage: 'supporting_only'") -or
    -not $backtestSource.Contains("strongConclusionAllowed: false") -or
    -not $backtestSource.Contains('data-testid="backtest-run-governance"') -or
    -not $backtestSource.Contains('data-testid="backtest-run-governance-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-run-evidence-strength"') -or
    -not $backtestSource.Contains('data-testid="backtest-run-blocker"') -or
    -not $backtestSource.Contains('data-testid="backtest-run-next-action"') -or
    -not $backtestSource.Contains('data-testid="backtest-run-simulation-boundary"') -or
    -not $backtestSource.Contains("simulation_only={String(backtestGovernance.simulationOnly)} / is_real_trade={String(backtestGovernance.isRealTrade)} / evidence_usage={backtestGovernance.evidenceUsage} / strong_conclusion_allowed={String(backtestGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("assertBacktestRunVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest sample visible run boundary")) {
  throw "BacktestPage is missing visible run ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $backtestSource.Contains("const buildBacktestParameterScanGovernance") -or
    -not $backtestSource.Contains("const buildBacktestParameterScanJobGovernance") -or
    -not ($backtestSource -match "type BacktestParameterScanGovernance = Omit<BacktestGovernance, 'evidenceStrength' \| 'evidenceUsage'> & \{\s*evidenceStrength: 'LOW'\s*evidenceUsage: 'review_gate_only'\s*strongConclusionAllowed: false\s*\}") -or
    $backtestSource.Contains("evidenceStrength: 'LOW' | 'SUPPORTING_ONLY'") -or
    $backtestSource.Contains("evidenceStrength: completed && hasBestRun && !boundaryBroken ? 'SUPPORTING_ONLY' : 'LOW'") -or
    -not $backtestSource.Contains("Parameter scan retained as review-gated evidence") -or
    -not $backtestSource.Contains("Backtest parameter scan simulation-only boundary violated") -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance-evidence-strength"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance-blocker"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance-next-action"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-governance-simulation-boundary"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance-evidence-strength"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance-blocker"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance-next-action"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-governance-simulation-boundary"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-governance"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-governance-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-evidence-strength"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-blocker"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-next-action"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-simulation-boundary"') -or
    -not $backtestSource.Contains("evidence_usage={scanNoticeGovernance.evidenceUsage}") -or
    -not $backtestSource.Contains("strong_conclusion_allowed={String(scanNoticeGovernance.strongConclusionAllowed)}") -or
    -not $backtestSource.Contains("evidence_usage={parameterScanJobGovernance.evidenceUsage}") -or
    -not $backtestSource.Contains("strong_conclusion_allowed={String(parameterScanJobGovernance.strongConclusionAllowed)}") -or
    -not $backtestSource.Contains("evidence_usage={scanGovernance.evidenceUsage}") -or
    -not $backtestSource.Contains("strong_conclusion_allowed={String(scanGovernance.strongConclusionAllowed)}")) {
  throw "BacktestPage is missing parameter-scan ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $backtestSource.Contains('data-testid="backtest-page"') -or
    -not $backtestSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $backtestSource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $backtestSource.Contains('data-testid="backtest-research-write-role"') -or
    -not $backtestSource.Contains('data-testid="backtest-research-write-disabled-reason"') -or
    -not $backtestSource.Contains('data-testid="backtest-job-control-role"') -or
    -not $backtestSource.Contains('data-testid="backtest-job-control-disabled-reason"') -or
    -not $backtestSource.Contains('data-testid="backtest-artifact-handoff-role"') -or
    -not $backtestSource.Contains('data-testid="backtest-artifact-handoff-disabled-reason"') -or
    -not $backtestSource.Contains('backtestWriteDisabledReason') -or
    -not $backtestSource.Contains('backtestJobControlDisabledReason') -or
    -not $backtestSource.Contains('backtestHandoffDisabledReason') -or
    -not $backtestSource.Contains('if (!canWriteBacktestResearch)') -or
    -not $backtestSource.Contains('if (!canControlBacktestJobs)') -or
    -not $backtestSource.Contains('if (!canHandoffBacktestArtifacts)') -or
    -not $backtestSource.Contains('data-testid="backtest-run-submit"') -or
    -not $backtestSource.Contains('disabled={submitting || !canWriteBacktestResearch') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-submit"') -or
    -not $backtestSource.Contains('disabled={scanSubmitting || !canWriteBacktestResearch') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-submit"') -or
    -not $backtestSource.Contains('disabled={parameterScanJobSubmitting || isParameterScanJobActive(parameterScanJob) || !canWriteBacktestResearch') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-sample-submit"') -or
    -not $backtestSource.Contains('disabled={sampleSubmitting || !canWriteBacktestResearch') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-status"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-cancel"') -or
    -not $backtestSource.Contains('disabled={!canControlBacktestJobs}') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-handoff"') -or
    -not $backtestSource.Contains('disabled={parameterScanJobHandoffSubmitting || !canHandoffBacktestArtifacts') -or
    -not $backtestSource.Contains('canStart={canWriteBacktestResearch}') -or
    -not $backtestSource.Contains('canCancel={canControlBacktestJobs}') -or
    -not $backtestSource.Contains("function buildSignalOpsRandomValidationGovernance") -or
    -not $backtestSource.Contains("SignalOps random validation simulation-only boundary violated") -or
    -not $backtestSource.Contains("dataQuality.completeTradeLoop === true") -or
    -not $backtestSource.Contains("job.sampleWindows.length > 0") -or
    -not $backtestSource.Contains("evidenceStrength: 'LOW'") -or
    $backtestSource.Contains("evidenceStrength: boundaryBroken || !job || status !== 'COMPLETED' || !hasSamples || !trusted || !completeTradeLoop || rejected ? 'LOW' : 'SUPPORTING_ONLY'") -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-governance"') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-governance-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-evidence-strength"') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-blocker"') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-next-action"') -or
    -not $backtestSource.Contains('data-testid="backtest-signalops-random-simulation-boundary"') -or
    -not $backtestSource.Contains("simulation_only={String(randomGovernance.simulationOnly)} / is_real_trade={String(randomGovernance.isRealTrade)} / evidence_usage={randomGovernance.evidenceUsage} / strong_conclusion_allowed={String(randomGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-handoff-status"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-handoff-custody"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-job-handoff-refresh"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-notice"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history"') -or
    -not $backtestSource.Contains('data-testid="backtest-parameter-scan-history-open-best"') -or
    -not $backtestSource.Contains("buildParameterScanWindows") -or
    -not $backtestSource.Contains("windows: scanWindows") -or
    -not $backtestSource.Contains("parameterScanTrialCount") -or
    -not $backtestSource.Contains("Windows:") -or
    -not $backtestSource.Contains("isParameterScanJobActive") -or
    -not $backtestSource.Contains("'RECOVERING'") -or
    -not $backtestSource.Contains("parameterScanJob.queueMode") -or
    -not $backtestSource.Contains("parameterScanJob.idempotencyKey") -or
    -not $backtestSource.Contains("parameterScanJob.attemptCount") -or
    -not $backtestSource.Contains("parameterScanJob.leaseStatus") -or
    -not $backtestSource.Contains("parameterScanJob.leaseOwner") -or
    -not $backtestSource.Contains("parameterScanJob.leaseId") -or
    -not $backtestSource.Contains("parameterScanJob?.handoffStatus") -or
    -not $backtestSource.Contains("handleRefreshParameterScanJobHandoffStatus") -or
    -not $backtestSource.Contains("parameterScanJobHandoff.bundleChecksum") -or
    -not $backtestSource.Contains("handoffBacktestParameterScanJob") -or
    -not $backtestSource.Contains("latestParameterScanJobAttempt") -or
    -not $backtestSource.Contains("durable={String(parameterScanJob.durable === true)}") -or
    -not $backtestSource.Contains("getBacktestParameterScanJob") -or
    -not $typesSource.Contains("BacktestParameterScanJobAttempt") -or
    -not $typesSource.Contains("idempotencyKey?: string") -or
    -not $typesSource.Contains("attemptCount?: number") -or
    -not $typesSource.Contains("leaseStatus?: string") -or
    -not $typesSource.Contains("leaseOwner?: string") -or
    -not $typesSource.Contains("leaseId?: string") -or
    -not $typesSource.Contains("handoffStatus?: Record<string, any>") -or
    -not $typesSource.Contains("BacktestParameterScanJobHandoff") -or
    -not $typesSource.Contains("bundleChecksum?: string") -or
    -not $backtestSource.Contains('data-testid="backtest-experiment-package-download"') -or
    -not $backtestSource.Contains('data-testid="backtest-create-verdict-inputs"') -or
    -not $backtestSource.Contains('data-testid="backtest-verdict-inputs-notice"') -or
    -not $backtestSource.Contains('data-testid="backtest-verdict-inputs-boundary"') -or
    -not $backtestSource.Contains("evidence_usage={verdictNotice.evidenceUsage}") -or
    -not $backtestSource.Contains("supporting_only={String(verdictNotice.supportingOnly)}") -or
    -not $backtestSource.Contains("simulation_only={String(verdictNotice.simulationOnly)}") -or
    -not $backtestSource.Contains("is_real_trade={String(verdictNotice.isRealTrade)}") -or
    -not $backtestSource.Contains("strong_conclusion_allowed={String(verdictNotice.strongConclusionAllowed)} / SIM_*") -or
    -not $backtestClientSource.Contains("createBacktestParameterScan") -or
    -not $backtestClientSource.Contains("createBacktestParameterScanJob") -or
    -not $backtestClientSource.Contains("getBacktestParameterScanJob") -or
    -not $backtestClientSource.Contains("cancelBacktestParameterScanJob") -or
    -not $backtestClientSource.Contains("handoffBacktestParameterScanJob") -or
    -not $backtestClientSource.Contains("getBacktestExperimentPackage") -or
    -not $backtestClientSource.Contains("listBacktestParameterScans") -or
    -not $backtestClientSource.Contains("/experiment-package") -or
    -not $backtestClientSource.Contains("/parameter-scans") -or
    -not $backtestClientSource.Contains("/parameter-scan/jobs") -or
    -not $backtestClientSource.Contains("/parameter-scan/jobs/`${jobId}/handoff") -or
    -not $researchClientSource.Contains("createResearchBacktestVerdictInputs") -or
    -not $researchClientSource.Contains("/research/backtest/runs/`${runId}/verdict-inputs") -or
    -not $typesSource.Contains("strong_conclusion_allowed: boolean") -or
    -not $backtestSource.Contains('disabled={verdictLinking || !canWriteBacktestResearch}') -or
    -not $researchLoopsSource.Contains("function researchBacktestPath") -or
    -not $researchLoopsSource.Contains('data-testid="research-open-linked-backtest"') -or
    -not $backtestClientSource.Contains('`${BACKTEST_API_BASE}/parameter-scan`') -or
    -not $backtestSource.Contains('data-testid="backtest-selected-run-id"') -or
    -not $backtestSource.Contains('data-testid="backtest-report-panel"') -or
    -not $backtestSource.Contains("form.signal_source === 'MOCK' || form.signal_source === 'NONE'") -or
    -not $strictAuthBrowserSource.Contains("runBacktestSampleScenario") -or
    -not $strictAuthBrowserSource.Contains("assertBacktestExperimentPackage") -or
    -not $strictAuthBrowserSource.Contains("runBacktestParameterScanScenario") -or
    -not $strictAuthBrowserSource.Contains("assertBacktestParameterScanBoundary") -or
    -not $strictAuthBrowserSource.Contains("backtest-verdict-inputs-boundary") -or
    -not $strictAuthBrowserSource.Contains("Research Backtest visible verdict-inputs boundary") -or
    -not $strictAuthBrowserSource.Contains("summary.totalTrials") -or
    -not $strictAuthBrowserSource.Contains("windowCount") -or
    -not $strictAuthBrowserSource.Contains("Evidence: LOW") -or
    $strictAuthBrowserSource.Contains("Evidence: SUPPORTING_ONLY") -or
    -not $strictAuthBrowserSource.Contains("/api/research/backtest/parameter-scan/jobs") -or
    -not $strictAuthBrowserSource.Contains("LOCAL_DURABLE_JSON") -or
    -not $strictAuthBrowserSource.Contains("bt-parameter-scan-") -or
    -not $strictAuthBrowserSource.Contains("backtest_parameter_scan_job_handoff_v1") -or
    -not $strictAuthBrowserSource.Contains("backtest_parameter_scan_job_handoff_manifest_v1") -or
    -not $strictAuthBrowserSource.Contains("backtest_parameter_scan_job_handoff_shipper_status_v1") -or
    -not $strictAuthBrowserSource.Contains("backtest-parameter-scan-job-handoff-custody") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest parameter-scan handoff custody") -or
    -not $strictAuthBrowserSource.Contains("deployment_owned_after_handoff") -or
    -not $strictAuthBrowserWrapperSource.Contains("BACKTEST_PARAMETER_SCAN_HANDOFF_DIR") -or
    -not $strictAuthBrowserSource.Contains("lastAttemptStatus") -or
    -not $strictAuthBrowserSource.Contains("durable=true") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest parameter-scan async job") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest parameter-scan handoff") -or
    -not $strictAuthBrowserSource.Contains("acceptDownloads: true") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest experiment package download") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest parameter-scan validation protocol") -or
    -not $strictAuthBrowserSource.Contains("if (['SUPPORTING_ONLY', 'WARN', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    -not $strictAuthBrowserSource.Contains("runResearchBacktestVerdictInputsScenario") -or
    -not $strictAuthBrowserSource.Contains("assertResearchBacktestVerdictInputsBoundary") -or
    -not $strictAuthBrowserSource.Contains("root.strong_conclusion_allowed !== false") -or
    -not $strictAuthBrowserSource.Contains("seedResearchBacktestReportedQualityAudit") -or
    -not $strictAuthBrowserSource.Contains("STRICT_AUTH_BROWSER_REPORTED_QUALITY_AUDIT") -or
    -not $strictAuthBrowserSource.Contains("quality: 'SUPPORTING_ONLY'") -or
    -not $strictAuthBrowserSource.Contains("reportedQuality: 'SUPPORTING_ONLY'") -or
    -not $strictAuthBrowserSource.Contains("Backtest verdict inputs did not retain reportedQuality audit grade") -or
    -not $strictAuthBrowserSource.Contains("Backtest verdict inputs did not retain SUPPORTING_ONLY reportedQuality audit grade") -or
    -not $strictAuthBrowserSource.Contains("audit.reviewGateQuality !== 'LOW'") -or
    -not $strictAuthBrowserSource.Contains("Research Lab verdict evidence did not render reportedQuality review-gate audit") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research Lab verdict reportedQuality audit") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Backtest sample run") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research Backtest verdict inputs")) {
  throw "BacktestPage is missing browser-visible sample-run hooks or strict-auth Backtest sample coverage"
}
if (-not $backtestSource.Contains("const mountedRef = useRef(true)") -or
    -not $backtestSource.Contains("detailRequestRef.current += 1") -or
    -not $backtestSource.Contains("if (!mountedRef.current) return") -or
    -not $backtestSource.Contains("mountedRef.current && detailRequestRef.current === requestId")) {
  throw "BacktestPage is missing unmounted/stale async request guards"
}
if (-not $httpClientSource.Contains("signal: callerSignal") -or
    -not $httpClientSource.Contains("callerSignal?.addEventListener('abort'") -or
    -not $httpClientSource.Contains("callerSignal?.aborted && !timedOut") -or
    -not $backtestClientSource.Contains("type BacktestReadOptions") -or
    -not $backtestClientSource.Contains("{ signal: options.signal }") -or
    -not $backtestSource.Contains("const refreshAbortRef = useRef<AbortController | null>(null)") -or
    -not $backtestSource.Contains("const detailAbortRef = useRef<AbortController | null>(null)") -or
    -not $backtestSource.Contains("refreshAbortRef.current?.abort()") -or
    -not $backtestSource.Contains("detailAbortRef.current?.abort()") -or
    -not $backtestSource.Contains("{ signal: abortController.signal }")) {
  throw "BacktestPage and shared HTTP client are missing active abort propagation for stale requests"
}
if (-not $historySelectorSource.Contains("useOperatorContext") -or
    -not $historySelectorSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $historySelectorSource.Contains("disabled={!canDeleteAnalysisRuns}") -or
    -not $backtestSource.Contains("useOperatorContext") -or
    -not $backtestSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $backtestSource.Contains("deleteDisabledReason={deleteDisabledReason}") -or
    -not $backtestSource.Contains("disabled={deletingRunId === selectedRun.run_id || !canDeleteBacktestRuns}") -or
    -not $portfolioSource.Contains("useOperatorContext") -or
    -not $portfolioSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $portfolioSource.Contains("canWritePortfolioSnapshots") -or
    -not $portfolioSource.Contains("writeDisabledReason") -or
    -not $portfolioSource.Contains("if (!canWritePortfolioSnapshots)") -or
    -not $portfolioSource.Contains('data-testid="portfolio-write-role"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-write-disabled-reason"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-create-sample"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-create-manual"') -or
    -not $portfolioSource.Contains("disabled={loading || !canWritePortfolioSnapshots}") -or
    -not $portfolioSource.Contains("disabled={loading || !manualForm.symbol.trim() || !canWritePortfolioSnapshots}") -or
    -not $portfolioSource.Contains("disabled={loading || !importFile || !canWritePortfolioSnapshots}") -or
    -not $portfolioSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $portfolioSource.Contains("disabled={loading || !canDeletePortfolioSnapshots}") -or
    -not $portfolioSource.Contains('data-testid="portfolio-broker-template"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-error-detail"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-observed-headers"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-row-preview"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-template-hint"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-repair-suggestions"') -or
    -not $portfolioSource.Contains("formatImportPreviewCells") -or
    -not $portfolioSource.Contains("extractPortfolioImportErrorDetail") -or
    -not $httpClientSource.Contains("class ApiError") -or
    -not $portfolioSource.Contains("templateWarnings.slice(0, 2)") -or
    -not $caseLibrarySource.Contains("useOperatorContext") -or
    -not $caseLibrarySource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $caseLibrarySource.Contains("disabled={saving || !canDeleteCaseLibraryItems}") -or
    -not $knowledgeVersionsSource.Contains("useOperatorContext") -or
    -not $knowledgeVersionsSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $knowledgeVersionsSource.Contains("disabled={saving || !canRollbackKnowledge}")) {
  throw "High-risk delete/rollback pages are missing role-aware admin gating"
}
if (-not $portfolioSource.Contains("function portfolioEvidenceStrengthLabel") -or
    -not $portfolioSource.Contains("function portfolioSnapshotBlocker") -or
    -not $portfolioSource.Contains("function portfolioSnapshotNextAction") -or
    -not $portfolioSource.Contains("function reviewGateEvidenceStrength") -or
    -not $portfolioSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW')") -or
    -not $portfolioSource.Contains("['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $portfolioSource.Contains("'RESEARCH_GRADE'") -or
    -not $portfolioSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $portfolioSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $portfolioSource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN', 'SUPPORTING_ONLY'].includes(normalized)) return normalized") -or
    $portfolioSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = '')") -or
    -not $portfolioSource.Contains("const apiStrength = reviewGateEvidenceStrength(snapshot.evidenceStrength)") -or
    -not $portfolioSource.Contains("positionCount <= 0") -or
    -not $portfolioSource.Contains("maxSinglePositionRatio > 0.4") -or
    -not $portfolioSource.Contains("portfolio-snapshot-governance-") -or
    -not $portfolioSource.Contains("portfolio-snapshot-governance-id-") -or
    -not $portfolioSource.Contains("portfolio-snapshot-evidence-strength-") -or
    -not $portfolioSource.Contains("portfolio-snapshot-blocker-") -or
    -not $portfolioSource.Contains("portfolio-snapshot-next-action-") -or
    -not $portfolioSource.Contains("portfolio-snapshot-simulation-boundary-") -or
    -not $portfolioSource.Contains("simulation_only={String(item.simulationOnly)} / is_real_trade={String(item.isRealTrade)} / evidence_usage={item.evidenceUsage} / strong_conclusion_allowed={String(item.strongConclusionAllowed)} / SIM_*") -or
    -not $portfolioClientSource.Contains("assertPortfolioSnapshotBoundary") -or
    -not $portfolioClientSource.Contains("function isStrongEvidenceValue") -or
    -not $portfolioClientSource.Contains("normalized === 'RESEARCH_GRADE'") -or
    -not $portfolioClientSource.Contains("normalized === 'PRIMARY_EVIDENCE_READY'") -or
    -not $portfolioClientSource.Contains("normalized.includes('STRONG')") -or
    -not $portfolioClientSource.Contains("normalized.includes('PRIMARY')") -or
    -not $portfolioClientSource.Contains("portfolio evidence must not become a strong conclusion") -or
    -not $portfolioClientSource.Contains("evidenceUsage: 'supporting_only'") -or
    -not $strictAuthBrowserSource.Contains("assertPortfolioSnapshotVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains('portfolio-snapshot-simulation-boundary-${snapshotId}') -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Portfolio visible review boundary")) {
  throw "Portfolio snapshots are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $caseLibrarySource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $caseLibrarySource.Contains("useSearchParams") -or
    -not $caseLibrarySource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $caseLibrarySource.Contains("const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)") -or
    -not $caseLibrarySource.Contains("const runId = isLinkedRunPending ? '' : linkedRunId || currentRunId || currentRun?.runId") -or
    $caseLibrarySource.Contains("const runId = currentRunId ?? currentRun?.runId") -or
    -not $caseLibrarySource.Contains("if (isLinkedRunPending)") -or
    -not $caseLibrarySource.Contains("canWriteCaseLibraryItems") -or
    -not $caseLibrarySource.Contains("caseLibraryWriteDisabledReason") -or
    -not $caseLibrarySource.Contains('data-testid="case-library-write-role"') -or
    -not $caseLibrarySource.Contains('data-testid="case-library-write-disabled-reason"') -or
    -not $caseLibrarySource.Contains('data-testid="case-library-current-run-id"') -or
    -not $caseLibrarySource.Contains('data-testid="case-library-current-run-loading"') -or
    -not $caseLibrarySource.Contains('data-testid="case-library-create-case"') -or
    -not $caseLibrarySource.Contains("case-library-add-tag-") -or
    -not $caseLibrarySource.Contains("case-library-save-review-") -or
    -not $caseLibrarySource.Contains("case-library-approve-with-evaluation-") -or
    -not $caseLibrarySource.Contains("case-library-review-approve-") -or
    -not $caseLibrarySource.Contains("case-library-review-reject-") -or
    -not $caseLibrarySource.Contains("case-library-review-archive-") -or
    -not $caseLibrarySource.Contains("if (!canWriteCaseLibraryItems)") -or
    -not $caseLibrarySource.Contains("disabled={!runId || saving || !canWriteCaseLibraryItems || isLinkedRunPending}") -or
    -not $caseLibrarySource.Contains("disabled={saving || !canWriteCaseLibraryItems}")) {
  throw "Case Library write paths are missing role-aware researcher gating"
}
if (-not $caseLibrarySource.Contains("function caseEvidenceStrengthLabel") -or
    -not $caseLibrarySource.Contains("function caseBlockingReason") -or
    -not $caseLibrarySource.Contains("function caseNextActionLabel") -or
    -not $caseLibrarySource.Contains("function reviewGateEvidenceStrength") -or
    -not $caseLibrarySource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW')") -or
    -not $caseLibrarySource.Contains("['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $caseLibrarySource.Contains("'RESEARCH_GRADE'") -or
    -not $caseLibrarySource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $caseLibrarySource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $caseLibrarySource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN', 'SUPPORTING_ONLY'].includes(normalized)) return normalized") -or
    $caseLibrarySource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = '')") -or
    -not $caseLibrarySource.Contains("const apiStrength = reviewGateEvidenceStrength(item.evidence_strength)") -or
    $caseLibrarySource.Contains("if (reviewed && hasJudgement) return 'MEDIUM") -or
    -not $caseLibrarySource.Contains("if (reviewed && hasJudgement) return 'LOW") -or
    $caseLibrarySource.Contains("return 'SUPPORTING_ONLY") -or
    -not $caseLibrarySource.Contains("item.review_status !== 'REVIEWED'") -or
    -not $caseLibrarySource.Contains("item.data_sufficiency !== 'ADEQUATE'") -or
    -not $caseLibrarySource.Contains("item.key_lessons.length === 0") -or
    -not $caseLibrarySource.Contains("case-library-case-governance-") -or
    -not $caseLibrarySource.Contains("case-library-case-id-") -or
    -not $caseLibrarySource.Contains("case-library-case-evidence-strength-") -or
    -not $caseLibrarySource.Contains("case-library-case-blocker-") -or
    -not $caseLibrarySource.Contains("case-library-case-next-action-") -or
    -not $caseLibrarySource.Contains("case-library-case-simulation-boundary-") -or
    -not $caseLibrarySource.Contains("simulation_only={String(item.simulation_only)} / is_real_trade={String(item.is_real_trade)} / evidence_usage={item.evidence_usage} / strong_conclusion_allowed={String(item.strong_conclusion_allowed)} / SIM_*") -or
    -not $caseLibraryClientSource.Contains("assertCaseLibraryBoundary") -or
    -not $caseLibraryClientSource.Contains("case evidence must not become a strong conclusion") -or
    -not $typesSource.Contains("evidence_usage: 'supporting_only'") -or
    -not $strictAuthBrowserSource.Contains("assertCaseLibraryReviewBoundaryVisible") -or
    -not $strictAuthBrowserSource.Contains("Case Library visible review boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Case Library visible review boundary")) {
  throw "Case Library cases are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $caseLibrarySource.Contains("function buildSimulationCaseGovernance") -or
    -not $caseLibrarySource.Contains("function simulationCaseWarnings") -or
    -not $caseLibrarySource.Contains("Agent simulation case simulation-only boundary violated") -or
    -not $caseLibrarySource.Contains("Paper gate warning:") -or
    -not $caseLibrarySource.Contains("source_signal_id && item.source_paper_order_id") -or
    -not $caseLibrarySource.Contains("hasExecutableAction && !hasTradeMetrics") -or
    -not $caseLibrarySource.Contains("knowledge_candidate_status") -or
    -not $caseLibrarySource.Contains("evidenceStrength: 'LOW'") -or
    $caseLibrarySource.Contains("evidenceStrength: boundaryBroken || warnings.length > 0 || !hasIds ? 'LOW' : 'SUPPORTING_ONLY'") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-governance-") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-id-") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-evidence-strength-") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-blocker-") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-next-action-") -or
    -not $caseLibrarySource.Contains("case-library-simulation-case-simulation-boundary-") -or
    -not $caseLibrarySource.Contains("simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("case-library-simulation-case-simulation-boundary-") -or
    -not $strictAuthBrowserSource.Contains("simulation case governance")) {
  throw "Case Library Agent simulation cases are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $caseLibrarySource.Contains("function buildErrorLedgerGovernance") -or
    -not $caseLibrarySource.Contains("function errorLedgerBoundary") -or
    -not $caseLibrarySource.Contains("Error ledger simulation-only boundary violated") -or
    -not $caseLibrarySource.Contains("const evidenceStrength = apiStrength === 'MEDIUM' ? 'MEDIUM' : 'LOW'") -or
    $caseLibrarySource.Contains("fallbackStrength = boundaryBroken || status === 'OPEN' || !hasIds ? 'LOW' : 'SUPPORTING_ONLY'") -or
    $caseLibrarySource.Contains("apiStrength === 'LOW' || apiStrength === 'SUPPORTING_ONLY'") -or
    -not $caseLibrarySource.Contains("entry.attribution") -or
    -not $caseLibrarySource.Contains("entry.patch_required && !entry.patch_candidate_id") -or
    -not $caseLibrarySource.Contains("entry.repeated_count > 1") -or
    -not $caseLibrarySource.Contains("case-library-error-governance-") -or
    -not $caseLibrarySource.Contains("case-library-error-id-") -or
    -not $caseLibrarySource.Contains("case-library-error-evidence-strength-") -or
    -not $caseLibrarySource.Contains("case-library-error-blocker-") -or
    -not $caseLibrarySource.Contains("case-library-error-next-action-") -or
    -not $caseLibrarySource.Contains("case-library-error-simulation-boundary-") -or
    -not $caseLibrarySource.Contains("simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={entry.evidence_usage} / strong_conclusion_allowed={String(entry.strong_conclusion_allowed)} / SIM_*") -or
    -not $strictAuthBrowserSource.Contains("case-library-error-simulation-boundary-") -or
    -not $strictAuthBrowserSource.Contains("error ledger governance")) {
  throw "Case Library error ledger is missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $caseLibrarySource.Contains("function patchHasEvaluationEvidence") -or
    -not $caseLibrarySource.Contains("function patchEvidenceStrengthLabel") -or
    -not $caseLibrarySource.Contains("const strength = reviewGateEvidenceStrength(patch.evidence_strength)") -or
    -not $caseLibrarySource.Contains("function patchBlockingReason") -or
    -not $caseLibrarySource.Contains("function patchNextActionLabel") -or
    -not $caseLibrarySource.Contains("patch.backtest_required && !patchHasEvaluationEvidence(patch)") -or
    -not $caseLibrarySource.Contains("case-library-patch-governance-") -or
    -not $caseLibrarySource.Contains("case-library-patch-id-") -or
    -not $caseLibrarySource.Contains("case-library-patch-evidence-strength-") -or
    -not $caseLibrarySource.Contains("case-library-patch-blocker-") -or
    -not $caseLibrarySource.Contains("case-library-patch-next-action-") -or
    -not $caseLibrarySource.Contains("case-library-patch-simulation-boundary-") -or
    -not $caseLibrarySource.Contains("simulation_only={String(patch.simulation_only)} / is_real_trade={String(patch.is_real_trade)} / evidence_usage={patch.evidence_usage} / strong_conclusion_allowed={String(patch.strong_conclusion_allowed)} / SIM_*") -or
    -not $caseLibraryClientSource.Contains("assertKnowledgePatchBoundary") -or
    -not $caseLibraryClientSource.Contains("patch evidence must not become a strong conclusion") -or
    -not $caseLibraryClientSource.Contains("patch review must stay simulation-only")) {
  throw "Case Library patch governance is missing visible ID/evidence/blocker/next-action simulation-boundary guardrails"
}
if (-not $httpClientSource.Contains("body instanceof FormData") -or
    -not $httpClientSource.Contains("getOperatorHeaders()") -or
    -not $portfolioClientSource.Contains("const form = new FormData()") -or
    -not $portfolioClientSource.Contains("importError?: Record<string, unknown>") -or
    -not $portfolioClientSource.Contains("assertPortfolioSnapshotSummary") -or
    -not $portfolioClientSource.Contains("assertPortfolioSnapshot") -or
    -not $portfolioClientSource.Contains("assertHoldingImportResponse") -or
    -not $portfolioClientSource.Contains("assertHoldingImportJob") -or
    -not $portfolioClientSource.Contains("assertDeletePortfolioSnapshotResult") -or
    -not $portfolioClientSource.Contains("ensureArray(items, 'portfolio snapshot list').map(assertPortfolioSnapshotSummary)") -or
    -not $portfolioClientSource.Contains(".then(assertPortfolioSnapshot)") -or
    -not $portfolioClientSource.Contains(".then(assertHoldingImportJob)") -or
    -not $portfolioClientSource.Contains(".then(assertHoldingImportResponse)") -or
    -not $portfolioClientSource.Contains("return request<unknown>('/portfolio/imports'") -or
    $portfolioClientSource.Contains("fetch('/portfolio/imports") -or
    -not $portfolioSource.Contains("importPortfolioSnapshot(importFile") -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-file"') -or
    -not $portfolioSource.Contains('data-testid="portfolio-import-submit"') -or
    -not $strictAuthBrowserSource.Contains("runPortfolioImportScenario") -or
    -not $strictAuthBrowserSource.Contains("importPortfolioFileFixture") -or
    -not $strictAuthBrowserSource.Contains("importInvalidPortfolioFileFixture") -or
    -not $strictAuthBrowserSource.Contains("NO_VALID_HOLDING_ROWS") -or
    -not $strictAuthBrowserSource.Contains("Observed headers: Stock Name, Market Value") -or
    -not $strictAuthBrowserSource.Contains("Row 2: Stock Name=Yinglian; Market Value=1000") -or
    -not $strictAuthBrowserSource.Contains("portfolio malformed import broker template hint") -or
    -not $strictAuthBrowserSource.Contains("portfolio malformed import repair suggestion") -or
    -not $strictAuthBrowserSource.Contains("Futu/Moomoo exports") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Portfolio import malformed-file UX") -or
    -not $strictAuthBrowserSource.Contains("setInputFiles") -or
	    -not $strictAuthBrowserSource.Contains("htsc-holdings.tsv") -or
	    -not $strictAuthBrowserSource.Contains("Huatai Securities export") -or
	    -not $strictAuthBrowserSource.Contains("gtja-positions.csv") -or
	    -not $strictAuthBrowserSource.Contains("Guotai Junan Securities export") -or
	    -not $strictAuthBrowserSource.Contains("futu-moomoo-positions.csv") -or
	    -not $strictAuthBrowserSource.Contains("Futu/Moomoo broker export") -or
	    -not $strictAuthBrowserSource.Contains("tiger-portfolio.csv") -or
	    -not $strictAuthBrowserSource.Contains("Tiger broker export") -or
	    -not $strictAuthBrowserSource.Contains("multipart/form-data") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Portfolio import multi-broker upload") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Portfolio import upload")) {
  throw "Portfolio file import must stay on shared httpClient FormData/operator-header path"
}
if (-not $caseLibraryClientSource.Contains("assertCaseLibraryItem") -or
    -not $caseLibraryClientSource.Contains("assertCaseLibrarySummary") -or
    -not $caseLibraryClientSource.Contains("assertReviewTagItem") -or
    -not $caseLibraryClientSource.Contains("assertErrorLedgerItem") -or
    -not $caseLibraryClientSource.Contains("function isStrongEvidenceValue") -or
    -not $typesSource.Contains("evidence_strength: 'LOW' | 'PENDING' | 'MISSING' | (string & {})") -or
    $typesSource.Contains("evidence_strength: 'LOW' | 'SUPPORTING_ONLY' | 'PENDING' | 'MISSING' | (string & {})") -or
    -not $caseLibraryClientSource.Contains("normalized === 'RESEARCH_GRADE'") -or
    -not $caseLibraryClientSource.Contains("normalized === 'PRIMARY_EVIDENCE_READY'") -or
    -not $caseLibraryClientSource.Contains("normalized.includes('STRONG')") -or
    -not $caseLibraryClientSource.Contains("normalized.includes('PRIMARY')") -or
    -not $caseLibraryClientSource.Contains("assertKnowledgePatchItem") -or
    -not $caseLibraryClientSource.Contains("assertEvaluationRunItem") -or
    -not $caseLibraryClientSource.Contains("assertEvaluationSandboxBoundary") -or
    -not $caseLibraryClientSource.Contains("evaluation evidence must not become a strong conclusion") -or
    -not $caseLibraryClientSource.Contains("assertStrategyExperimentReport") -or
    -not $caseLibraryClientSource.Contains("assertStrategyExperimentBoundary") -or
    -not $caseLibraryClientSource.Contains("strategy experiment evidence must not become a strong conclusion") -or
    -not $caseLibraryClientSource.Contains("strategy experiment review must stay simulation-only") -or
    -not $caseLibraryClientSource.Contains("assertKnowledgeVersionItem") -or
    -not $caseLibraryClientSource.Contains("assertKnowledgeVersionBoundary") -or
    -not $caseLibraryClientSource.Contains("version evidence must not become a strong conclusion") -or
    -not $caseLibraryClientSource.Contains("version review must stay simulation-only") -or
    -not $caseLibraryClientSource.Contains("assertPostPublishRegressionReport") -or
    -not $caseLibraryClientSource.Contains("assertPostPublishRegressionBoundary") -or
    -not $caseLibraryClientSource.Contains("regression evidence must not become a strong conclusion") -or
    -not $caseLibraryClientSource.Contains("regression review must stay simulation-only") -or
    -not $caseLibraryClientSource.Contains("assertVersionDiffResult") -or
    -not $caseLibraryClientSource.Contains("assertRollbackResult") -or
    -not $caseLibraryClientSource.Contains("assertDeleteResult") -or
    -not $caseLibraryClientSource.Contains(".then(assertCaseLibrarySummary)") -or
    -not $caseLibraryClientSource.Contains(".then(assertCaseLibraryList)") -or
    -not $caseLibraryClientSource.Contains(".then(assertReviewTagSummary)") -or
    -not $caseLibraryClientSource.Contains(".then(assertErrorLedgerSummary)") -or
    -not $caseLibraryClientSource.Contains(".then(assertKnowledgePatchSummary)") -or
    -not $caseLibraryClientSource.Contains(".then(assertEvaluationRunItem)") -or
    -not $caseLibraryClientSource.Contains(".then(assertStrategyExperimentReport)") -or
    -not $caseLibraryClientSource.Contains(".then(assertEvaluationRunList)") -or
    -not $caseLibraryClientSource.Contains(".then(assertKnowledgeVersionList)") -or
    -not $caseLibraryClientSource.Contains(".then(assertKnowledgeVersionItem)") -or
    -not $caseLibraryClientSource.Contains(".then(assertVersionDiffResult)") -or
    -not $caseLibraryClientSource.Contains(".then(assertRollbackResult)") -or
    -not $caseLibraryClientSource.Contains(".then(assertDeleteResult)") -or
    -not $caseLibraryClientSource.Contains("request<unknown>('/case-library/summary')") -or
    -not $caseLibraryClientSource.Contains("request<unknown>('/case-library/patches/summary')") -or
    -not $caseLibraryClientSource.Contains('request<unknown>(`/case-library/patches/${patchId}/evaluate`') -or
    -not $caseLibraryClientSource.Contains('request<unknown>(`/case-library/patches/${patchId}/strategy-experiment`') -or
    -not $caseLibraryClientSource.Contains('request<unknown>(`/case-library/knowledge-versions/${versionId}/regression`') -or
    -not $caseLibraryClientSource.Contains('request<unknown>(`/case-library/knowledge-versions/${versionId}/rollback`') -or
    -not $caseLibraryClientSource.Contains('request<unknown>(`/case-library/patches/${patchId}/approve-with-evaluation`')) {
  throw "caseLibraryClient is missing Case/Evaluation/Knowledge Version response guards"
}
if (-not $caseLibraryClientSource.Contains("rerunKnowledgeVersionRegression") -or
    -not $caseLibraryClientSource.Contains('knowledge-versions/${versionId}/regression') -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-versions-page"') -or
    -not $knowledgeVersionsSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $knowledgeVersionsSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $knowledgeVersionsSource.Contains("canWriteKnowledgeVersions") -or
    -not $knowledgeVersionsSource.Contains("canRollbackKnowledge") -or
    -not $knowledgeVersionsSource.Contains("knowledgeVersionWriteDisabledReason") -or
    -not $knowledgeVersionsSource.Contains("rollbackDisabledReason") -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-write-role"') -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-write-disabled-reason"') -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-rollback-role"') -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-rollback-disabled-reason"') -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-create-draft"') -or
    -not $knowledgeVersionsSource.Contains("const v = await createKnowledgeVersion({") -or
    $knowledgeVersionsSource.Contains("createKnowledgeVersion('") -or
    -not $knowledgeVersionsSource.Contains("if (!canWriteKnowledgeVersions)") -or
    -not $knowledgeVersionsSource.Contains("if (!canRollbackKnowledge)") -or
    -not $knowledgeVersionsSource.Contains("disabled={saving || !canWriteKnowledgeVersions}") -or
    -not $knowledgeVersionsSource.Contains("disabled={saving || !canRollbackKnowledge}") -or
    -not $knowledgeVersionsSource.Contains("disabled={saving || ver.status === 'draft' || !canWriteKnowledgeVersions}") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-rollback-") -or
    -not $knowledgeVersionsSource.Contains('data-testid="knowledge-version-regression-overview"') -or
    -not $knowledgeVersionsSource.Contains("function knowledgeVersionEvidenceStrengthLabel") -or
    -not $knowledgeVersionsSource.Contains("function knowledgeVersionBlocker") -or
    -not $knowledgeVersionsSource.Contains("function knowledgeVersionNextAction") -or
    -not $knowledgeVersionsSource.Contains("function reviewGateEvidenceStrength") -or
    -not $knowledgeVersionsSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW')") -or
    $knowledgeVersionsSource.Contains("fallback = 'SUPPORTING_ONLY'") -or
    -not $knowledgeVersionsSource.Contains("['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $knowledgeVersionsSource.Contains("'RESEARCH_GRADE'") -or
    -not $knowledgeVersionsSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $knowledgeVersionsSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $knowledgeVersionsSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $knowledgeVersionsSource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN', 'SUPPORTING_ONLY'].includes(normalized)) return normalized") -or
    $knowledgeVersionsSource.Contains("return 'SUPPORTING_ONLY'") -or
    -not $knowledgeVersionsSource.Contains("function regressionReportEvidenceStrength") -or
    -not $knowledgeVersionsSource.Contains("return reviewGateEvidenceStrength(report?.evidence_strength, 'LOW')") -or
    $knowledgeVersionsSource.Contains("return reviewGateEvidenceStrength(report?.evidence_strength, 'SUPPORTING_ONLY')") -or
    -not $knowledgeVersionsSource.Contains("function regressionReportBlocker") -or
    -not $knowledgeVersionsSource.Contains("function regressionReportNextAction") -or
    -not $knowledgeVersionsSource.Contains("const apiStrength = reviewGateEvidenceStrength(version.evidence_strength)") -or
    $knowledgeVersionsSource.Contains("const apiStrength = reviewGateEvidenceStrength(version.evidence_strength, '')") -or
    -not $knowledgeVersionsSource.Contains("version.status || 'active'") -or
    -not $knowledgeVersionsSource.Contains("policy?.blocking === true") -or
    -not $knowledgeVersionsSource.Contains("impact?.auto_blocks_promotion === true") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-governance-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-governance-id-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-evidence-strength-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-blocker-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-next-action-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-simulation-boundary-") -or
    -not $knowledgeVersionsSource.Contains("simulation_only={String(ver.simulation_only)} / is_real_trade={String(ver.is_real_trade)} / evidence_usage={ver.evidence_usage} / strong_conclusion_allowed={String(ver.strong_conclusion_allowed)} / SIM_*") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-governance-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-report-id-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-evidence-strength-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-blocker-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-next-action-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-simulation-boundary-") -or
    -not $knowledgeVersionsSource.Contains("simulation_only={String(regression?.simulation_only ?? true)} / is_real_trade={String(regression?.is_real_trade ?? false)} / evidence_usage={regression?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(regression?.strong_conclusion_allowed ?? false)} / SIM_*") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-rerun-regression-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-quality-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-policy-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-remediation-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-impact-") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-waiver-") -or
    -not $knowledgeVersionsSource.Contains("regression_waiver") -or
    -not $knowledgeVersionsSource.Contains("knowledge_promotion_regression_waiver_v1") -or
    -not $knowledgeVersionsSource.Contains("knowledge_impact") -or
    -not $knowledgeVersionsSource.Contains("OBSERVATION_ONLY") -or
    -not $knowledgeVersionsSource.Contains("case_set_quality") -or
    -not $knowledgeVersionsSource.Contains("case_set_quality_policy") -or
    -not $knowledgeVersionsSource.Contains("remediation") -or
    -not $knowledgeVersionsSource.Contains("quality_warnings") -or
    -not $caseLibraryClientSource.Contains("CreateKnowledgeVersionDraftPayload") -or
    -not $caseLibraryClientSource.Contains("function sanitizeDirectDraftApprovalRecord") -or
    -not $caseLibraryClientSource.Contains("delete record.evidence_refs") -or
    -not $caseLibraryClientSource.Contains("const KNOWLEDGE_VERSION_APPROVAL_REF_TYPES = new Set(['backtest', 'evaluation', 'regression_waiver', 'verdict'])") -or
    -not $caseLibraryClientSource.Contains("function assertKnowledgeVersionApprovalEvidenceRef") -or
    -not $caseLibraryClientSource.Contains("source must be a validated review artifact") -or
    -not $caseLibraryClientSource.Contains("evidence usage must stay review_gate_only") -or
    -not $caseLibraryClientSource.Contains("assertKnowledgeVersionApprovalEvidenceRef(ref, index)") -or
    $caseLibraryClientSource.Contains("body: JSON.stringify({ description, ...governance })") -or
    -not $caseLibraryClientSource.Contains("status: 'draft'") -or
    -not $typesSource.Contains("export interface CreateKnowledgeVersionDraftPayload") -or
    -not $typesSource.Contains("export interface KnowledgeVersionApprovalEvidenceRef") -or
    -not $typesSource.Contains("evidence_refs?: KnowledgeVersionApprovalEvidenceRef[]") -or
    $typesSource.Contains("evidence_refs?: Array<Record<string, any> | string>") -or
    -not $typesSource.Contains("evidence_refs?: never") -or
    -not $typesSource.Contains("knowledge_impact") -or
    -not $typesSource.Contains("evidence_strength: 'LOW' | 'MISSING' | 'PENDING' | (string & {})") -or
    $typesSource.Contains("evidence_strength: 'LOW' | 'SUPPORTING_ONLY' | 'MISSING' | 'PENDING' | (string & {})") -or
    -not $typesSource.Contains("strong_conclusion_allowed: boolean") -or
    -not $typesSource.Contains("auto_blocks_promotion") -or
    -not $dashboardSource.Contains("knowledgeRegressionQualityWarnings") -or
    -not $dashboardSource.Contains("knowledgeRegressionAllWarnings") -or
    -not $dashboardSource.Contains("dashboard-knowledge-regression-impact") -or
    -not $dashboardSource.Contains("dashboard-knowledge-regression-quality-policy") -or
    -not $dashboardSource.Contains("dashboard-knowledge-regression-remediation") -or
    -not $knowledgeVersionsSource.Contains("knowledge-version-regression-summary-") -or
    -not $knowledgeVersionsSource.Contains("ver.status === 'draft'") -or
    -not $strictAuthBrowserSource.Contains("runKnowledgeVersionsRegressionScenario") -or
    -not $strictAuthBrowserSource.Contains("single_symbol_representative_cases") -or
    -not $strictAuthBrowserSource.Contains("knowledge_regression_case_set_quality_v1") -or
    -not $strictAuthBrowserSource.Contains("knowledge_post_publish_impact_summary_v1") -or
    -not $strictAuthBrowserSource.Contains("knowledge-version-regression-quality-") -or
    -not $strictAuthBrowserSource.Contains("knowledge-version-regression-policy-") -or
    -not $strictAuthBrowserSource.Contains("knowledge-version-regression-remediation-") -or
    -not $strictAuthBrowserSource.Contains("knowledge-version-regression-impact-") -or
    -not $strictAuthBrowserSource.Contains("knowledge-version-regression-waiver-") -or
    -not $strictAuthBrowserSource.Contains("WAIVER-BROWSER-001") -or
    $strictAuthBrowserSource.Contains("{ source_type: 'case', source_id: 'CASE_BROWSER_REVIEW' }") -or
    -not $strictAuthBrowserSource.Contains("Knowledge Versions post-publish regression rerun") -or
    -not $strictAuthBrowserSource.Contains("assertKnowledgeVersionsReviewGateBoundaryVisible") -or
    -not $strictAuthBrowserSource.Contains("Knowledge Versions visible review-gate boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Knowledge Versions visible review-gate boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Knowledge Versions post-publish regression")) {
  throw "Knowledge Versions post-publish regression is missing active page/client/strict-auth browser linkage"
}
if (-not $caseLibraryClientSource.Contains("runPatchEvaluation") -or
    -not $caseLibraryClientSource.Contains('`/case-library/patches/${patchId}/evaluate`') -or
    -not $caseLibraryClientSource.Contains("runPatchStrategyExperiment") -or
    -not $caseLibraryClientSource.Contains('`/case-library/patches/${patchId}/strategy-experiment`') -or
    -not $caseLibraryClientSource.Contains("approvePatchWithEvaluation") -or
    -not $caseLibraryClientSource.Contains('`/case-library/patches/${patchId}/approve-with-evaluation`') -or
    -not $caseLibrarySource.Contains("async function handleApproveWithEval") -or
    -not $caseLibrarySource.Contains("const evalResult = await runPatchEvaluation(patch.patch_id, true)") -or
    -not $caseLibrarySource.Contains("await approvePatchWithEvaluation(patch.patch_id, 'human'") -or
    -not $caseLibrarySource.Contains("evaluation_id: evalResult.eval_id") -or
    -not $caseLibrarySource.Contains("risk_boundary: patch.risk_note") -or
    -not $caseLibrarySource.Contains("promotionFeedback") -or
    -not $caseLibrarySource.Contains("case-library-promotion-feedback-") -or
    -not $caseLibrarySource.Contains("setPromotionFeedback") -or
    -not $evaluationSandboxSource.Contains("useOperatorContext") -or
    -not $evaluationSandboxSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $evaluationSandboxSource.Contains("canRunEvaluationSandbox") -or
    -not $evaluationSandboxSource.Contains("evaluationSandboxDisabledReason") -or
    -not $evaluationSandboxSource.Contains('data-testid="evaluation-sandbox-write-role"') -or
    -not $evaluationSandboxSource.Contains('data-testid="evaluation-sandbox-write-disabled-reason"') -or
    -not $evaluationSandboxSource.Contains("if (!canRunEvaluationSandbox)") -or
    -not $evaluationSandboxSource.Contains("disabled={experimenting === patch.patch_id || !canRunEvaluationSandbox}") -or
    -not $evaluationSandboxSource.Contains("disabled={running === patch.patch_id || !canRunEvaluationSandbox}") -or
    -not $evaluationSandboxSource.Contains('data-testid="evaluation-sandbox-page"') -or
    -not $evaluationSandboxSource.Contains('data-testid="evaluation-sandbox-summary"') -or
    -not $evaluationSandboxSource.Contains("function evaluationEvidenceStrengthLabel") -or
    -not $evaluationSandboxSource.Contains("function reviewGateEvidenceStrength") -or
    -not $evaluationSandboxSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = 'LOW')") -or
    -not $evaluationSandboxSource.Contains("['HIGH', 'STRONG', 'PRIMARY', 'PRIMARY_EVIDENCE', 'PASS', 'READY'].includes(normalized)) return 'MEDIUM'") -or
    -not $evaluationSandboxSource.Contains("'RESEARCH_GRADE'") -or
    -not $evaluationSandboxSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $evaluationSandboxSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $evaluationSandboxSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $evaluationSandboxSource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN', 'SUPPORTING_ONLY'].includes(normalized)) return normalized") -or
    $evaluationSandboxSource.Contains("function reviewGateEvidenceStrength(value?: string | null, fallback = '')") -or
    -not $evaluationSandboxSource.Contains("const apiStrength = reviewGateEvidenceStrength(latestEval?.evidence_strength)") -or
    $evaluationSandboxSource.Contains("if (experimentReport) return 'SUPPORTING_ONLY") -or
    -not $evaluationSandboxSource.Contains("if (experimentReport) return 'LOW") -or
    -not $evaluationSandboxSource.Contains("function evaluationRunBoundaryViolation") -or
    -not $evaluationSandboxSource.Contains("latestEval.simulation_only !== true") -or
    -not $evaluationSandboxSource.Contains("latestEval.is_real_trade === true") -or
    -not $evaluationSandboxSource.Contains("latestEval.strong_conclusion_allowed === true") -or
    -not $evaluationSandboxSource.Contains("latestEval.evidence_usage !== 'review_gate_only'") -or
    -not $evaluationSandboxSource.Contains("Evaluation run evidence usage must remain review_gate_only") -or
    -not $evaluationSandboxSource.Contains("function evaluationPatchBlocker") -or
    -not $evaluationSandboxSource.Contains("function evaluationPatchNextAction") -or
    -not $evaluationSandboxSource.Contains("function buildEvaluationRunGovernance") -or
    -not $evaluationSandboxSource.Contains("latestEval.total_cases <= 0") -or
    -not $evaluationSandboxSource.Contains("review_gate_only") -or
    -not $evaluationSandboxSource.Contains("function buildStrategyExperimentGovernance") -or
    -not $evaluationSandboxSource.Contains("function strategyExperimentEvidenceStrength") -or
    $evaluationSandboxSource.Contains("if (['LOW', 'MISSING', 'PENDING'].includes(normalized)) return normalized") -or
    -not $evaluationSandboxSource.Contains("if (['MISSING', 'PENDING'].includes(normalized)) return normalized") -or
    -not $evaluationSandboxSource.Contains("report.simulation_only === true") -or
    -not $evaluationSandboxSource.Contains("report.is_real_trade === true") -or
    -not $evaluationSandboxSource.Contains("report.strong_conclusion_allowed === true") -or
    $evaluationSandboxSource.Contains("return 'SUPPORTING_ONLY'") -or
    -not $evaluationSandboxSource.Contains("return 'LOW'") -or
    -not $evaluationSandboxSource.Contains("StrategyExperimentGovernancePanel") -or
    -not $evaluationSandboxSource.Contains("latestEval.regressed_cases > 0") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-governance-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-id-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-evidence-strength-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-blocker-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-next-action-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-simulation-boundary-") -or
    -not $evaluationSandboxSource.Contains("simulation_only={String(latestEval?.simulation_only ?? true)} / is_real_trade={String(latestEval?.is_real_trade ?? false)} / evidence_usage={latestEval?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(latestEval?.strong_conclusion_allowed ?? false)} / SIM_*") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-patch-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-run-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-summary-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-governance-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-id-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-evidence-strength-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-blocker-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-next-action-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-evaluation-simulation-boundary-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-report-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-governance-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-id-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-evidence-strength-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-blocker-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-next-action-") -or
    -not $evaluationSandboxSource.Contains("evaluation-sandbox-experiment-simulation-boundary-") -or
    -not $evaluationSandboxSource.Contains("simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*") -or
    -not $typesSource.Contains("evidence_usage: 'review_gate_only'") -or
    -not $typesSource.Contains("evidence_strength: 'LOW' | 'MISSING' | 'PENDING' | (string & {})") -or
    $typesSource.Contains("evidence_strength: 'SUPPORTING_ONLY' | 'LOW' | 'MISSING' | 'PENDING' | (string & {})") -or
    -not $typesSource.Contains("strong_conclusion_allowed: boolean") -or
    -not $strictAuthBrowserSource.Contains("runEvaluationSandboxScenario") -or
    -not $strictAuthBrowserSource.Contains("assertEvaluationSandboxReviewGateBoundaryVisible") -or
    -not $strictAuthBrowserSource.Contains("Evaluation Sandbox visible review-gate boundary is missing") -or
    -not $strictAuthBrowserSource.Contains("Evaluation Sandbox patch evaluation") -or
    -not $strictAuthBrowserSource.Contains("Evaluation Sandbox strategy experiment") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Evaluation Sandbox visible review-gate boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Evaluation Sandbox patch evaluation and strategy experiment")) {
  throw "Evaluation Sandbox is missing active page/client/strict-auth browser evaluation linkage"
}
if (-not $configClientSource.Contains("approval_gate") -or
    -not $configClientSource.Contains("required_secret_refs") -or
    -not $configClientSource.Contains("restoreExternalConfig") -or
    -not $configClientSource.Contains("assertConfigVersionItem") -or
    -not $configClientSource.Contains("assertConfigVersionList") -or
    -not $configClientSource.Contains("assertExternalConfigRestoreResult") -or
    -not $configClientSource.Contains("assertConfigProfile") -or
    -not $configClientSource.Contains("assertConfigSchemaItem") -or
    -not $configClientSource.Contains("assertPolicyCheckResult") -or
    -not $configClientSource.Contains("assertConfigDraft") -or
    -not $configClientSource.Contains("assertRuntimeConfigPatchResult") -or
    -not $configClientSource.Contains("assertConfigDraftApplyResult") -or
    -not $configClientSource.Contains("assertConfigRollbackResult") -or
    -not $configClientSource.Contains("assertDataSourcesConfig") -or
    -not $configClientSource.Contains("assertDataSourceTestResult") -or
    -not $configClientSource.Contains(".then(assertConfigVersionList)") -or
    -not $configClientSource.Contains(".then(assertExternalConfigRestoreResult)") -or
    -not $configClientSource.Contains(".then(assertConfigProfile)") -or
    -not $configClientSource.Contains(".then(assertConfigSchema)") -or
    -not $configClientSource.Contains(".then(assertPolicyCheckResult)") -or
    -not $configClientSource.Contains(".then(assertConfigDraft)") -or
    -not $configClientSource.Contains(".then(assertRuntimeConfigPatchResult)") -or
    -not $configClientSource.Contains(".then(assertDataSourcesConfig)") -or
    -not $configClientSource.Contains(".then(assertDataSourceTestResult)") -or
    -not $configClientSource.Contains("request<unknown>('/agents/data-sources')") -or
    -not $configClientSource.Contains('request<unknown>(`/agents/data-sources/${key}/test`') -or
    -not $configClientSource.Contains("assertStringArray(item.effective_scope") -or
    -not $configClientSource.Contains("ensureArray(gate.required_secret_refs") -or
    -not $configVersionsSource.Contains("approval_gate.status") -or
    -not $configVersionsSource.Contains("secret_vault_version_required") -or
    -not $configVersionsSource.Contains("required_secret_refs.length") -or
    -not $configVersionsSource.Contains("handleExternalRestore") -or
    -not $configVersionsSource.Contains("restoreDialog") -or
    -not $configVersionsSource.Contains("if (!canRestoreExternalConfig || !version.profile_id) return") -or
    -not $configVersionsSource.Contains("disabled={!canRestoreExternalConfig || restoringAuditId === version.audit_id}") -or
    -not $configVersionsSource.Contains('data-testid="config-approved-restore-role"') -or
    -not $configVersionsSource.Contains('data-testid="config-approved-restore-disabled-reason"') -or
    -not $configVersionsSource.Contains("configRestoreDisabledReason") -or
    -not $configVersionsSource.Contains("title={!canRestoreExternalConfig ? configRestoreDisabledReason : undefined}") -or
    -not $configVersionsSource.Contains('data-testid="config-approved-restore-modal"') -or
    -not $configVersionsSource.Contains('data-testid="config-approved-restore-confirm-secret-safe"') -or
    $configVersionsSource.Contains("window.prompt") -or
    -not $strictAuthBrowserSource.Contains("runConfigVersionsRestoreScenario") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Config Versions approved restore modal") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Config Versions multi-surface approved restore") -or
    -not $strictAuthBrowserSource.Contains("agent_runtime:data_sources_config") -or
    -not $strictAuthBrowserSource.Contains("agent_runtime:market_data_adapter_config") -or
    -not $configVersionsSource.Contains("setRestoreStatus") -or
    -not $configVersionsSource.Contains("roleAllows(operator.role, 'admin')")) {
  throw "Config Versions is missing secret-safe rollback approval gate display or restore action"
}
if (-not $backendTuningSource.Contains("useOperatorContext()") -or
    -not $backendTuningSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $backendTuningSource.Contains("tuningWriteDisabledReason") -or
    -not $backendTuningSource.Contains('data-testid="backend-tuning-role"') -or
    -not $backendTuningSource.Contains('data-testid="backend-tuning-disabled-reason"') -or
    -not $backendTuningSource.Contains('data-testid="backend-tuning-apply-runtime"') -or
    -not $backendTuningSource.Contains('data-testid="backend-tuning-submit-draft"') -or
    -not $backendTuningSource.Contains("if (!canManageBackendTuning) return") -or
    -not $backendTuningSource.Contains("disabled={!canManageBackendTuning}")) {
  throw "BackendTuningPage config writes must stay behind the admin operator role guard"
}
if (-not $pluginClientSource.Contains("archivePlugin") -or
    -not $pluginClientSource.Contains("upgradePlugin") -or
    -not $pluginClientSource.Contains("uploadPluginArtifact") -or
    -not $pluginClientSource.Contains("cleanupPluginArtifacts") -or
    -not $pluginClientSource.Contains("PluginUpgradePayload") -or
    -not $pluginClientSource.Contains("assertPluginList") -or
    -not $pluginClientSource.Contains("assertPluginItem") -or
    -not $pluginClientSource.Contains("assertPluginRuntimePlan") -or
    -not $pluginClientSource.Contains("assertPluginUsageStatsItem") -or
    -not $pluginClientSource.Contains("assertPluginUsageHistoryResponse") -or
    -not $pluginClientSource.Contains("assertPluginArtifactUploadResult") -or
    -not $pluginClientSource.Contains("assertPluginArtifactCleanupResult") -or
    -not $pluginClientSource.Contains("assertPluginAuditList") -or
    -not $pluginClientSource.Contains("assertPluginValidateResult") -or
    -not $pluginClientSource.Contains("assertPluginSandboxRunResult") -or
    -not $pluginClientSource.Contains(".then(assertPluginList)") -or
    -not $pluginClientSource.Contains(".then(assertPluginItem)") -or
    -not $pluginClientSource.Contains(".then(assertPluginRuntimePlan)") -or
    -not $pluginClientSource.Contains(".then(assertPluginUsageStatsList)") -or
    -not $pluginClientSource.Contains(".then(assertPluginUsageHistoryResponse)") -or
    -not $pluginClientSource.Contains(".then(assertPluginArtifactUploadResult)") -or
    -not $pluginClientSource.Contains(".then(assertPluginArtifactCleanupResult)") -or
    -not $pluginClientSource.Contains(".then(assertPluginAuditList)") -or
    -not $pluginClientSource.Contains(".then(assertPluginValidateResult)") -or
    -not $pluginClientSource.Contains(".then(assertPluginSandboxRunResult)") -or
    -not $pluginClientSource.Contains('`/plugins/${pluginId}/upgrade`') -or
    -not $pluginClientSource.Contains('`/plugins/${pluginId}/artifacts`') -or
    -not $pluginClientSource.Contains("'/plugins/artifacts/cleanup'") -or
    -not $pluginClientSource.Contains("getPluginUsageStats") -or
    -not $pluginClientSource.Contains("getPluginUsageHistory") -or
    -not $pluginClientSource.Contains("'/plugins/usage/stats'") -or
    -not $pluginClientSource.Contains('`/plugins/usage/history?days=${days}`') -or
    -not $pluginClientSource.Contains('`/plugins/${pluginId}/archive`') -or
    -not $pluginRegistrySource.Contains("handleArchive") -or
    -not $pluginRegistrySource.Contains("handleUpgrade") -or
    -not $pluginRegistrySource.Contains("handleArtifactUpload") -or
    -not $pluginRegistrySource.Contains("handleArtifactCleanupDryRun") -or
    -not $pluginRegistrySource.Contains("package_artifact") -or
    -not $pluginRegistrySource.Contains("migration_steps") -or
    -not $pluginRegistrySource.Contains("uploaded_package") -or
    -not $pluginRegistrySource.Contains("artifact_storage_verified") -or
    -not $pluginRegistrySource.Contains("packageHashScanStatus") -or
    -not $pluginRegistrySource.Contains("packageScanStatus") -or
    -not $pluginRegistrySource.Contains("packageExternalScanStatus") -or
    -not $pluginRegistrySource.Contains("packageExternalScanProvider") -or
    -not $pluginRegistrySource.Contains("externalScanDetailLabel") -or
    -not $pluginRegistrySource.Contains("matches_artifact_checksum") -or
    -not $pluginRegistrySource.Contains("packageRetentionLabel") -or
    -not $pluginRegistrySource.Contains("hash_scan_status") -or
    -not $pluginRegistrySource.Contains("scan_status") -or
    -not $pluginRegistrySource.Contains("external_scan_status") -or
    -not $pluginRegistrySource.Contains("external_scan_status") -or
    -not $pluginRegistrySource.Contains("retention_expires_at") -or
    -not $pluginRegistrySource.Contains("metadata-only") -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-file"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-checksum"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-upload-action"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-upload-result"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-cleanup-dry-run-action"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-artifact-cleanup-result"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-package-artifact-state"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-archive-action"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-upgrade-action"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-upgraded-state"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-archived-state"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-resource-summary"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-usage-summary"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-usage-history"') -or
    -not $pluginRegistrySource.Contains("selectedUsageStats") -or
    -not $pluginRegistrySource.Contains("selectedUsageHistory") -or
    -not $pluginRegistrySource.Contains("resource_limit_warnings") -or
    -not $pluginRegistrySource.Contains("resourceSummary.quota_status") -or
    -not $pluginRegistrySource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $pluginRegistrySource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $pluginRegistrySource.Contains("canRunPluginChecks") -or
    -not $pluginRegistrySource.Contains("pluginRuntimeActionDisabledReason") -or
    -not $pluginRegistrySource.Contains("pluginLifecycleActionDisabledReason") -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-runtime-action-role"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-runtime-action-disabled-reason"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-lifecycle-action-role"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-lifecycle-action-disabled-reason"') -or
    -not $pluginRegistrySource.Contains('data-testid="plugin-validate-action"') -or
    -not $pluginRegistrySource.Contains('data-testid={`plugin-sandbox-run-${agent.agent_id}`}') -or
    -not $pluginRegistrySource.Contains("if (!canRunPluginChecks)") -or
    -not $pluginRegistrySource.Contains("if (!canTogglePlugins)") -or
    -not $pluginRegistrySource.Contains("disabled={loading || !canRunPluginChecks}") -or
    -not $pluginRegistrySource.Contains("disabled={!agent.execution_sandbox.hot_reload_allowed || runningAgentId !== '' || !canRunPluginChecks}") -or
    -not $strictAuthBrowserSource.Contains("selectorForAppLink") -or
    -not $strictAuthBrowserSource.Contains("navigateByAppLink(page, '/backend', 'Plugin Registry prerequisite Backend Status route')") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser app-link navigation") -or
    -not $strictAuthBrowserSource.Contains("runPluginArchiveScenario") -or
    -not $strictAuthBrowserSource.Contains("Plugin artifact upload hash verification") -or
    -not $strictAuthBrowserSource.Contains("provider_status: 'READY'") -or
    -not $strictAuthBrowserSource.Contains("threat_intel_status: 'CURRENT'") -or
    -not $strictAuthBrowserSource.Contains("matches_artifact_checksum") -or
    -not $strictAuthBrowserSource.Contains("/api/plugins/artifacts/cleanup") -or
    -not $strictAuthBrowserSource.Contains("cleanupRequestPayload?.dry_run !== true") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Plugin artifact cleanup dry-run") -or
    -not $strictAuthBrowserSource.Contains("Plugin usage history") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Plugin archive lifecycle")) {
  throw "Plugin Registry is missing runtime-check role guard, archived lifecycle, or resource quota UI/client/strict-auth coverage"
}
if (-not $signalOpsSource.Contains("validateAutoPaperNumericInputs") -or
    -not $signalOpsSource.Contains("setFormValidationErrors(numericValidation.errors)") -or
    -not $signalOpsSource.Contains("numericFieldHelp('initialCash')") -or
    -not $signalOpsSource.Contains("aria-invalid={Boolean(error)}") -or
    $signalOpsSource.Contains("toNumber(form.")) {
  throw "SignalOps auto-paper config form is missing explicit numeric validation or still silently falls back from invalid inputs"
}
$signalOpsLifecycleClientBoundaryMarkers = @(
  "assertSignalItem",
  "assertSignalTransitionItem",
  "assertRequiredSimulationOnlyRecordBoundary(transition, 'SignalOps transition')",
  "assertSignalReviewItem",
  "assertRequiredSimulationOnlyRecordBoundary(review, 'SignalOps review')",
  "assertSignalDetail",
  "assertPaperPortfolioItem",
  "assertOptionalPaperPortfolioItem",
  "assertPaperPositionItem",
  "assertRequiredSimulationOnlyRecordBoundary(position, 'SignalOps paper position')",
  "assertPaperOrderItem",
  "assertAgentSimulationCaseItem",
  "assertRequiredSimulationOnlyRecordBoundary",
  "request<unknown>('/signals'",
  'request<unknown>(`/signals${qs.toString() ?',
  'request<unknown>(`/signals/${signalId}`',
  'request<unknown>(`/signals/${signalId}/transition`',
  'request<unknown>(`/signals/${signalId}/attach-run`',
  'request<unknown>(`/signals/${signalId}/conditions`',
  'request<unknown>(`/signals/${signalId}/review`',
  'request<unknown>(`/signalops/${signalId}/paper-portfolio`',
  'request<unknown>(`/signalops/${signalId}/paper-portfolio${qs}`',
  'request<unknown>(`/signalops/${signalId}/paper-orders`',
  'request<unknown>(`/signalops/${signalId}/paper-positions`',
  'request<unknown>(`/signalops/${signalId}/paper-orders/${orderId}/fill`',
  'request<unknown>(`/signalops/${signalId}/paper-cases`',
  'request<unknown>(`/knowledge/cases?source=${encodeURIComponent(source)}`',
  "}).then(assertSignalItem)",
  "}).then(assertSignalTransitionItem)",
  "}).then(assertSignalReviewItem)",
  "}).then(assertPaperPortfolioItem)",
  "}).then(assertPaperOrderItem)",
  "}).then(assertAgentSimulationCaseItem)",
  ".then(assertSignalDetail)",
  ".then(assertOptionalPaperPortfolioItem)",
  ".map(assertSignalItem)",
  ".map(assertPaperOrderItem)",
  ".map(assertPaperPositionItem)",
  ".map(assertAgentSimulationCaseItem)"
)
foreach ($marker in $signalOpsLifecycleClientBoundaryMarkers) {
  if (-not $signalOpsClientSource.Contains($marker)) {
    throw ("SignalOps API client is missing lifecycle/paper response guard: " + $marker)
  }
}
$signalOpsClientBoundaryMarkers = @(
  "assertSignalOpsAutomationBoundary",
  "assertAutoPaperTradingConfigResponse",
  "assertAutoPaperTradingStatusResponse",
  "assertAutoPaperTradingTickResult",
  "assertAutoPaperTradingDailyReviewResult",
  "assertAutoPaperTradingCommandResult",
  "assertAutoPaperTradingReviewDecisionResult",
  "assertReviewDecisionEventExport",
  "assertReviewDecisionEventVerification",
  "assertReviewDecisionEventHandoff",
  "request<unknown>('/signalops/auto-paper/config?compact=true'",
  "request<unknown>('/signalops/auto-paper/status?compact=true'",
  "request<unknown>('/signalops/auto-paper/config'",
  "request<unknown>('/signalops/auto-paper/tick'",
  "request<unknown>('/signalops/auto-paper/daily-review'",
  "request<unknown>('/signalops/auto-paper/command'",
  "request<unknown>('/signalops/auto-paper/review-decisions'",
  'request<unknown>(`/signalops/auto-paper/review-decision-events?${qs.toString()}`',
  "request<unknown>('/signalops/auto-paper/review-decision-events/verify'",
  'request<unknown>(`/signalops/auto-paper/review-decision-events/handoff?${qs.toString()}`',
  "}).then(assertAutoPaperTradingConfigResponse)",
  "}).then(assertAutoPaperTradingStatusResponse)",
  "}).then(assertAutoPaperTradingTickResult)",
  "}).then(assertAutoPaperTradingDailyReviewResult)",
  "}).then(assertAutoPaperTradingCommandResult)",
  "}).then(assertAutoPaperTradingReviewDecisionResult)",
  ".then(assertReviewDecisionEventExport)",
  "}).then(assertReviewDecisionEventVerification)",
  "}).then(assertReviewDecisionEventHandoff)",
  "allowed_order_namespace !== 'SIM_*'",
  "live_module_status !== 'CONFIGURED_DISABLED'",
  "live.order_router !== undefined && live.order_router !== 'DISABLED'"
)
foreach ($marker in $signalOpsClientBoundaryMarkers) {
  if (-not $signalOpsClientSource.Contains($marker)) {
    throw ("SignalOps API client is missing auto-paper simulation/live-disabled boundary guard: " + $marker)
  }
}
$signalOpsStrictBrowserBoundaryMarkers = @(
  "live: { status: 'CONFIGURED_DISABLED', execution_enabled: false, simulation_only: true, is_real_trade: false }",
  "trading_date: '2026-06-03'",
  "case_ids: []",
  "evidence_links: []",
  "tuning_update: {}",
  "cleaned_records: []",
  "review_decisions: []",
  "decision_tree_reviews: []",
  "ok strict-auth browser SignalOps daily review"
)
foreach ($marker in $signalOpsStrictBrowserBoundaryMarkers) {
  if (-not $strictAuthBrowserSource.Contains($marker)) {
    throw ("strict-auth SignalOps browser fixture is missing backend-equivalent auto-paper boundary/default field: " + $marker)
  }
}
if (-not $signalOpsSource.Contains('data-testid="signalops-manual-ops"') -or
    -not $signalOpsSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $signalOpsSource.Contains("roleAllows(operator.role, 'operator')") -or
    -not $signalOpsSource.Contains("roleAllows(operator.role, 'admin')") -or
    -not $signalOpsSource.Contains('data-testid="signalops-operator-policy"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-lifecycle-write-role"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-lifecycle-write-disabled-reason"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-manual-control-role"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-manual-control-disabled-reason"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-runtime-config-role"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-runtime-config-disabled-reason"') -or
    -not $signalOpsSource.Contains('writeDisabledReason') -or
    -not $signalOpsSource.Contains('operateDisabledReason') -or
    -not $signalOpsSource.Contains('configDisabledReason') -or
    -not $signalOpsSource.Contains('if (!canWriteSignalOps) throw new Error(writeDisabledReason)') -or
    -not $signalOpsSource.Contains('if (!canOperateSignalOps) throw new Error(operateDisabledReason)') -or
    -not $signalOpsSource.Contains('if (!canManageSignalOpsConfig) throw new Error(configDisabledReason)') -or
    -not $signalOpsSource.Contains('testId="signalops-run-tick"') -or
    -not $signalOpsSource.Contains('testId="signalops-run-daily-review"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-result-snapshot"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-tick-result-summary"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-daily-review-summary"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-command-result-summary"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-pool-manual-ops"') -or
    -not $signalOpsSource.Contains('signalops-command-FORCE_OPEN_BUY-') -or
    -not $signalOpsSource.Contains('testId="signalops-open-review-window"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-window"') -or
    -not $signalOpsSource.Contains('signalops-review-queue-item-') -or
    -not $signalOpsSource.Contains('signalops-review-governance-') -or
    -not $signalOpsSource.Contains('signalops-review-governance-id-') -or
    -not $signalOpsSource.Contains('signalops-review-evidence-strength-') -or
    -not $signalOpsSource.Contains('function signalOpsReviewGovernanceStrength') -or
    -not $signalOpsSource.Contains("return ['WEAK', 'LOW', 'SUPPORTING_ONLY', 'UNKNOWN', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY', 'PENDING', 'MISSING'].includes(quality)") -or
    -not $signalOpsSource.Contains("if (isWeakEvidenceQuality(quality)) return 'LOW'") -or
    $signalOpsSource.Contains("if (isWeakEvidenceQuality(quality)) return quality === 'SUPPORTING_ONLY' ? 'SUPPORTING_ONLY' : 'LOW'") -or
    -not $signalOpsSource.Contains("'RESEARCH_GRADE'") -or
    -not $signalOpsSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $signalOpsSource.Contains('const governanceEvidenceStrength = signalOpsReviewGovernanceStrength(item.evidence_quality)') -or
    -not $signalOpsSource.Contains("const randomEvidenceReviewStrength = randomEvidence ? signalOpsReviewGovernanceStrength(randomEvidence) : 'LOW'") -or
    $signalOpsSource.Contains("const randomEvidenceReviewStrength = randomEvidence ? signalOpsReviewGovernanceStrength(randomEvidence) : 'UNKNOWN'") -or
    -not $signalOpsSource.Contains("randomValidationEvidence: randomValidationRan ? randomEvidenceReviewStrength") -or
    $signalOpsSource.Contains("latestRandomSummary.evidence_level === 'STRONG'") -or
    $signalOpsSource.Contains("automationSummary.randomValidationEvidence === 'STRONG'") -or
    -not $signalOpsSource.Contains('{displayCode(governanceEvidenceStrength)}') -or
    -not $signalOpsSource.Contains('signalops-review-blocker-') -or
    -not $signalOpsSource.Contains('signalops-review-next-action-') -or
    -not $signalOpsSource.Contains('signalops-review-simulation-boundary-') -or
    -not $signalOpsSource.Contains('SignalOps review simulation-only boundary violated') -or
    -not $signalOpsSource.Contains("tone={isWeakEvidenceQuality(item.evidence_quality) ? 'warn' : 'good'}") -or
    -not $signalOpsSource.Contains("const governanceEvidenceUsage = 'simulation_only'") -or
    -not $signalOpsSource.Contains('const governanceStrongConclusionAllowed = false') -or
    -not $signalOpsSource.Contains('evidence_usage=${governanceEvidenceUsage}') -or
    -not $signalOpsSource.Contains('strong_conclusion_allowed=${String(governanceStrongConclusionAllowed)}') -or
    -not $signalOpsSource.Contains('simulation_only=${String(item.simulation_only)} / is_real_trade=${String(item.is_real_trade)} / evidence_usage=${governanceEvidenceUsage} / strong_conclusion_allowed=${String(governanceStrongConclusionAllowed)} / SIM_*') -or
    -not $signalOpsSource.Contains('function buildPaperOrderGovernance') -or
    -not $signalOpsSource.Contains('function paperOrderWarnings') -or
    -not $signalOpsSource.Contains("action.startsWith('SIM_')") -or
    -not $signalOpsSource.Contains('SignalOps paper order simulation-only boundary violated') -or
    -not $signalOpsSource.Contains('Paper order action must stay in SIM_* namespace') -or
    -not $signalOpsSource.Contains("evidenceStrength: 'LOW'") -or
    -not $signalOpsSource.Contains("evidenceUsage: 'simulation_only'") -or
    -not $signalOpsSource.Contains('strongConclusionAllowed: false') -or
    $signalOpsSource.Contains("evidenceStrength: boundaryBroken || !actionInSimNamespace || !hasIds || warnings.length > 0 || fillBlocked ? 'LOW' : 'SUPPORTING_ONLY'") -or
    -not $signalOpsSource.Contains('signalops-paper-order-governance-') -or
    -not $signalOpsSource.Contains('signalops-paper-order-id-') -or
    -not $signalOpsSource.Contains('signalops-paper-order-evidence-strength-') -or
    -not $signalOpsSource.Contains('signalops-paper-order-blocker-') -or
    -not $signalOpsSource.Contains('signalops-paper-order-next-action-') -or
    -not $signalOpsSource.Contains('signalops-paper-order-simulation-boundary-') -or
    -not $signalOpsSource.Contains('simulation_only={String(governance.simulationOnly)} / is_real_trade={String(governance.isRealTrade)} / evidence_usage={governance.evidenceUsage} / strong_conclusion_allowed={String(governance.strongConclusionAllowed)} / SIM_*') -or
    -not $signalOpsSource.Contains('signalops-review-decision-') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-candidate-baseline"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-parameter-diff-summary"') -or
    -not $signalOpsSource.Contains('candidateBaselineParameterRows(item)') -or
    -not $signalOpsSource.Contains("parameter_diff_summary") -or
    -not $signalOpsSource.Contains("parameter_diff_checksum") -or
    -not $signalOpsSource.Contains("latestDecisionDiffChecksum") -or
    -not $signalOpsSource.Contains("review_decision_event_ledger") -or
    -not $signalOpsSource.Contains("reviewDecisionLedgerHash") -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-event-export-verification"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-event-export-role"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-event-export-disabled-reason"') -or
    -not $signalOpsSource.Contains('canVerifyReviewEventExport={canOperateSignalOps}') -or
    -not $signalOpsSource.Contains('disabled={verificationBusy || !canVerifyReviewEventExport}') -or
    -not $signalOpsSource.Contains('disabled={handoffBusy || !canVerifyReviewEventExport}') -or
    -not $signalOpsSource.Contains('data-testid="signalops-verify-review-event-export"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-handoff-review-event-export"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-event-export-handoff-status"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-review-event-export-shipper-status"') -or
    -not $signalOpsClientSource.Contains("getAutoPaperTradingReviewDecisionEvents") -or
    -not $signalOpsClientSource.Contains("verifyAutoPaperTradingReviewDecisionEventExport") -or
    -not $signalOpsClientSource.Contains("handoffAutoPaperTradingReviewDecisionEvents") -or
    -not $signalOpsClientSource.Contains("/signalops/auto-paper/review-decision-events") -or
    -not $signalOpsClientSource.Contains("/signalops/auto-paper/review-decision-events/verify") -or
    -not $signalOpsClientSource.Contains("/signalops/auto-paper/review-decision-events/handoff") -or
    -not $signalOpsClientSource.Contains("export_signature_status") -or
    -not $signalOpsClientSource.Contains("export_signature") -or
    -not $signalOpsClientSource.Contains("shipper_status?: Record<string, unknown>") -or
    -not $signalOpsSource.Contains("changeType") -or
    -not $strictAuthBrowserSource.Contains("baseline_config") -or
    -not $strictAuthBrowserSource.Contains("candidate_config") -or
    -not $strictAuthBrowserSource.Contains("signalops_candidate_parameter_diff_v1") -or
    -not $strictAuthBrowserSource.Contains("reviewed_parameter_diff_checksum") -or
    -not $strictAuthBrowserSource.Contains("sigops-reviewevent-") -or
    -not $strictAuthBrowserSource.Contains("sigops-reviewevents-") -or
    -not $strictAuthBrowserSource.Contains("signalops_review_decision_event_export_signature_v1") -or
    -not $strictAuthBrowserSource.Contains("signalops_review_decision_event_export_verification_v1") -or
    -not $strictAuthBrowserSource.Contains("signalops_review_decision_event_export_handoff_v1") -or
    -not $strictAuthBrowserSource.Contains("signalops_review_decision_event_export_handoff_manifest_v1") -or
    -not $strictAuthBrowserSource.Contains("signalops_review_decision_event_export_shipper_status_v1") -or
    -not $strictAuthBrowserSource.Contains("signalops-review-event-export-shipper-status") -or
    -not $strictAuthBrowserSource.Contains("deployment_owned_after_handoff") -or
    -not $strictAuthBrowserSource.Contains("sigops-reviewevents-hmac-") -or
    -not $strictAuthBrowserSource.Contains("sigops-paramdiff-tampered") -or
    -not $strictAuthBrowserSource.Contains("review-decision-events") -or
    -not $strictAuthBrowserSource.Contains("sigops-paramdiff-") -or
    -not $strictAuthBrowserSource.Contains("changed: 4") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsTickSimulationBoundary") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsDailyReviewSimulationBoundary") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsCommandSimulationBoundary") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsReviewDecisionSimulationBoundary") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsReviewDecisionVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("assertSignalOpsPaperOrderVisibleBoundary") -or
    -not $strictAuthBrowserSource.Contains("await assertSignalOpsReviewDecisionVisibleBoundary(reviewWindow, 'rq-approve')") -or
    -not $strictAuthBrowserSource.Contains("await assertSignalOpsPaperOrderVisibleBoundary(page, 'ORDER_SIGNALOPS_BROWSER_SMOKE')") -or
    -not $strictAuthBrowserSource.Contains("SignalOps forced tick") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps forced tick") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps daily review") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps manual command") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps candidate baseline review") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps review decision visible boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps paper order visible boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps review decision export handoff custody") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps review decisions")) {
  throw "SignalOps page is missing browser-visible core operation hooks or strict-auth high-risk write coverage"
}
$signalOpsReviewEmptyText = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5pqC5peg5aSN5qC46K6w5b2V44CC"))
$signalOpsHistoryMarkers = @(
  '<SignalHistoryPanel detail={detail} />',
  'function SignalHistoryPanel({ detail }: { detail: SignalDetail | null })',
  'const transitions = detail?.transitions || []',
  'const reviews = detail?.reviews || []',
  'reviews.slice(0, 6).map',
  $signalOpsReviewEmptyText
)
foreach ($marker in $signalOpsHistoryMarkers) {
  if (-not $signalOpsSource.Contains($marker)) {
    throw ("SignalOps selected-signal detail is missing lifecycle/review history linkage: " + $marker)
  }
}
$signalOpsDetailRaceMarkers = @(
  'const signalDetailRequestSeq = useRef(0)',
  'const requestSeq = signalDetailRequestSeq.current + 1',
  'signalDetailRequestSeq.current = requestSeq',
  'if (requestSeq !== signalDetailRequestSeq.current) return',
  'data-testid="signalops-selected-signal-detail"',
  'data-testid="signalops-selected-signal-id"'
)
foreach ($marker in $signalOpsDetailRaceMarkers) {
  if (-not $signalOpsSource.Contains($marker)) {
    throw ("SignalOps selected-signal detail is missing stale-response/race guard: " + $marker)
  }
}
if (-not $signalOpsSource.Contains("createResearchSignalOpsEvidence") -or
    -not $signalOpsSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $signalOpsSource.Contains("const researchIterationId = (searchParams.get('iteration_id') || '').trim()") -or
    -not $signalOpsSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $signalOpsSource.Contains("const isLinkedRunPending = Boolean(linkedRunId && currentRun?.runId !== linkedRunId)") -or
    -not $signalOpsSource.Contains("const bridgeRun = isLinkedRunPending ? null : currentRun") -or
    -not $signalOpsSource.Contains("if (isLinkedRunPending) throw new Error(") -or
    -not $signalOpsSource.Contains('${linkedRunId}`)') -or
    -not $signalOpsSource.Contains("source_run_id: bridgeRun.runId") -or
    $signalOpsSource.Contains("source_run_id: currentRun.runId") -or
    -not $signalOpsSource.Contains('data-testid="signalops-current-run-loading"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-current-run-symbol"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-current-run-id"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-research-evidence-context"') -or
    -not $signalOpsSource.Contains('testId="signalops-create-research-evidence"') -or
    -not $signalOpsSource.Contains('data-testid="signalops-research-evidence-boundary"') -or
    -not $signalOpsSource.Contains("evidence_usage={researchEvidenceNotice.evidenceUsage}") -or
    -not $signalOpsSource.Contains("supporting_only={String(researchEvidenceNotice.supportingOnly)}") -or
    -not $signalOpsSource.Contains("simulation_only={String(researchEvidenceNotice.simulationOnly)}") -or
    -not $signalOpsSource.Contains("is_real_trade={String(researchEvidenceNotice.isRealTrade)}") -or
    -not $signalOpsSource.Contains("strong_conclusion_allowed={String(researchEvidenceNotice.strongConclusionAllowed)} / SIM_*") -or
    -not $researchClientSource.Contains("createResearchSignalOpsEvidence") -or
    -not $researchClientSource.Contains("/research/signalops/signals/`${signalId}/evidence") -or
    -not $researchLoopsSource.Contains("function signalOpsEvidencePath") -or
    -not $researchLoopsSource.Contains("new URLSearchParams({ iteration_id: iteration.iteration_id })") -or
    -not $researchLoopsSource.Contains("function researchSignalOpsSignalId(iteration: ResearchIteration)") -or
    -not $researchLoopsSource.Contains("stringValue(iteration.metrics?.signalops_signal_id)") -or
    -not $researchLoopsSource.Contains("firstStringValue(iteration.metrics?.signalops_signal_ids)") -or
    -not $researchLoopsSource.Contains("String(item.source_type || '').toUpperCase() === 'SIGNALOPS'") -or
    -not $researchLoopsSource.Contains("const signalId = researchSignalOpsSignalId(iteration)") -or
    -not $researchLoopsSource.Contains("params.set('signal_id', signalId)") -or
    -not $researchLoopsSource.Contains('data-testid="research-open-signalops-evidence"') -or
    -not $strictAuthBrowserSource.Contains("runSignalOpsResearchEvidenceScenario") -or
    -not $strictAuthBrowserSource.Contains("runResearchSignalOpsDeepLinkScenario") -or
    -not $strictAuthBrowserSource.Contains("assertResearchSignalOpsEvidenceBoundary") -or
    -not $strictAuthBrowserSource.Contains("signalops-research-evidence-boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser SignalOps Research evidence") -or
    -not $strictAuthBrowserSource.Contains("SignalOps visible Research evidence boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research SignalOps selected deep link")) {
  throw "SignalOps is missing the Research evidence bridge from selected tick/signal context"
}
if (-not $agentDagSource.Contains('data-testid="agent-dag-page"') -or
    -not $agentDagSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $agentDagSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $agentDagSource.Contains("currentRun?.runId !== linkedRunId") -or
    -not $agentDagSource.Contains('data-testid="agent-dag-page-loading"') -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-page"') -or
    -not $agentDebateSource.Contains("const [searchParams] = useSearchParams()") -or
    -not $agentDebateSource.Contains("const linkedRunId = (searchParams.get('run_id') || '').trim()") -or
    -not $agentDebateSource.Contains("currentRun?.runId !== linkedRunId") -or
    -not $agentDebateSource.Contains('data-testid="agent-debate-page-loading"') -or
    -not $finalWriterSource.Contains('data-testid="final-writer-page"') -or
    -not $researchClosureBrowserSource.Contains("verifyTopBarCurrentRun") -or
    -not $researchClosureBrowserSource.Contains("verifyRunContextWritePageDirectLoad") -or
    -not $researchClosureBrowserSource.Contains("topbar current run id") -or
    -not $researchClosureBrowserSource.Contains("verifyCurrentRunDirectLoad(page, '/'") -or
    -not $researchClosureBrowserSource.Contains("verifyCurrentRunDirectLoad(page, '/signalops'") -or
    -not $researchClosureBrowserSource.Contains("verifyRunContextWritePageDirectLoad(page, '/case-library'") -or
    -not $researchClosureBrowserSource.Contains("verifyRunContextWritePageDirectLoad(page, '/knowledge'") -or
    -not $researchClosureBrowserSource.Contains("ok browser signalops direct-load current run id") -or
    -not $researchClosureBrowserSource.Contains("verifyCurrentRunDirectLoad(page, '/dag'") -or
    -not $researchClosureBrowserSource.Contains("agent-dag-selected-node-governance") -or
    -not $researchClosureBrowserSource.Contains("agent-dag-selected-node-evidence-strength") -or
    -not $researchClosureBrowserSource.Contains("ok browser dag selected node governance") -or
    -not $researchClosureBrowserSource.Contains("verifyCurrentRunDirectLoad(page, '/debate'") -or
    -not $researchClosureBrowserSource.Contains("verifyCurrentRunDirectLoad(page, '/final'")) {
  throw "current-run direct-load browser coverage is missing Dashboard, SignalOps, DAG, Debate, or Final page hooks and stale-run guards"
}
if (-not $researchClosureBrowserSource.Contains("collectStartRunBrowserResponses") -or
    -not $researchClosureBrowserSource.Contains("waitForCollectedStartRun") -or
    -not $researchClosureBrowserSource.Contains("waitForCurrentResearchIteration") -or
    -not $researchClosureBrowserSource.Contains("ok browser new-task start observed via live-run") -or
    -not $researchClosureBrowserSource.Contains("ok browser new-task live-run direct fallback") -or
    $researchClosureBrowserSource.Contains("if (!startRecord?.ok)") -or
    -not $researchClosureLiveSource.Contains("TIANYUAN_UV_CACHE_DIR") -or
    -not $researchClosureLiveSource.Contains('$env:UV_CACHE_DIR = $uvCacheDir')) {
  throw "Research closure browser smoke must collect New Task start responses, retain live-run fallback evidence, select current iterations, and use an isolated uv cache override"
}
if (-not $dashboardSource.Contains('data-testid="dashboard-research-closed-loop-evidence-strength"') -or
    -not $dashboardSource.Contains("function dashboardReviewStrength") -or
    -not $dashboardSource.Contains("'RESEARCH_GRADE'") -or
    -not $dashboardSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $dashboardSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'WARNING', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    -not $dashboardSource.Contains("dashboardReviewStrength(actionableStep?.evidence_strength || lastStep?.evidence_strength)") -or
    $dashboardSource.Contains("const evidenceStrength = actionableStep?.evidence_strength || lastStep?.evidence_strength || 'UNKNOWN'")) {
  throw "Dashboard Research closed-loop evidence strength must be review-gated to LOW before display"
}
if (-not $researchLoopsSource.Contains('data-testid="research-create-closed-loop-sample"') -or
    -not $researchLoopsSource.Contains('data-testid="research-create-sample-loop-from-latest-run"') -or
    -not $researchLoopsSource.Contains('data-testid="research-lab-workflow-role"') -or
    -not $researchLoopsSource.Contains('data-testid="research-lab-workflow-disabled-reason"') -or
    -not $researchLoopsSource.Contains('data-testid="research-closed-loop-secondary-disabled-reason"') -or
    -not $researchLoopsSource.Contains('data-testid="research-materialize-current-artifacts"') -or
    -not $researchLoopsSource.Contains('data-testid="research-attach-run-id"') -or
    -not $researchLoopsSource.Contains("setAttachRunId(currentIteration.linked_run_id ?? currentRunId ?? '')") -or
    -not $researchLoopsSource.Contains("linked_run_id: iteration.linked_run_id ?? currentRunId ?? undefined") -or
    $researchLoopsSource.Contains("setAttachRunId(currentRunId ?? currentIteration.linked_run_id ?? '')") -or
    $researchLoopsSource.Contains("linked_run_id: currentRunId ?? iteration.linked_run_id ?? undefined") -or
    -not $researchLoopsSource.Contains("writeDisabledReason={researchWriteDisabledReason}") -or
    -not $researchLoopsSource.Contains("title={writeDisabledReason || undefined}") -or
    -not $researchLoopsSource.Contains("useOperatorContext()") -or
    -not $researchLoopsSource.Contains("roleAllows(operator.role, 'researcher')") -or
    -not $researchLoopsSource.Contains($researchWorkflowPermissionText) -or
    -not $researchLoopsSource.Contains("ensureResearchLabWrite") -or
    -not $researchLoopsSource.Contains("createP2ClosedLoopSample") -or
    -not $researchLoopsSource.Contains('workflow-step-${step.key}-source') -or
    -not $researchLoopsSource.Contains('workflow-step-${step.key}-strength') -or
    -not $researchLoopsSource.Contains('workflow-step-${step.key}-missing') -or
    -not $researchLoopsSource.Contains('workflow-step-${step.key}-next') -or
    -not $researchLoopsSource.Contains('workflow-maturity-level') -or
    -not $researchLoopsSource.Contains('workflow-maturity-reason') -or
    -not $researchLoopsSource.Contains("function workflowReviewStrength") -or
    -not $researchLoopsSource.Contains("'RESEARCH_GRADE'") -or
    -not $researchLoopsSource.Contains("'PRIMARY_EVIDENCE_READY'") -or
    -not $researchLoopsSource.Contains("['UNKNOWN', 'SUPPORTING_ONLY', 'WEAK', 'WARN', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'") -or
    $researchLoopsSource.Contains("['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN'].includes(normalized)) return normalized") -or
    $researchLoopsSource.Contains("return fallbackStatus ? workflowReviewStrength(fallbackStatus) : 'UNKNOWN'") -or
    -not $researchLoopsSource.Contains("return fallbackStatus ? workflowReviewStrength(fallbackStatus) : 'LOW'") -or
    -not $researchLoopsSource.Contains("closedLoopStepReviewStrength(step)") -or
    -not $researchLoopsSource.Contains("const normalized = workflowReviewStrength(quality)") -or
    -not $researchLoopsSource.Contains("qualityLabel(workflowReviewStrength(item.quality))") -or
    -not $researchLoopsSource.Contains("function evidenceAuditDetail") -or
    -not $researchLoopsSource.Contains('reportedQuality=${qualityLabel(reported)} -> review_gate=${qualityLabel(workflowReviewStrength(item.quality))}') -or
    -not $researchLoopsSource.Contains("detail: evidenceAuditDetail(item)") -or
    $researchLoopsSource.Contains("if (['HIGH', 'PASS'].includes(normalized)) return 100") -or
    $researchLoopsSource.Contains("if (['HIGH', 'PASS'].includes(normalized)) return 'PASS'") -or
    -not $researchLoopsSource.Contains("function researchLoopEvidenceStrengthLabel") -or
    -not $researchLoopsSource.Contains("workflowReviewStrength(workflowState.evidence_strength)") -or
    -not $researchLoopsSource.Contains("].map((item) => workflowReviewStrength(item))") -or
    -not $researchLoopsSource.Contains("if (strengths.length === 0) return 'LOW") -or
    -not $researchLoopsSource.Contains("if (strengths.some((item) => item !== 'MEDIUM')) return 'LOW") -or
    -not $researchLoopsSource.Contains("if (strengths.every((item) => item === 'MEDIUM')) return 'MEDIUM") -or
    ($researchLoopsSource -match "function researchLoopEvidenceStrengthLabel[\s\S]*?return 'UNKNOWN") -or
    ($researchLoopsSource -match "function researchLoopEvidenceStrengthLabel[\s\S]*?return 'MISSING") -or
    $researchLoopsSource.Contains("['MEDIUM', 'WARN', 'SUPPORTING_ONLY'].includes(item)") -or
    -not $researchLoopsSource.Contains("function researchLoopBlockerLabel") -or
    -not $researchLoopsSource.Contains("function workflowCurrentStepLabel") -or
    -not $researchLoopsSource.Contains("function buildArtifactChainGovernance") -or
    -not $researchLoopsSource.Contains("Research artifact chain simulation-only boundary violated") -or
    -not $researchLoopsSource.Contains("artifactIds.requiresPatch && !artifactIds.patchId") -or
    -not $researchLoopsSource.Contains("artifactIds.patchId && !artifactIds.evaluationId") -or
    -not $researchLoopsSource.Contains("evidenceStrength: 'LOW'") -or
    $researchLoopsSource.Contains("evidenceStrength: boundaryBroken || !hasIds || !artifactIds.assetsComplete || (artifactIds.patchId && !artifactIds.evaluationId) ? 'LOW' : 'SUPPORTING_ONLY'") -or
    -not $researchLoopsSource.Contains("function buildVerdictOverrideAudit") -or
    -not $researchLoopsSource.Contains("metrics.verdict_gate_override !== true") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_blocking_reasons") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_quality_warnings") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_can_accept_feedback") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_evidence_usage") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_simulation_only") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_is_real_trade") -or
    -not $researchLoopsSource.Contains("verdict_gate_override_strong_conclusion_allowed") -or
    -not $researchLoopsSource.Contains("const evidenceStrength = 'LOW'") -or
    $researchLoopsSource.Contains("evidenceStrength: boundaryBroken || !canAcceptFeedback || blockingReasons.length > 0 || qualityWarnings.length > 0 ? 'LOW' : 'SUPPORTING_ONLY'") -or
    -not $researchLoopsSource.Contains("workflowState.blocking_reasons.length > 0") -or
    -not $researchLoopsSource.Contains("iteration.evidence_links.length === 0") -or
    -not $researchLoopsSource.Contains("workflowState.steps.some((step) => step.missing_items.length > 0)") -or
    -not $researchLoopsSource.Contains("const workflowBacktestStep = workflowState?.steps.find((step) => step.key === 'backtest')") -or
    -not $researchLoopsSource.Contains("const workflowBacktestId = workflowBacktestStatus === 'PASS'") -or
    -not $researchLoopsSource.Contains("const backtestId = workflowState ? workflowBacktestId : rawBacktestId") -or
    -not $researchLoopsSource.Contains('rawBacktestId ? `unverified: ${rawBacktestId}` : ''missing''') -or
    -not $researchLoopsSource.Contains("research-artifact-chain-governance-") -or
    -not $researchLoopsSource.Contains("research-artifact-chain-id-") -or
    -not $researchLoopsSource.Contains("research-artifact-chain-evidence-strength-") -or
    -not $researchLoopsSource.Contains("research-artifact-chain-blocker-") -or
    -not $researchLoopsSource.Contains("research-artifact-chain-next-action-") -or
    -not $researchLoopsSource.Contains("research-artifact-chain-simulation-boundary-") -or
    -not $researchLoopsSource.Contains("simulation_only={String(artifactGovernance.simulationOnly)} / is_real_trade={String(artifactGovernance.isRealTrade)} / evidence_usage={artifactGovernance.evidenceUsage} / strong_conclusion_allowed={String(artifactGovernance.strongConclusionAllowed)} / SIM_*") -or
    -not $researchLoopsSource.Contains("research-verdict-override-governance-") -or
    -not $researchLoopsSource.Contains("research-verdict-override-id-") -or
    -not $researchLoopsSource.Contains("research-verdict-override-evidence-strength-") -or
    -not $researchLoopsSource.Contains("research-verdict-override-blocker-") -or
    -not $researchLoopsSource.Contains("research-verdict-override-next-action-") -or
    -not $researchLoopsSource.Contains("research-verdict-override-simulation-boundary-") -or
    -not $researchLoopsSource.Contains("simulation_only={String(overrideAudit.simulationOnly)} / is_real_trade={String(overrideAudit.isRealTrade)} / evidence_usage={overrideAudit.evidenceUsage} / strong_conclusion_allowed={String(overrideAudit.strongConclusionAllowed)} / SIM_*") -or
    -not $researchLoopsSource.Contains("research-loop-governance-") -or
    -not $researchLoopsSource.Contains("research-loop-iteration-id-") -or
    -not $researchLoopsSource.Contains("research-loop-current-step-") -or
    -not $researchLoopsSource.Contains("research-loop-evidence-strength-") -or
    -not $researchLoopsSource.Contains("research-loop-blocker-") -or
    -not $researchLoopsSource.Contains("research-loop-next-action-") -or
    -not $researchLoopsSource.Contains("research-loop-simulation-boundary-") -or
    -not $researchLoopsSource.Contains("simulation_only={String(workflowState?.simulation_only ?? true)} / is_real_trade={String(workflowState?.is_real_trade ?? false)} / evidence_usage={workflowState?.evidence_usage ?? 'review_gate_only'} / strong_conclusion_allowed={String(workflowState?.strong_conclusion_allowed ?? false)} / SIM_*") -or
    -not $typesSource.Contains("missing_items: string[]") -or
    -not $typesSource.Contains("evidence_strength: 'MEDIUM' | 'LOW' | 'MISSING' | 'PENDING' | 'UNKNOWN' | (string & {})") -or
    -not $typesSource.Contains("source_timestamp: string") -or
    -not $typesSource.Contains("evidence_strength: string") -or
    -not $typesSource.Contains("evidence_usage: 'review_gate_only'") -or
    -not $typesSource.Contains("strong_conclusion_allowed: boolean") -or
    -not $typesSource.Contains("next_action_label: string") -or
    -not $typesSource.Contains("maturity_level: string") -or
    -not $typesSource.Contains("maturity_reasons: string[]") -or
    -not $researchClientSource.Contains("assertResearchWorkflowState") -or
    -not $researchClientSource.Contains("maturity_label") -or
    -not $researchClientSource.Contains("assertResearchWorkflowStep") -or
    -not $researchClientSource.Contains("assertStringArray(step.missing_items") -or
    -not $researchClientSource.Contains("source_timestamp") -or
    -not $researchClientSource.Contains("next_action_label") -or
    -not $researchClosureBrowserSource.Contains("research-create-closed-loop-sample") -or
    -not $researchClosureBrowserSource.Contains("assertP2ClosedLoopReviewBoundary") -or
    -not $researchClosureBrowserSource.Contains("step.strong_conclusion_allowed !== false") -or
    -not $researchClosureBrowserSource.Contains("usage === 'primary_evidence'") -or
    -not $researchClosureBrowserSource.Contains("research attach run defaults to linked run id") -or
    -not $researchClosureBrowserSource.Contains("ok browser research one-click closed-loop sample") -or
    -not $strictAuthBrowserSource.Contains("runResearchClosedLoopScenario") -or
    -not $strictAuthBrowserSource.Contains("retrying SPA route without reloading auth state") -or
    -not $strictAuthBrowserSource.Contains("Research Lab closed-loop sample creation") -or
    -not $strictAuthBrowserSource.Contains("research-materialize-current-artifacts") -or
    -not $strictAuthBrowserSource.Contains("/api/research/iterations/") -or
    -not $strictAuthBrowserSource.Contains("/artifacts/materialize") -or
    -not $strictAuthBrowserSource.Contains("Research Lab artifact materialization") -or
    -not $strictAuthBrowserSource.Contains("Research Lab visible artifact chain boundary") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research Lab artifact materialization") -or
    -not $strictAuthBrowserSource.Contains("Research Lab governance summary did not expose the current weak-link step") -or
    -not $strictAuthBrowserSource.Contains("Research Lab visible workflow boundary") -or
    -not $strictAuthBrowserSource.Contains("Research Lab visible verdict override boundary") -or
    -not $strictAuthBrowserSource.Contains("knowledge_version_id") -or
    -not $strictAuthBrowserSource.Contains("ok strict-auth browser Research Lab closed-loop sample")) {
  throw "ResearchLoopsPage one-click closed-loop sample entry is missing UI or browser-smoke coverage"
}
$scenarioIds = [regex]::Matches($scenarioTemplatesSource, "id:\s*'([^']+)'") | ForEach-Object { $_.Groups[1].Value }
foreach ($scenarioId in $scenarioIds) {
  $escapedScenarioId = [regex]::Escape($scenarioId)
  if ($mockScenariosSource -notmatch $escapedScenarioId) {
    throw "Scenario template $scenarioId has no local mock fixture or alias"
  }
}
$mockDagOrderMatch = [regex]::Match($mockScenariosSource, "const\s+STANDARD_DAG_ORDER\s*=\s*\[(?<body>[\s\S]*?)\]")
if (-not $mockDagOrderMatch.Success) {
  throw "Mock scenarios are missing STANDARD_DAG_ORDER"
}
$mockDagOrderBody = $mockDagOrderMatch.Groups["body"].Value
foreach ($marker in @("'orchestrator'", "'data_reliability_engine'", "'guardrail_hub'", "'quant_core'", "'execution'", "'anti_conclusion'", "'signalops'", "'final_writer'")) {
  if (-not $mockDagOrderBody.Contains($marker)) {
    throw ("Mock STANDARD_DAG_ORDER is missing canonical active node: " + $marker)
  }
}
foreach ($legacyMarker in @("'data_engine'", "'dvg_gate'", "'risk_firewall'", "'trade_micro'", "'quant_engine'")) {
  if ($mockDagOrderBody.Contains($legacyMarker)) {
    throw ("Mock STANDARD_DAG_ORDER must not contain legacy active node: " + $legacyMarker)
  }
}
foreach ($marker in @("guardrailHub:", "triggerNode: 'guardrail_hub'", "dvg_gate / risk_firewall / trade_micro")) {
  if (-not $mockScenariosSource.Contains($marker)) {
    throw ("Mock scenarios are missing canonical guardrail compatibility marker: " + $marker)
  }
}
foreach ($marker in @("guardrail_hub: 3", "dvg_gate: 3", "risk_firewall: 3", "trade_micro: 3", "quant_core: 4")) {
  if (-not $dashboardSource.Contains($marker)) {
    throw ("Dashboard DAG ordering is missing canonical guardrail ordering marker: " + $marker)
  }
}
$commonFiles = Get-ChildItem -LiteralPath (Join-Path $frontendRoot "src\components\common") -File -Filter "*.tsx"
$sourceFiles = Get-ChildItem -LiteralPath (Join-Path $frontendRoot "src") -Recurse -File | Where-Object { $_.Extension -in @(".ts", ".tsx") }
foreach ($commonFile in $commonFiles) {
  $componentName = [System.IO.Path]::GetFileNameWithoutExtension($commonFile.Name)
  $hasImporter = $false
  foreach ($sourceFile in $sourceFiles) {
    if ($sourceFile.FullName -eq $commonFile.FullName) {
      continue
    }
    $source = [System.IO.File]::ReadAllText($sourceFile.FullName, [System.Text.Encoding]::UTF8)
    if (
      $source.Contains("../common/$componentName") -or
      $source.Contains("./common/$componentName") -or
      $source.Contains("./components/common/$componentName") -or
      $source.Contains("./$componentName")
    ) {
      $hasImporter = $true
      break
    }
  }
  if (-not $hasImporter) {
    throw "Common component $componentName has no active non-self import"
  }
}
if ($bottomRedirect.Count -eq 0) {
  throw "routeManifest is missing /bottom-research -> /quant-core legacy redirect"
}
if ($quantEngineRedirect.Count -eq 0) {
  throw "routeManifest is missing /quant-engine -> /quant-core legacy redirect"
}
if ($scenarioRedirect.Count -eq 0) {
  throw "routeManifest is missing /scenario -> /quant-core legacy redirect"
}
if (-not ($navPaths -contains "/guardrail-hub")) {
  throw "routeManifest navGroups must expose /guardrail-hub as the unified guardrail entry"
}
if (-not ($navPaths -contains "/data-reliability")) {
  throw "routeManifest navGroups must expose /data-reliability as the unified data reliability entry"
}
foreach ($route in @("/data-health", "/data-engine")) {
  if ($navPaths -contains $route) {
    throw "Removed data reliability legacy route $route must not appear as a primary sidebar navigation item"
  }
  if (@($manifest.legacyRoutes) -contains $route) {
    throw "Removed data reliability legacy route $route must not remain in routeManifest legacyRoutes"
  }
  if (@($manifest.redirects | Where-Object { $_.from -eq $route }).Count -gt 0) {
    throw "Removed data reliability legacy route $route must not redirect to the new module"
  }
  if ($appSource.Contains('path="' + $route + '"')) {
    throw "App must not mount removed data reliability legacy route $route"
  }
}
foreach ($route in $guardrailLegacyRoutes) {
  if ($navPaths -contains $route) {
    throw "Guardrail legacy route $route must not appear as a primary sidebar navigation item"
  }
  if (-not (@($manifest.legacyRoutes) -contains $route)) {
    throw "routeManifest legacyRoutes is missing guardrail compatibility route $route"
  }
}
if ($badgeImportHits.Count -lt 5) {
  throw "Badge shared component import evidence is unexpectedly low: $($badgeImportHits.Count)"
}
if ($cardImportHits.Count -lt 5) {
  throw "Card shared component import evidence is unexpectedly low: $($cardImportHits.Count)"
}
if ($materialImportHits.Count -lt 12) {
  throw "Material shared data component import evidence is unexpectedly low: $($materialImportHits.Count)"
}
if ($appSource -notmatch "components/common/LoadingState" -or $appSource -notmatch "LoadingState") {
  throw "App Suspense fallback is not wired to common LoadingState"
}
if ($errorBoundarySource -notmatch "from './ErrorState'" -or $errorBoundarySource -notmatch "ErrorState") {
  throw "ErrorBoundary is not wired to common ErrorState"
}
if (-not $appShellSource.Contains("material-app-shell") -or
    -not $appShellSource.Contains("material-page-frame") -or
    -not $sidebarSource.Contains("w-[68px]") -or
    -not $sidebarSource.Contains("sr-only") -or
    -not $sidebarSource.Contains("sidebar-guardrail-hub") -or
    -not $sidebarSource.Contains("LEGACY_GUARDRAIL_PATHS") -or
    $sidebarSource.Contains("lg:w-72") -or
    $sidebarSource.Contains("collapsed") -or
    -not $topBarSource.Contains("institution-command-bar") -or
    -not $topBarSource.Contains("institution-secondary-nav") -or
    -not $topBarSource.Contains("institution-nav-pill-active") -or
    -not $topBarSource.Contains("simulationOnly=true") -or
    -not $topBarSource.Contains("isRealTrade=false")) {
  throw "Institutional light shell/navigation contract is missing or has regressed"
}
$materialContracts = @(
  "export function MetricTile",
  "export function TableShell",
  "export function InlineSparkline",
  "export function FactorBarStack",
  "export function MatrixHeatmap",
  "export function SourceFreshnessPanel",
  "export function EvidenceLedger",
  "institution-progress-track",
  "institution-progress-fill"
)
foreach ($marker in $materialContracts) {
  if (-not $materialSource.Contains($marker)) {
    throw ("Material institutional data component is missing marker: " + $marker)
  }
}
$cssContracts = @(
  "--institution-data-accent",
  "--institution-data-accent-soft",
  "--institution-radius-sm",
  "--institution-radius-md",
  ".institution-command-bar",
  ".institution-secondary-nav",
  ".institution-nav-pill",
  ".institution-table",
  ".institution-progress-track",
  ".institution-chip-data"
)
foreach ($marker in $cssContracts) {
  if (-not $indexCssSource.Contains($marker)) {
    throw ("Institutional CSS token or utility is missing marker: " + $marker)
  }
}
if ($indexCssSource.Contains("linear-gradient(180deg")) {
  throw "Institutional light theme should not restore the old dark/gradient cockpit shell"
}
if (-not $quantCoreSource.Contains("SourceFreshnessPanel") -or
    -not $quantCoreSource.Contains("FactorBarStack") -or
    -not $quantCoreSource.Contains("MatrixHeatmap") -or
    -not $quantCoreSource.Contains("InlineSparkline") -or
    -not $backendStatusSource.Contains("EvidenceLedger") -or
    -not $backendStatusSource.Contains("SourceFreshnessPanel") -or
    -not $backendStatusSource.Contains("TableShell") -or
    -not $portfolioSource.Contains("MetricTile") -or
    -not $portfolioSource.Contains("TableShell") -or
    -not $signalOpsSource.Contains("EvidenceLedger") -or
    -not $signalOpsSource.Contains("FactorBarStack") -or
    -not $researchLoopsSource.Contains("MatrixHeatmap") -or
    -not $researchLoopsSource.Contains("EvidenceLedger")) {
  throw "Key quantitative pages are missing the shared institutional data presentation components"
}
$pageSurfaceFiles = @($tsxFiles | Where-Object { $_.Name -match "(Page|Console)\.tsx$" })
foreach ($pageFile in $pageSurfaceFiles) {
  $pageSource = Get-Content -LiteralPath $pageFile.FullName -Raw -Encoding UTF8
  $relativePage = Resolve-Path -LiteralPath $pageFile.FullName -Relative
  $hasMaterialDataPresentation = (
    $pageSource.Contains("from '../common/Material'") -or
    $pageSource.Contains("from './common/Material'") -or
    $pageSource.Contains("ResearchMetricCard")
  )
  if (-not $hasMaterialDataPresentation) {
    throw "Page surface is missing shared Material data presentation evidence: $relativePage"
  }
  if ($pageSource -match '<table className="(?!institution-table)') {
    throw "Page surface has a table outside the institutional table system: $relativePage"
  }
  if ($pageSource -match 'min-w-full divide-y|w-full text-sm|min-w-full text-left') {
    throw "Page surface has legacy table utility classes instead of institution-table: $relativePage"
  }
}
if (-not $packageSource.Contains('"smoke:frontend:responsive"') -or
    -not $packageSource.Contains('scripts\\smoke-frontend-responsive.mjs')) {
  throw "package.json is missing the frontend responsive smoke entrypoint"
}
$responsiveSmokeMarkers = @(
  "1440",
  "1280",
  "768",
  "390",
  "collectRoutes(manifest)",
  "routeManifest",
  "legacyRoutes",
  "unexpected document horizontal overflow",
  "institution-command-bar",
  "institution-secondary-nav",
  "material-table-shell",
  "FRONTEND_RESPONSIVE_ROUTES",
  "FRONTEND_RESPONSIVE_ROUTE_LIMIT"
)
foreach ($marker in $responsiveSmokeMarkers) {
  if (-not $frontendResponsiveSmokeSource.Contains($marker)) {
    throw ("frontend responsive smoke is missing marker: " + $marker)
  }
}
$frontendGuideResponsiveMarkers = @(
  "smoke:frontend:responsive",
  "1440x1000",
  "1280x900",
  "768x1024",
  "390x844",
  "KLineCurve",
  "VolumeBar",
  "legacyRoutes",
  "PR Definition of Done"
)
foreach ($marker in $frontendGuideResponsiveMarkers) {
  if (-not $frontendRedesignGuideSource.Contains($marker)) {
    throw ("FRONTEND_REDESIGN_GUIDE is missing redesign acceptance marker: " + $marker)
  }
}
if (-not $testingGuideSource.Contains("smoke:frontend:responsive") -or
    -not $testingGuideSource.Contains("visual/responsive pass") -or
    -not $testingGuideSource.Contains("1440x1000") -or
    -not $testingGuideSource.Contains("390x844")) {
  throw "TESTING_GUIDE is missing the frontend responsive acceptance entrypoint"
}
if (-not $testingGuideSource.Contains("frontend responsive smoke") -or
    -not $testingGuideSource.Contains("-SkipResponsiveSmoke")) {
  throw "TESTING_GUIDE is missing the default premerge responsive smoke contract"
}
if (-not $developmentGuideSource.Contains("validate:premerge") -or
    -not $developmentGuideSource.Contains("frontend responsive smoke") -or
    -not $developmentGuideSource.Contains("strict-auth browser matrix")) {
  throw "DEVELOPMENT_GUIDE is missing the default premerge responsive smoke contract"
}
if (-not $projectAssessmentSource.Contains("validate:premerge") -or
    -not $projectAssessmentSource.Contains("frontend responsive smoke") -or
    -not $projectAssessmentSource.Contains("strict-auth browser matrix")) {
  throw "PROJECT_DEVELOPMENT_ASSESSMENT is missing the default premerge responsive smoke contract"
}
if (-not $quantImprovementPlanSource.Contains("validate:premerge") -or
    -not $quantImprovementPlanSource.Contains("frontend responsive smoke") -or
    -not $quantImprovementPlanSource.Contains("strict-auth browser matrix")) {
  throw "QUANT_SYSTEM_IMPROVEMENT_PLAN is missing the default premerge responsive smoke contract"
}
Write-Output "ok frontend weak-link contracts"

if (-not (Test-Path -LiteralPath $distIndex)) {
  throw "frontend/dist is missing. Run npm.cmd run build before smoke routes."
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$node = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $node) {
  $node = Get-Command node -ErrorAction SilentlyContinue
}
if (-not $node) {
  throw "node was not found on PATH."
}

$outLog = Join-Path $logDir "frontend-smoke.out.log"
$errLog = Join-Path $logDir "frontend-smoke.err.log"
$env:PORT = [string]$Port
$env:HOST = "127.0.0.1"
$process = Start-Process -FilePath $node.Source -ArgumentList "preview-dist.cjs" -WorkingDirectory $frontendRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

try {
  $baseUrl = "http://127.0.0.1:$Port"
  $ready = $false
  for ($i = 0; $i -lt 40; $i++) {
    try {
      $response = Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/" -TimeoutSec 2
      if ($response.StatusCode -eq 200) {
        $ready = $true
        break
      }
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  if (-not $ready) {
    throw "frontend preview did not become ready on $baseUrl"
  }

  foreach ($route in $Routes) {
    $uri = "$baseUrl$route"
    $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -TimeoutSec 5
    if ($response.StatusCode -ne 200) {
      throw "route $route returned HTTP $($response.StatusCode)"
    }
    if ($response.Content -notmatch 'id="root"') {
      throw "route $route did not return the React root document"
    }
    Write-Output "ok $route"
  }

  $assetText = ""
  Get-ChildItem -LiteralPath (Join-Path $frontendRoot "dist\assets") -Filter "*.js" -ErrorAction SilentlyContinue | ForEach-Object {
    $assetText += [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
  }
  if ($Routes -contains "/signalops") {
    foreach ($text in $SignalOpsRequiredText) {
      if (-not $assetText.Contains($text)) {
        throw "SignalOps built assets are missing required text: $text"
      }
    }
    Write-Output "ok /signalops required text"
  }
} finally {
  if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force
  }
}
