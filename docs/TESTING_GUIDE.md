# 测试指南

## 当前常用命令

从项目根目录运行（Run from the repository root）。

### 当前推荐基线

```powershell
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd run audit:baseline
npm.cmd run test:backend
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
npm.cmd run chaos:isolated
npm.cmd run smoke:signalops-auto-paper-chain
npm.cmd run smoke:research-closure
```

### 全页面数据呈现 smoke

Large frontend refactors must keep this command in the acceptance set:

```powershell
npm.cmd run smoke:frontend
```

The smoke now validates every accessible page/console surface, not only the shell. It checks `routeManifest.json` routes, redirects, and `legacyRoutes`, requires shared Material data-presentation evidence on every `*Page.tsx` / `*Console.tsx`, requires `institution-table` for page tables, and blocks legacy dark cockpit shells, decorative gradients, wide narrative sidebars, and old table utility classes from returning. This is the fast guard for the approved light institutional quantitative UI before browser smoke.

### 前端重构视觉与响应式验收

Large frontend refactors also need a visual/responsive pass against `docs/FRONTEND_REDESIGN_GUIDE.md` before final acceptance. The static smoke proves route and component contracts; this pass proves layout quality:

| Viewport | Acceptance focus |
| --- | --- |
| `1440x1000` | Approved desktop density, command bar, secondary nav, KPI strip, chart/table balance |
| `1280x900` | Laptop fit, no unintended body horizontal scroll, compact controls still readable |
| `768x1024` | Tablet stacking, primary filters and review/status actions remain visible |
| `390x844` | Mobile text wrapping, no overlap, long tables contained in table-level scroll or folded sections |

Record the result in the delivery note or PR checklist. If screenshots are captured, keep them free of secrets, real account identifiers, broker credentials, and direct personal data. A failure in any viewport blocks visual acceptance unless the risk is explicitly scoped and accepted.

Minimum command set for this visual pass remains:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:frontend:responsive
```

`smoke:frontend:responsive` starts the built frontend preview and checks every `routeManifest` route plus legacy redirect and `legacyRoutes` entry in the fixed `1440x1000`, `1280x900`, `768x1024`, and `390x844` viewport matrix. For local diagnosis only, narrow it with `FRONTEND_RESPONSIVE_ROUTES=/global-market,/portfolio` or `FRONTEND_RESPONSIVE_ROUTE_LIMIT=5`; final acceptance should run the full matrix.

### 隔离破坏性验收

Use this after large UI/API refactors and before final acceptance when the requirement includes destructive or chaos-style validation:

```powershell
npm.cmd run chaos:isolated
```

The command is intentionally isolated: it builds the frontend, runs concurrent route pressure against `frontend/dist`, runs destructive backend boundary tests for strict auth, malformed/oversized portfolio imports, SQLite lock fallback, stream timeout/auth behavior, and SignalOps simulation-only boundaries, then runs the strict-auth browser matrix by default. It writes under `.tmp/chaos-validation-*` and existing smoke temp paths, and fails if `storage\tianyuan_quant.db` changes during the run.

For focused local diagnosis only:

```powershell
.\scripts\chaos-validation.ps1 -SkipStrictAuthMatrix
```

Do not use the skipped variant as final acceptance for a full-system refactor.

### Shared configClient frontend guard checks

Use this focused set when touching `frontend/src/api/configClient.ts`, Backend Tuning, Settings, `frontend/src/components/config/ConfigVersionsPage.tsx`, `/api/config/current`, `/api/config/schema`, `/api/config/validate`, `/api/config/drafts`, `/api/config/runtime`, `/api/config/rollback`, `/api/config/versions`, or `/api/config/external-restore`:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:strict-auth-browser:platform
```

`smoke:frontend` checks that `configClient` keeps response guards for current profile, schema rows, policy checks, draft creation/apply, runtime patch, rollback, Config Versions rows, rollback policy, approval gate, `required_secret_refs`, `effective_scope`, and approved restore result payloads before Backend Tuning, Settings, or `/config-versions` store them in page state. Config Versions approved restore must also keep the admin-only role hook, visible disabled reason, handler short-circuit, button title, and governed modal controls. The platform strict-auth browser scenario exercises the approved-restore modal, Bearer-auth request body, and multi-surface Agent Runtime fixture after those guards run.

### Agent Runtime frontend guard checks

Use this focused set when touching `frontend/src/api/agentRuntimeClient.ts`, Agent Runtime, New Task default LLM profile status, Backend Status adapter loading, Data Reliability Engine adapter loading, Settings market-data adapter config, `/api/agents/runtime`, `/api/agents/runtime/test`, `/api/agents/runtime/validate-config`, `/api/agents/runtime/market-data/test`, `/api/agents/market-data/adapters`, `/api/agents/market-data/adapters/config`, or `/api/agents/market-data/status`:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:strict-auth-browser:platform
npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin
```

Settings data-source config is part of the same focused set: `configClient` must keep `assertDataSourcesConfig()` and `assertDataSourceTestResult()` plus `.then(...)` wiring for `/agents/data-sources` and `/agents/data-sources/${key}/test`. The guard validates public token-set/mask metadata and per-source/per-API result rows only; it must not require or expose plaintext tokens. Settings role-boundary coverage requires `/settings` to keep `useOperatorContext()`, `roleAllows(operator.role, 'admin')`, `roleAllows(operator.role, 'operator')`, `settings-data-source-config-role`, `settings-data-source-config-disabled-reason`, `settings-data-source-check-role`, `settings-data-source-check-disabled-reason`, data-source token/save/test/toggle hooks, adapter refresh/check/config-save hooks, handler-level `guardSettingsConfigWrite()` and `guardSettingsActiveCheck()` short-circuits, and disabled write/check controls guarded by `smoke:frontend`. Run `smoke:strict-auth-browser:platform` sequentially after `build`, not concurrently with `build`, so the preview does not read a half-rewritten `frontend/dist`.

`smoke:frontend` checks that `agentRuntimeClient` keeps response guards for runtime config, LLM profiles, market-data profiles, LLM/market-data `base_url_security`, agent deployments, LLM validation/test results, market-data test results, adapter health rows, adapter config rows, and market-data status matrix payloads. It also checks the frontend no-direct-trade deployment guard for `allow_trade_action` and `final_decision_cap`, plus the Agent Runtime page markers that show server egress security and configured allowlist hosts for both LLM and Market Data profiles. Agent Runtime admin-write coverage requires `/settings` to keep `useOperatorContext()`, `roleAllows(operator.role, 'admin')`, `agent-runtime-write-role`, `agent-runtime-write-disabled-reason`, profile save/apply/validate/test hooks, market-data save/test hooks, runtime routing save/apply hooks, disabled write controls, and handler-level `guardRuntimeWrite()` short-circuits guarded by `smoke:frontend`. The platform strict-auth browser scenario covers Backend Status/Data Reliability/Settings adapter consumption, while portfolio-live-plugin covers New Task default runtime read before Live Run and Plugin lifecycle checks continue.

### MFE/MAE 量化核心链路 smoke

Use this focused smoke when touching the MFE/MAE path risk filter, MFE/MAE Path Research evaluation, or the `/quant-core` display contract:

```powershell
npm.cmd run smoke:mfe-mae-quant-core
```

It runs `backend\tests\test_mfe_mae_quant_core_chain.py` through the repository backend test wrapper. The smoke constructs verified LIVE daily proxy payloads, runs `normalize_run_artifacts()`, checks `coreInterpretation.pathRiskFilter` and final-context synchronization, verifies fixed risk-curve buckets and proxy field naming, and proves high path risk only adds read-only interpretation flags/conflicts. It also checks `mfeMaeResearch.modelDiagnostics.mfeMaePathRiskEvaluation` and `conditionalQuantileEvaluation` use labeled historical windows while excluding `UNLABELED_NOWCAST` from Rank IC, coverage, and folds; `bottomResearch` is only asserted as a legacy mirror when needed for old runs.

The backend wrapper keeps pytest cache/basetemp under repo `.tmp` for traceability, but sends `TEMP` / `TMP` to a system temp subdirectory outside the OneDrive workspace so `uv` Windows trampoline executables are not blocked by repo sync or file scanners.

### SignalOps auto-paper chain smoke

Use this focused smoke when touching SignalOps automation, module evidence, paper orders, or the simulated portfolio snapshot bridge:

```powershell
npm.cmd run smoke:signalops-auto-paper-chain
```

It verifies a forced auto-paper tick computes deterministic module evidence first, keeps live trading disabled, creates only `SIM_*` orders, and persists a `SIGNALOPS_SIM` portfolio snapshot with at least one `holding_positions` row for downstream portfolio/research closure checks.

Frontend SignalOps boundary guards are also covered by `npm.cmd run smoke:frontend`: `signalopsClient` must keep the auto-paper config/status, forced tick, daily review, manual command, review-decision, event-export, verification, and handoff calls on `request<unknown>()` before their `.then(...)` guards run. Those guards must reject non-simulation automation modules, enabled live order routers, missing live-disabled boundaries, or real-trade-looking payloads before `/signalops` stores them in page state.

SignalOps lifecycle and paper-mode client coverage is part of the same static smoke. `signalopsClient` must also keep signal rows, selected-signal detail, transitions, reviews, paper portfolios, paper orders, paper positions, and agent simulation cases on `request<unknown>()` before their runtime guards run. Paper portfolio, paper order, and simulation-case responses must preserve `simulation_only=true` and `is_real_trade=false` before `/signalops` or Case Library stores them in render state.

Run `npm.cmd run smoke:strict-auth-browser:signalops` after changing these guards or their fixtures. The browser fixture must include backend-equivalent auto-paper defaults such as `trading_date`, `case_ids`, `evidence_links`, `cleaned_records`, `review_decisions`, `decision_tree_reviews`, `warnings`, and live-module `simulation_only=true`; otherwise the client guard should reject the mock instead of letting `/signalops` render incomplete runtime data.

SignalOps -> Research evidence bridge focused checks:

```powershell
npm.cmd run test:backend -- backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-signalops-research-evidence
npm.cmd run test:backend -- backend\tests\test_research_store.py::test_signalops_evidence_route_returns_404_for_missing_signal backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-signalops-evidence-missing
npm.cmd run test:backend -- backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-research-evidence-bridges
```

Use these when touching `POST /api/research/signalops/signals/{signal_id}/evidence`, `createResearchSignalOpsEvidence()`, or the `/signalops?iteration_id=...` Research context. The checks prove SignalOps tick evidence reaches `ResearchVerdictInputs` as supporting-only evidence while preserving `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false`, and that a missing SignalOps signal returns route-level `404` without attaching partial Research evidence.

### Phase 1-3 closure and worker checks

Use this bundle for changes touching Research Lab workflow state, P2 closed-loop samples, portfolio-to-task routing, browser closure smoke, or SQLite analysis jobs:

```powershell
npm.cmd run validate:phase1-3
```

The phase gate prints `git status --short`, runs `audit:baseline`, module participation validation, frontend typecheck/lint/build, static frontend smoke, and `smoke:research-closure:browser`. For focused failure isolation, run the same pieces manually:

```powershell
npm.cmd run audit:baseline
git status --short
npm.cmd run validate:module-participation
npm.cmd run test:backend -- backend\tests\test_research_store.py backend\tests\test_closed_loop_sample.py backend\tests\test_analysis_job_sqlite.py backend\tests\test_analysis_workflow.py -q
npm.cmd run smoke:analysis-worker
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
npm.cmd run smoke:research-closure:browser
```

`validate:module-participation` aggregates the existing SignalOps auto-paper chain, MFE/MAE Quant Core chain, isolated closed-loop participation smoke, analysis worker smoke, and focused Portfolio/Backtest/Research/Evaluation/Plugin/Data Reliability/observability backend tests. Use it when the risk is cross-module participation rather than a single page or API route.

`smoke:research-closure:browser` expects `frontend/dist` to exist, so run `npm.cmd run build` first. It starts an isolated backend plus a static frontend preview with `/api` proxying, points `TIANYUAN_QUANT_DB_URL` at a unique `.tmp/research-closure-smoke-*.db`, requires Playwright, uses worker queue mode for the UI-created live run, clicks `/portfolio -> /new-task -> /live-run -> /research-lab`, and verifies visible snapshot/run/backtest/research/case/knowledge/evaluation/knowledge-version IDs plus blocking reasons. The wrapper always creates a temp portfolio sample and checks the temporary DB has `portfolio_snapshots > 0` and `holding_positions > 0`.

Backup smoke:

```powershell
npm.cmd run smoke:db-backup-restore
npm.cmd run smoke:db-offhost-backup
npm.cmd run smoke:storage-offhost-restore
```

`smoke:db-backup-restore` creates a temporary SQLite source database, runs the normal backup helper, validates restore dry-run, force-restores into a temporary target, and verifies SQLite integrity. `smoke:db-offhost-backup` creates a temporary SQLite source database, runs the normal backup helper, copies the backup and manifest into a separate simulated off-host directory, and verifies the copied backup checksum against the manifest. `smoke:storage-offhost-restore` creates a temporary backend-storage tree with runtime JSON, run/plugin artifacts, ops logs, secret vault, and key file, copies it to a simulated off-host directory, restores it to a separate temp directory, and verifies every file by SHA-256 manifest. These commands write only under `.tmp` and are not production backup substitutes.

Strict-auth browser smoke:

```powershell
npm.cmd run build
npm.cmd run smoke:strict-auth-browser
```

For faster isolation after a focused change, the strict-auth browser smoke can also run independently by scenario group:

```powershell
npm.cmd run smoke:strict-auth-browser:platform
npm.cmd run smoke:strict-auth-browser:signalops
npm.cmd run smoke:strict-auth-browser:research-backtest
npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin
npm.cmd run smoke:strict-auth-browser:matrix
```

These focused commands start the same isolated backend/frontend and still prove strict-mode `/api/metrics` rejection plus tab-scoped token application. `smoke:strict-auth-browser:matrix` runs all focused groups sequentially with separated port ranges and is the CI/pre-merge-friendly entrypoint when full scenario isolation matters. `smoke:strict-auth-browser` remains the full default chain and is equivalent to `STRICT_AUTH_BROWSER_SCENARIO=all`.

Local pre-merge gate:

```powershell
npm.cmd run validate:premerge
```

`validate:premerge` runs the default backend regression set, isolated closed-loop participation smoke, analysis worker smoke, frontend typecheck, lint, build, static frontend smoke, frontend responsive smoke, and `smoke:strict-auth-browser:matrix`. Use `scripts\pre-merge-validation.ps1 -SkipClosedLoopParticipation`, `-SkipAnalysisWorkerSmoke`, `-SkipResponsiveSmoke`, or `-SkipStrictAuthMatrix` only for quick local iteration, not for broad release acceptance.

`smoke:strict-auth-browser` starts an isolated backend with `API_AUTH_MODE=strict`, a one-run admin token, a temp SQLite DB, and a static frontend preview. The browser first verifies a protected read (`/api/metrics`) returns 401 without a token, then applies the token through `/backend`, checks `/config-versions` approved restore modal payload/auth behavior across `agent_runtime:data_sources_config` and `agent_runtime:market_data_adapter_config`, checks `/signalops` compact config/status requests with `Authorization: Bearer ...`, verifies the SignalOps simulation-only/no-real-trade boundary window, and drives deterministic browser-level SignalOps forced-tick, daily-review, manual-command, review-decision, and Research evidence POSTs to prove page interaction, Bearer transport, supporting-only Research evidence, and simulation-only rendering without depending on external market latency. It then creates a P2 closed-loop sample and opens `/dag?run_id=...` plus `/debate?run_id=...` to verify Agent DAG/Debate linked-run LLM evidence, clicks Agent DAG ReactFlow zoom-in and fit-view controls, drags the read-only ReactFlow pane to verify pan behavior, clicks the `orchestrator` node, keyboard-selects a second real run node, and asserts the selected-node detail panel renders node id, LLM status, profile, and token evidence after each selection. Dedicated `RUN_DAG_FAILURE_BROWSER_SMOKE` and `RUN_DAG_STATE_MATRIX_BROWSER_SMOKE` fixtures also verify degraded/failed rows, source counts, and selected-node `data-source` classification for LLM, LLM degraded, LLM failed, rule engine, read-only plugin observation, and mock/sample output without changing backend state. The same flow navigates inside the SPA to `/portfolio`, first uploads a malformed CSV to verify Bearer-auth multipart transport, structured `NO_VALID_HOLDING_ROWS` diagnostics, failed import job id, and visible `portfolio-import-error-detail`, then uploads Eastmoney-style CSV, Huatai/HTSC TSV, Guotai Junan/GTJA CSV, Futu/Moomoo CSV, and Tiger CSV fixtures through the active import input, asserts `/api/portfolio/imports` uses Bearer auth and multipart `FormData`, verifies imported broker-template metadata for all fixtures is visible, then creates a sample portfolio with `Authorization: Bearer ...`, creates and starts an analysis run from `/new-task`, verifies `/live-run` opens its EventSource stream with the scoped `api_key` query token, then uses terminal fixtures to prove `STREAM_TIMEOUT` and `RUN_STALE_RECOVERED` SSE events remain visible as `FAIL` after the run-detail refresh and do not show a reconnect/error banner. Backend stream regressions also cover SSE stale/cancelled `done` behavior and WebSocket `STALE` / `CANCELLED` status-specific terminal events, `RUN_REMOVED`, and `STREAM_TIMEOUT`. This is the runtime counterpart to the strict-auth backend tests, SignalOps simulation-boundary smoke, and the frontend static token-bridge smoke.

The strict-auth browser smoke also verifies Backtest artifact download, parameter-scan validation evidence, retained scan history, async job handoff, handoff custody sidecar status, and the Research -> Backtest -> verdict-inputs round trip. During the Backtest sample run it clicks `backtest-experiment-package-download`, asserts `/api/research/backtest/runs/{run_id}/experiment-package` uses Bearer auth, captures the browser download, parses the downloaded JSON, and checks package id/schema/hash/run-id/simulation boundary fields. It then drives the Backtest page `Parameter scan` action, asserts `POST /api/research/backtest/parameter-scan` uses Bearer auth, checks the bounded scan response and generated runs preserve `simulation_only=true` / `is_real_trade=false`, verifies the selected best run renders parameter-scan, walk-forward, and data-package validation protocol evidence, and checks `backtest-parameter-scan-history` renders the retained scan id, best run, trial count, and simulation boundary. It then queues the async parameter-scan job, waits for `COMPLETED`, clicks `backtest-parameter-scan-job-handoff`, asserts `POST /api/research/backtest/parameter-scan/jobs/{job_id}/handoff` uses Bearer auth, and requires `HANDED_OFF`, `LOCAL_DEPLOYMENT_HANDOFF_DIR`, `backtest_parameter_scan_job_handoff_manifest_v1`, `deployment_owned_after_handoff`, `simulationOnly=true`, and `isRealTrade=false` before accepting `ok strict-auth browser Backtest parameter-scan handoff`. The smoke then writes a deployment-style `backtest_parameter_scan_job_handoff_shipper_status_v1` sidecar, clicks `backtest-parameter-scan-job-handoff-refresh`, verifies `handoffStatus.status=DELIVERED`, `provider=object-store`, `matchesLatestHandoff=true`, `matchesJob=true`, `searchIndexReady=true`, and confirms `backtest-parameter-scan-job-handoff-custody` renders the delivered/search-ready state without leaking the fixture secret before accepting `ok strict-auth browser Backtest parameter-scan handoff custody`. After creating the P2 closed-loop sample it follows a Research Lab Backtest link that preserves `iteration_id`, waits for the selected Backtest run, clicks `backtest-create-verdict-inputs`, asserts the POST uses Bearer auth, and checks the response/notice keep Backtest evidence supporting-only. It also follows the Research Lab SignalOps evidence link, verifies both `iteration_id` and `signal_id` survive into `/signalops`, and confirms the selected SignalOps detail loads with Bearer auth before accepting the Research evidence context. The same strict-auth run opens `/data-reliability`, verifies `/api/data-reliability/snapshot` uses Bearer auth, checks a deterministic partial/fallback snapshot renders latest source freshness, adapter fallback context, fallback count, slowest latency cards, current-run provenance/freshness, and persisted `SOURCE_FALLBACK` evidence. It then opens `/settings` through SPA navigation, returns a deterministic adapter list while failing adapter config, verifies the adapter list and config-load error remain visible, and clicks `settings-adapter-refresh-all` to confirm the live-check refresh path preserves partial-load state under Bearer auth. It also opens canonical `/quant-core?run_id=...`, records a Technical Kline `misjudge` case through the active page, asserts `POST /api/technical-kline/cases` uses Bearer auth with run/config/prompt context, and verifies the returned Case Library id is visible. `smoke:frontend` additionally guards the Technical Kline case-impact panel (`technical-kline-case-impact` / `technical-kline-current-config-impact`) and the typed `TechnicalKlineCaseImpact` contract so reviewed-case impact by config hash remains visible on `/quant-core`.

Technical Kline role-boundary coverage requires the actual `/quant-core` `TechnicalKlineCaseGovernanceCard` to keep `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `technical-kline-card-case-role`, `technical-kline-card-case-disabled-reason`, the handler-level `if (!canRecordCase)` short-circuit, and `disabled={recording || loading || !governance || !canRecordCase}` before `recordTechnicalKlineCase()`. The legacy `TechnicalKlinePage` source should keep `technical-kline-governance-role`, governance/case disabled reasons, `technical-kline-save-governance`, `technical-kline-rollback-governance`, and `technical-kline-record-current-case` so static smoke catches regressions, but browser DOM proof should target the mounted `/quant-core` card.

Backtest role-boundary coverage requires `/research-lab/backtest` to keep research writes behind `researcher+`, local job cancellation behind `operator+`, and artifact handoff/delete actions behind `admin`. Keep `BacktestPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'operator')`, `roleAllows(operator.role, 'admin')`, `backtest-research-write-role`, `backtest-research-write-disabled-reason`, `backtest-job-control-role`, `backtest-job-control-disabled-reason`, `backtest-artifact-handoff-role`, `backtest-artifact-handoff-disabled-reason`, handler-level short-circuits, and disabled write/control buttons guarded by `smoke:frontend`. The guarded write set includes run creation, synchronous parameter scan, async parameter-scan job creation, SignalOps sample generation, SignalOps random validation start, and Backtest -> Research verdict-input evidence creation; job cancellation remains operator-gated and artifact handoff remains admin-gated.

Data Reliability external monitoring coverage now also requires `data_reliability_external_monitor_status_v1` to stay on `/api/data-reliability/snapshot.externalMonitorStatus`, with `DataReliabilityExternalMonitorStatus` typed in `dataReliabilityClient`, `data-reliability-external-monitor-status` visible on `/data-reliability`, static guards in `smoke:frontend`, and the strict-auth marker `ok strict-auth browser Data Reliability external monitoring retention`. This remains deployment-reported visibility only; the app does not own provider monitor deployment or retention enforcement.

Data Reliability frontend response coverage also requires `dataReliabilityClient` to guard `getDataReliabilitySnapshot()`, `getDataReliabilitySummary()`, adapter list/check responses, matrix entries, history rows, event rows, external-monitor sidecar status, and symbol-check rows before `/data-reliability` stores them in render state. These endpoint calls should stay on `request<unknown>()` before runtime guards run, so the page never relies on compile-time-only generic trust for backend payload shape. When changing these guards or the strict-auth Data Reliability fixture, run `npm.cmd run typecheck`, `npm.cmd run smoke:frontend`, `npm.cmd run test:backend -- backend\tests\test_data_reliability_routes.py -q --basetemp=.tmp\pytest-data-reliability-client-guards`, and a strict-auth browser group that reaches `/data-reliability`.

Data Reliability active-check coverage also requires `/data-reliability` to keep explicit adapter checks and symbol coverage checks behind the shared `operator+` browser role boundary. Keep `DataReliabilityPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'operator')`, `data-reliability-check-role`, `data-reliability-check-disabled-reason`, `data-reliability-adapter-check`, `data-reliability-symbol-check`, and handler-level `if (!canRunDataReliabilityChecks)` short-circuits guarded by `smoke:frontend`. Snapshot, freshness, event trail, external-monitor, matrix, and history reads remain visible without active-check permission.

The Research/Backtest strict-auth group should keep `navigateToResearchLoopsPage()` and the stable `current-iteration-id` assertion for Research -> SignalOps deep links. This prevents `/research-lab/backtest` -> `/research-lab/research` subroute checks from depending on raw `pushState` or global text matching while still requiring the visible Research loop and SignalOps evidence link to work.

Technical Kline governance coverage now also requires `savedGovernance.caseImpact.representativeCaseSet`, `parameterVersionReview`, and `longWindowRegression` to remain typed and visible. `/quant-core` must keep `technical-kline-representative-case-set`, `technical-kline-representative-missing-classes`, `technical-kline-parameter-version-review`, `technical-kline-parameter-version-delta`, and `technical-kline-long-window-regression`; `smoke:strict-auth-browser` must keep the representative case-set fixture, `READY_FOR_REVIEW` assertion, baseline config delta rendering, long-window retained-case regression rendering, and exact created-run Live Run stream matching before accepting `ok strict-auth browser Technical Kline Case Library sedimentation`.

Technical Kline frontend response coverage also requires `technicalKlineClient` to guard analysis, prompt, governance, saved governance, case-impact, signal-backtest, and case-record responses before `/technical-kline` or `/quant-core` stores them in render state. These guarded endpoint calls should stay on `request<unknown>()` before the `assertTechnical...` guards run, so Technical Kline pages never rely on compile-time-only generic trust for backend payload shape. Governance, prompt, and signal-backtest payloads must keep `NO_DIRECT_TRADE_ACTION`; representative case-set, parameter-version review, and long-window regression payloads must keep `REVIEW_ONLY_NO_TRADE_ACTION`, `blocking=false`, and reviewed-case governance semantics. When changing these guards or the strict-auth Technical Kline fixture, run `npm.cmd run typecheck`, `npm.cmd run smoke:frontend`, `npm.cmd run test:backend -- backend\tests\test_technical_kline_agent.py -q --basetemp=.tmp\pytest-technical-kline-client-guards`, and a strict-auth platform browser smoke that reaches `/quant-core`.

Backend Status production-health strict-auth coverage should keep the apply-token flow refreshing the read-only Production Health card and the platform smoke's Bearer-checked `/api/metrics` fixture aligned with `productionHealth.windows`, `productionHealth.trend`, and `productionHealth.longTrend`. This avoids judging slow isolated SQLite aggregation as a page failure while still proving the page sends Authorization and renders `backend-production-health-trend-deltas` before continuing to Dashboard, Data Reliability, Settings, and Technical Kline.

Backend health/startup/metrics frontend response coverage requires `analysisClient.getBackendHealth()`, `getStartupStatus()`, and `getBackendMetrics()` to stay on `request<unknown>()` before their runtime guards run. `useBackendStore` should reuse those guarded helpers, including the 3-second startup-status timeout, so TopBar and HistorySelector do not consume compile-time-only `/health` or `/startup/status` payloads. When changing these guards or the platform health fixture, run `npm.cmd run typecheck`, `npm.cmd run smoke:frontend`, `npm.cmd run test:backend -- backend\tests\test_observability_routes.py -q --basetemp=.tmp\pytest-backend-health-metrics-client-guards`, and `npm.cmd run smoke:strict-auth-browser:platform`.

Startup readiness and Dashboard decision-workbench coverage require optional local warmers to remain concurrent and `market_data_status` to stay deferred/degraded instead of blocking or revoking READY. Keep `backend\tests\test_main_lifespan.py` covering concurrent local warmers, deferred market-data failure, and deferred market-data timeout. Dashboard analysis detail responses must keep additive `dashboardSummary.schema=analysis_dashboard_summary_v1`, `tradeBoundary.simulationOnly=true`, and `tradeBoundary.isRealTrade=false` without persisting the projection into run storage; `/` must keep `dashboard-decision-workbench`, `dashboard-trade-boundary`, `dashboard-evidence-spine`, `simulationOnly=true`, and `isRealTrade=false`. Shared run-history filtering must keep `visibleRunHistory()` hiding `P2_CLOSED_LOOP_SAMPLE` rows from normal selectors while preserving active/deep-linked ids in Dashboard, Live Run, and Data Compression. When touching these paths, run `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py backend\tests\test_main_lifespan.py -q --basetemp=.tmp\pytest-dashboard-startup`, `npm.cmd run typecheck`, `npm.cmd run smoke:frontend`, and a Dashboard-reaching strict-auth browser smoke when browser fixtures changed.

Dashboard closed-loop coverage in `smoke:strict-auth-browser` now also toggles the operator role from `viewer` to `admin`: it asserts the Dashboard `Research Lab closed-loop sample` button is disabled for `viewer` with a visible reason, then restores `admin`, clicks the action, verifies Bearer auth on `POST /api/research/p2/closed-loop-sample`, and checks the returned chain keeps `simulation_only=true` / `is_real_trade=false`. `smoke:frontend` statically guards the same role hook, `researcher` threshold, disabled reason, and Dashboard closed-loop DOM hooks.

Dashboard and Backend Status LLM live-call health coverage requires `productionHealth.windows[*].llmCallFailureRate` to keep `successRate`, `failureRate`, `failureReasons`, `sampleFailures`, and `totalTokens`; `productionHealth.windows` must keep `24h`, `7d`, and `30d`; `productionHealth.trend` and `productionHealth.longTrend` must keep `baselineWindow`, `llmSuccessRateDelta`, and `llmFailureRateDelta`; Dashboard must keep `getBackendMetrics()`, `dashboard-llm-live-call-health`, `dashboard-llm-live-call-success-rate`, `dashboard-llm-live-call-trend`, and `dashboard-llm-live-call-failure-reason`; Backend Status must keep `backend-production-health-refresh`, `backend-production-health-llm-failure-reasons`, and `backend-production-health-trend-deltas`; and browser smoke must keep verifying Bearer-auth `/api/metrics` loading plus redacted success/failure-reason and 24h-vs-7d/30d trend fixtures. The strict-auth platform smoke clicks the Backend Status refresh after applying the operator token, then opens Dashboard and Backend Status against the same `/api/metrics` fixture and must keep printing `ok strict-auth browser cross-page production health trend fixture`, proving both pages consume the same backend-derived production-health contract. This path is read-only and must not trigger a live LLM call.

Data Reliability provenance coverage requires `DataReliabilityPage` to keep consuming `buildDashboardProvenanceSummary(currentRun)` and to preserve `data-reliability-page`, `data-reliability-current-run-id`, `data-reliability-data-provenance`, `data-reliability-source-freshness`, and `data-reliability-fallback-chain`. `smoke:strict-auth-browser` must keep opening `/data-reliability` for the seeded run, asserting the run id, visible provenance/freshness/fallback sections, and Bearer-auth snapshot loading via the marker `ok strict-auth browser Data Reliability provenance/freshness`.

SignalOps candidate/baseline review coverage requires the review card to preserve `signalops-review-candidate-baseline`, row test ids generated from config keys, and the `candidateBaselineParameterRows(item)` path from `strategy_experiment.baseline_config` / `candidate_config`. `smoke:strict-auth-browser` must keep fixture baseline/candidate configs, assert the visible `1.2% -> 0.8%` review delta, and emit `ok strict-auth browser SignalOps candidate baseline review` before the approval/rejection decisions.

SignalOps review-decision event export verification, handoff, and custody-sidecar coverage requires `POST /api/signalops/auto-paper/review-decision-events/verify`, `POST /api/signalops/auto-paper/review-decision-events/handoff`, `verifyAutoPaperTradingReviewDecisionEventExport()`, `handoffAutoPaperTradingReviewDecisionEvents()`, `signalops-review-event-export-verification`, `signalops-review-event-export-role`, `signalops-review-event-export-disabled-reason`, `signalops-verify-review-event-export`, `signalops-handoff-review-event-export`, `signalops-review-event-export-handoff-status`, and `signalops-review-event-export-shipper-status` to stay wired. SignalOps role-boundary coverage must also keep `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'operator')`, `roleAllows(operator.role, 'admin')`, `signalops-operator-policy`, lifecycle-write/manual-control/runtime-config role hooks, their disabled-reason hooks, handler-level short-circuits, and verify/handoff buttons bound to `canOperateSignalOps` guarded by `smoke:frontend`. `smoke:strict-auth-browser:signalops` must keep proving a signed export verifies as `VALID`, a tampered event bundle verifies as `INVALID`, the page verification button renders status, the handoff button returns/renders `HANDED_OFF` with `LOCAL_DEPLOYMENT_HANDOFF_DIR`, and the deployment-style `signalops_review_decision_event_export_shipper_status_v1` state renders `DELIVERED`, provider, retention policy, latest handoff/export matching, and no fixture secret before printing `ok strict-auth browser SignalOps review decision export handoff custody` and `ok strict-auth browser SignalOps review decisions`.

Plugin Registry artifact lifecycle and client-contract coverage requires `pluginClient` to keep response guards for registry rows, runtime plans/nested agent policies, usage stats/history buckets, artifact upload/cleanup, audit, validate, sandbox, and lifecycle mutation responses before `PluginRegistryPage` consumes them. `smoke:frontend` must keep checking the guard names and `.then(...)` wiring alongside upload and upgrade UI state. Keep the package artifact card (`plugin-package-artifact-state`), upgraded lifecycle card (`plugin-upgraded-state`), cleanup dry-run card, external scan status/provider text, external scan readiness details (`provider READY`, `threat intel CURRENT`, `signature ...`, `checksum matched`), and strict-auth runtime markers for artifact upload, cleanup dry-run, and archive lifecycle together. Plugin Registry runtime-check coverage also requires manifest validation and per-agent sandbox runs to stay behind the shared `operator+` browser role boundary, while lifecycle toggle/archive/upgrade/upload/cleanup remains `admin`. Keep `PluginRegistryPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'operator')`, `roleAllows(operator.role, 'admin')`, `plugin-runtime-action-role`, `plugin-runtime-action-disabled-reason`, `plugin-lifecycle-action-role`, `plugin-lifecycle-action-disabled-reason`, `plugin-validate-action`, `plugin-sandbox-run-`, handler-level `if (!canRunPluginChecks)` and `if (!canTogglePlugins)` short-circuits, and disabled validate/sandbox/lifecycle/artifact expressions guarded by `smoke:frontend`. Registry reads, resource summaries, usage stats/history, package artifact state, and audit rows remain visible without runtime-check or lifecycle permission. `smoke:strict-auth-browser` configures `TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_REQUIRED=1`, writes a temporary sidecar verdict, and must continue proving the uploaded artifact renders `external scan PASSED` plus provider-readiness evidence. The Plugin chain must enter its prerequisite Backend Status page through the real app link helper before clicking `/plugins`, and the browser run must keep printing `ok strict-auth browser app-link navigation Plugin Registry prerequisite Backend Status route`. The strict-auth Plugin summary panel waits must keep 30-second timeouts plus `pageRenderDiagnostic(...)` so a missing `plugin-resource-summary`, `plugin-usage-summary`, or `plugin-usage-history` reports page errors instead of only a locator timeout.

Backend Status worker diagnostics pagination coverage requires `analysisClient.getAnalysisJobs(limit, offset)` and `getAnalysisJobAttempts({ limit, offset, runId })` to keep forwarding `offset`; Backend Status must preserve `backend-analysis-job-queue-page`, `backend-analysis-job-queue-prev`, `backend-analysis-job-queue-next`, `backend-analysis-job-attempt-page`, `backend-analysis-job-attempt-prev`, and `backend-analysis-job-attempt-next`. If the SQLite attempt mirror is locked, `/analysis/jobs/attempts` must fall back to the JSON job store's current attempt row instead of returning `[]`, while still preserving SQLite retry-history behavior when the mirror is readable. `smoke:frontend` statically guards the hooks, and `smoke:strict-auth-browser` must keep printing `ok strict-auth browser Backend Status attempt diagnostics` and `ok strict-auth browser Backend Status analysis job queue`.

Backend Status queue summary coverage requires `analysisClient.getAnalysisJobs(limit, offset, statuses)` and `getAnalysisJobSummary(limit, offset, statuses)` to keep forwarding repeatable `status` filters, while `getAnalysisJobAttempts()` keeps the longer diagnostics timeout. `GET /analysis/jobs/summary` must also keep the read-only `external_queue_status.schema="analysis_job_external_queue_status_v1"` sidecar contract, including provider readiness fields `claim_backend`, `claim_status`, `idempotency_scope`, `audit_stream`, `dead_letter_queue`, `dead_letter_count`, `visibility_timeout_seconds`, and `lease_renewal_status`. Backend Status must preserve `backend-analysis-job-queue-filter`, `backend-analysis-job-queue-total`, `backend-analysis-job-external-queue-status`, and `backend-analysis-job-external-queue-readiness`; queue loading must keep stale-response protection so an older request cannot hide a newer seeded worker job. `smoke:strict-auth-browser:platform` writes a temporary `TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE` sidecar and must verify both the summary payload, visible external queue row, and visible readiness row before printing `ok strict-auth browser Backend Status analysis job external queue readiness`. Run `npm.cmd run build` before `npm.cmd run smoke:strict-auth-browser`, because the strict-auth browser wrapper serves `frontend/dist`.

Analysis lifecycle/job/node/report frontend response coverage requires `analysisClient` create/start/retry/cancel, job list/summary, node list/detail, debate, final-report, report-list, and delete helpers to stay on `request<unknown>()` before their runtime guards run. The static `smoke:frontend` markers should keep those exits aligned with `assertCreateAnalysisResponse`, `assertStartAnalysisResponse`, `assertAnalysisRunJobActionResponse`, `assertAnalysisJobs`, `assertAnalysisJobSummary`, `assertAgentNodes`, `assertAgentNode`, `assertAnalysisDebateResponse`, `assertFinalReportAsset`, and `assertDeleteAnalysisRunResponse`. When changing this slice, run `npm.cmd run typecheck`, `npm.cmd run smoke:frontend`, `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py backend\tests\test_analysis_job_sqlite.py backend\tests\test_final_writer.py backend\tests\test_final_report_store.py -q --basetemp=.tmp\pytest-analysis-client-lifecycle-guards`, `npm.cmd run smoke:strict-auth-browser:platform`, and `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`.

Backend Status ops alert/log frontend response coverage requires `analysisClient` production alert status/export/handoff/dispatch and ops log status/query/export/handoff helpers to stay on `request<unknown>()` before their runtime guards run. The static `smoke:frontend` markers should keep those exits aligned with `assertProductionAlertChannelStatus`, `assertProductionAlertExportBundle`, `assertProductionAlertExportHandoff`, `assertProductionAlertDispatchResult`, `assertOpsLogStatus`, `assertOpsLogQueryResult`, `assertOpsLogExportBundle`, and `assertOpsLogExportHandoff`. The production-alert status guard must continue accepting an empty-string `last_event_at` for the valid no-alert state, and `smoke:strict-auth-browser` must keep `PRODUCTION_ALERT_OUTBOX_FILE` isolated per run so the platform scenario is not coupled to default local alert storage. When changing this slice, run `npm.cmd run typecheck`, PowerShell parse checks for the smoke scripts, `npm.cmd run test:backend -- backend\tests\test_observability_routes.py -q --basetemp=.tmp\pytest-ops-alert-log-client-guards`, `npm.cmd run smoke:frontend`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:strict-auth-browser:platform`.

Backend Status ops-log export readiness coverage requires `/ops/logs/status` to keep returning `external_aggregation_ready`, `query_endpoint`, `query_schema`, `export_endpoint`, `export_schema`, `retention_policy`, `redaction_policy`, `handoff_status.schema="ops_log_export_handoff_status_v1"`, `handoff_status.inventory.schema="ops_log_export_handoff_inventory_v1"`, and `handoff_status.shipper_status.schema="ops_log_export_shipper_status_v1"`; `/ops/logs/query` must keep returning bounded sanitized `ops_log_query_v1` results over local JSONL events; `/ops/logs/export` must keep returning bounded sanitized `ops_log_export_v1` bundles with checksum. `POST /ops/logs/export/handoff` must return `DISABLED` when `OPS_LOG_EXPORT_HANDOFF_DIR` is not configured, and must write an `ops_log_export_v1` bundle plus `ops_log_export_handoff_manifest_v1` manifest with `deployment_owned_after_handoff` custody when configured. If deployment tooling writes `OPS_LOG_EXPORT_HANDOFF_DIR/shipper_status.json`, focused observability tests must keep proving the read-only sidecar status is BOM-compatible, sanitized, matches latest inventory by handoff id/checksum, and reports provider readiness fields including `remote_object_key`, `retention_status`, `custody_status`, `kms_key_ref`, `search_index`, and `search_index_ready`. Time-based local pruning is optional and guarded by `OPS_LOG_RETENTION_DAYS` / `TIANYUAN_OPS_LOG_RETENTION_DAYS`; focused observability tests must keep proving old events are pruned only when this policy is enabled. Backend Status must preserve `backend-ops-log-export-ready`, `backend-ops-log-handoff-role`, `backend-ops-log-handoff-disabled-reason`, `backend-ops-log-query-endpoint`, `backend-ops-log-query-text`, `backend-ops-log-query`, `backend-ops-log-query-result`, `backend-ops-log-export-endpoint`, `backend-ops-log-retention-policy`, `backend-ops-log-handoff-status`, `backend-ops-log-handoff-integrity`, `backend-ops-log-shipper-status`, `backend-ops-log-shipper-readiness`, `backend-ops-log-export`, `backend-ops-log-export-result`, `backend-ops-log-handoff`, and `backend-ops-log-handoff-result`; `smoke:frontend` must keep the handoff button title wired to the admin disabled reason while leaving sanitized export reads available. `smoke:strict-auth-browser:platform` must click the query, export, and handoff actions, assert Bearer-auth JSON with query schema/source counts plus export schema/source/checksum/manifest custody, render the results, verified inventory, shipper sidecar row, and provider readiness row, and keep printing `ok strict-auth browser Backend Status ops log query`, `ok strict-auth browser Backend Status ops log export readiness`, `ok strict-auth browser Backend Status ops log shipper readiness`, and `ok strict-auth browser Backend Status ops log export handoff`.

Backend Status production-alert export readiness coverage requires `/ops/alerts/status` to keep returning `external_aggregation_ready`, `export_endpoint`, `export_schema`, `alert_rule_policy.schema="production_alert_rule_policy_v1"`, `alert_rule_policy.provider_acceptance.schema="production_alert_rule_provider_acceptance_v1"`, `retention_policy`, `redaction_policy`, `handoff_status.schema="production_alert_outbox_export_handoff_status_v1"`, `handoff_status.inventory.schema="production_alert_outbox_export_handoff_inventory_v1"`, and `handoff_status.shipper_status.schema="production_alert_outbox_export_shipper_status_v1"`; `/ops/alerts/export` must keep returning bounded sanitized `production_alert_outbox_export_v1` bundles with checksum, alert-rule metadata, and provider-acceptance status while never returning webhook URLs or secret-like values. `POST /ops/alerts/export/handoff` must return `DISABLED` when `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR` is not configured, and must write a `production_alert_outbox_export_v1` bundle plus `production_alert_outbox_export_handoff_manifest_v1` manifest with `deployment_owned_after_handoff` custody and `alert_rule_policy` when configured. If deployment tooling writes `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR/shipper_status.json`, focused observability tests must keep proving the read-only sidecar status is BOM-compatible, sanitized, matches latest inventory by handoff id/checksum, and reports provider readiness fields including `remote_object_key`, `retention_status`, `custody_status`, `kms_key_ref`, `search_index`, and `search_index_ready`. If deployment tooling writes `PRODUCTION_ALERT_RULE_POLICY_FILE`, focused observability tests must keep proving custom rules are sanitized and applied to event `alert_rule_id` / `alert_routing_key`. If deployment tooling writes `PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE`, focused observability tests must keep proving `provider_acceptance` is sanitized and matches current policy id/rule count/rule ids. Backend Status must preserve `backend-production-alert-export-ready`, `backend-production-alert-admin-role`, `backend-production-alert-admin-disabled-reason`, `backend-production-alert-export-endpoint`, `backend-production-alert-handoff-status`, `backend-production-alert-handoff-integrity`, `backend-production-alert-shipper-status`, `backend-production-alert-shipper-readiness`, `backend-production-alert-rule-policy`, `backend-production-alert-rule-provider-acceptance`, `backend-production-alert-export`, `backend-production-alert-export-result`, `backend-production-alert-handoff`, and `backend-production-alert-handoff-result`; `smoke:frontend` must keep dispatch and handoff button titles wired to the admin disabled reason while leaving sanitized export reads available. `smoke:strict-auth-browser:platform` must keep printing `ok strict-auth browser Backend Status production alert rule provider acceptance`, `ok strict-auth browser Backend Status production alert export readiness`, `ok strict-auth browser Backend Status production alert shipper readiness`, and `ok strict-auth browser Backend Status production alert export handoff`.

Live Run SSE stream response coverage requires `connectRunStream()` to parse `EventSource` payloads as `unknown` and pass them through `assertStreamMessage()` before invoking page handlers. The stream guard must keep requiring a non-empty `event_type`, validating optional string fields when present, preserving arbitrary `payload`, and keeping terminal events such as `RUN_FINISHED`, `RUN_FAILED`, `RUN_CANCELLED`, `RUN_STALE_RECOVERED`, `RUN_NOT_FOUND`, `RUN_REMOVED`, and `STREAM_TIMEOUT` wired to close/refresh behavior. `smoke:frontend` must keep checking guarded parsing markers alongside EventSource query-token support. When changing this slice, run `npm.cmd run typecheck`, PowerShell parse check for `scripts\smoke-frontend-routes.ps1`, `npm.cmd run smoke:frontend`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`.

New Task -> Live Run handoff coverage requires `NewTaskPage` to navigate after successful `startAnalysisRun(response.run_id)` instead of blocking on initial run-detail hydration. `smoke:research-closure:browser` and `smoke:strict-auth-browser` must continue proving the Portfolio/New Task-created run reaches `/live-run?run_id=<created run>`, opens the EventSource stream for that exact run id with the scoped query token, and remains connected to Final Writer/Audit follow-up checks. The strict-auth chain should open Final Writer with `/final?run_id=<created run>` so the page hydrates the exact created run before checking `final-writer-current-run-id`, provenance, source freshness, final action, and sections. `FinalWriterPage` must keep `useSearchParams`, `refreshRun(linkedRunId)`, and `final-writer-page-loading` so a direct deep link cannot render against a stale store run. Strict-auth fallback navigation must avoid full reloads because the API token is tab-memory only; missed Final Writer/Audit/Plugin browser response events should use the page-level `/api` proxy fallback before direct Bearer API fallback, and both fallbacks must stay timeout-bounded. The Audit Log page must still visibly render the expected run event before `ok strict-auth browser Audit Log run audit`.

New Task run-creation coverage also requires `/new-task` to keep `createAnalysisRun()` and `startAnalysisRun()` behind the shared `researcher+` browser role boundary. Keep `NewTaskPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `new-task-run-role`, `new-task-run-disabled-reason`, `new-task-submit`, the handler-level `if (!canCreateAnalysisTask)` short-circuit, and `disabled={loading || !canCreateAnalysisTask}` guarded by `smoke:frontend`. Portfolio snapshot reads, preflight rendering, default LLM profile status reads, and form editing remain visible without run-creation permission.

Research Lab workflow maturity coverage requires backend `ResearchWorkflowState` to keep `maturity_score`, `maturity_level`, `maturity_label`, and `maturity_reasons`; `researchClient` must validate those fields; `ResearchLoopsPage` must keep `workflow-maturity-level` and `workflow-maturity-reason`; and `smoke:strict-auth-browser` must keep verifying the P2 closed-loop sample renders a `missing_sample` or weak-evidence maturity state without changing verdict acceptance or knowledge promotion.

Research Lab workflow-step evidence coverage requires every `ResearchWorkflowStep` returned by `researchClient` to validate `source`, `source_timestamp`, `evidence_strength`, `missing_items`, `next_action`, and `next_action_label` before the P2 closed-loop wizard renders step source, timestamp, strength, missing items, and next action. Keep those fields required in `ResearchWorkflowStep` and guarded by `smoke:frontend` so a partial backend payload fails as a controlled client contract error instead of silently hiding evidence metadata.

Research Lab workflow write coverage also requires `ResearchLoopsPage` to keep the shared operator role guard: `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `research-lab-workflow-role`, `research-lab-workflow-disabled-reason`, `research-closed-loop-secondary-disabled-reason`, `research-create-closed-loop-sample-secondary`, `research-materialize-current-artifacts`, and `ensureResearchLabWrite`. The P2 closed-loop guide's secondary create/materialize controls and option checkboxes must surface the same disabled reason as the main toolbar before any handler can call Research write APIs. `smoke:strict-auth-browser` must keep the `/research-lab/research` viewer-to-admin toggle before the P2 closed-loop sample so one-click latest-run, closed-loop, and secondary guide writes cannot regress to viewer-enabled behavior.

Research Lab hypothesis-draft coverage requires `researchClient` to validate `action_selection` and every item in `ResearchHypothesisDraftResponse.drafts` before `ResearchLoopsPage` renders or applies drafts. Keep `action_selection.evidence[]`, draft `target_modules[]`, and supported `targetModules[]` / `modules[]` aliases validated as string arrays through `assertStringArray()`, and keep `assertResearchActionSelection()`, `assertResearchHypothesisDraft()`, and `.forEach(assertResearchHypothesisDraft)` guarded by `smoke:frontend` so malformed LLM/rule draft payloads fail as controlled client errors instead of causing draft-card render or apply-time crashes.

Research Lab verdict-input coverage requires `researchClient` to validate every `ResearchVerdictInputs.comparison[]` and `ResearchVerdictInputs.evidence[]` item before `ResearchLoopsPage` renders metric rows or sends verdict evidence into feedback. Keep `assertResearchMetricComparisonRow()`, `assertResearchVerdictEvidence()`, and their `.forEach(...)` calls guarded by `smoke:frontend`; evidence rows must retain source type/id, label, quality, summary, metrics, and created timestamp before feedback can reuse them as `evidence_links`.

Research Lab iteration coverage requires `researchClient` to validate `ResearchIteration.target_modules[]` as strings and every `ResearchIteration.evidence_links[]` / `ResearchIteration.feedback_events[]` item before loop/detail, trace, Backtest-evidence, SignalOps-evidence, or feedback responses enter render state. Keep `assertResearchEvidenceLink()`, `assertResearchFeedbackEvent()`, and their `.forEach(...)` calls guarded by `smoke:frontend` so malformed persisted iteration evidence cannot break Research Lab module chips, edit-form joins, evidence links, readiness counters, warnings, or feedback history rendering.

Research Lab string-list response coverage requires `researchClient` to validate loop `tags[]`, sample-loop `missing_reasons[]`, P2 closed-loop `warnings[]`, verdict-input `blocking_reasons[]` and `quality_warnings[]`, artifact-materialization `provenance_chain[]` and `warnings[]`, and trace-import preview `tags[]` plus response `warnings[]` with `assertStringArray()` before pages render badges, warnings, toast text, or joined strings. Keep these static checks guarded by `smoke:frontend` so malformed list payloads fail as controlled client contract errors instead of creating render-time crashes or misleading empty evidence.

Research Trace import coverage requires `ResearchTracesPage` to parse pasted JSON as `unknown`, require a non-array top-level object, normalize blank source to `rd-agent`, and keep the import write behind the shared `researcher+` operator role boundary before calling `importResearchTrace()`. Keep `parseTraceJsonObject()`, the array/null/scalar rejection, `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `research-trace-import-role`, `research-trace-import-disabled-reason`, `research-trace-import-submit`, and the no-direct-cast marker guarded by `smoke:frontend` so invalid pasted traces fail as controlled form errors and viewer-role imports stay disabled before the backend import route.

Live Run control coverage requires `/live` to keep cancel/retry controls behind the shared `operator+` role boundary in addition to job-status eligibility. Keep `LiveRunConsole` wired to `useOperatorContext()`, `roleAllows(operator.role, 'operator')`, `canCancelRunByStatus`, `canRetryRunByStatus`, `canControlLiveRun`, `live-run-control-role`, `live-run-control-disabled-reason`, `live-run-cancel-run`, `live-run-retry-run`, disabled action buttons, and handler-level `if (!canControlLiveRun)` short-circuits guarded by `smoke:frontend`, so viewer/researcher browser sessions cannot trigger analysis cancel or retry calls even when a run status would otherwise make the action eligible.

Research Lab evidence-bridge coverage requires `POST /api/research/backtest/runs/{run_id}/verdict-inputs` and `POST /api/research/signalops/signals/{signal_id}/evidence` responses to keep top-level `evidence_usage="supporting_only"`, `supporting_only=true`, `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false` in addition to guarded `iteration` and `verdict_inputs`. Keep `assertSupportingOnlyResearchBridgeBoundary()` guarded by `smoke:frontend`, keep focused backend route tests for Backtest and SignalOps bridge responses, and keep strict-auth browser boundary assertions so bridge evidence remains review input only rather than verdict acceptance, knowledge promotion, order routing, or real-trade authority.

Backend Tuning config-write coverage requires `/tuning` to keep the shared admin operator role guard before applying runtime config or submitting review drafts. Keep `BackendTuningPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'admin')`, `backend-tuning-role`, `backend-tuning-disabled-reason`, `backend-tuning-apply-runtime`, `backend-tuning-submit-draft`, disabled write buttons, and handler-level `canManageBackendTuning` short-circuits guarded by `smoke:frontend`, so non-admin browser sessions cannot trigger config writes from this legacy tuning surface.

Agent Runtime surface-scoped external restore focused checks:

```powershell
npm.cmd run test:backend -- backend\tests\test_agent_runtime.py::test_external_config_restore_uses_approved_vault_version_refs backend\tests\test_agent_runtime.py::test_external_data_sources_restore_is_surface_scoped backend\tests\test_agent_runtime.py::test_external_market_data_profile_restore_is_surface_scoped backend\tests\test_agent_runtime.py::test_external_market_data_adapter_restore_is_surface_scoped -q --basetemp=.tmp\pytest-config-surface-restore
npm.cmd run test:backend -- backend\tests\test_config_routes.py::test_config_versions_filter_by_actor_and_include_secret_safe_policy -q --basetemp=.tmp\pytest-config-surface-policy
```

Use these when touching `/config/external-restore`, Agent Runtime config snapshots, or vault-version refs. They prove approved restore uses immutable secret refs, LLM/data-source/market-profile/adapter restore stays scoped to the requested surface, unrelated runtime profiles survive, and Config Versions still exposes secret-safe policy metadata.

Strict-auth query-token support is stream-only. The backend accepts the query-token aliases `token`, `api_key`, `apiKey`, `super_api_key`, and `superApiKey` only for `/api/analysis/runs/{run_id}/stream`, because browser `EventSource` cannot attach bearer headers. Sensitive REST reads, writes, and deletes must keep using `Authorization: Bearer ...` or API-key headers; reverse proxies in strict deployments should avoid logging full query strings for stream URLs.

Worker mode is opt-in:

```powershell
$env:ANALYSIS_EXECUTION_MODE="worker"
npm.cmd run worker:analysis -- -Once
```

Focused worker acceptance smoke:

```powershell
npm.cmd run smoke:analysis-worker
```

This runs the queue, claim, heartbeat, cancel, stale/reconciliation, and attempt-history tests, then launches the worker CLI once with `.tmp\analysis-worker-cli-smoke\analysis-worker.db` and `.tmp\analysis-worker-cli-smoke\analysis_jobs.json` so the smoke does not read or write the local runtime job mirror.

For isolated CLI smoke, do not let the worker read the local runtime job mirror. Pass both temp storage paths:

```powershell
npm.cmd run worker:analysis -- -Once -DatabaseFile .tmp\worker-cli-smoke.db -JobStorageFile .tmp\worker-cli-smoke\analysis_jobs.json
```

Without `ANALYSIS_EXECUTION_MODE=worker`, `POST /analysis/runs/{run_id}/start` keeps the existing in-process execution path.

`npm.cmd run audit:baseline` 是 Phase 0 基线冻结入口。它只读输出当前分支、HEAD、工作树状态、关键 SQLite 表计数、闭环必查表、闭环缺口和不可回退边界。闭环相关开发前应先确认 `portfolio_snapshots`、`holding_positions`、`analysis_runs`、`agent_results`、`signals`、`paper_orders`、`backtest_runs`、`research_evidence_links`、`research_loops`、`case_library`、`knowledge_patches`、`knowledge_versions`、`evaluation_runs`、`analysis_jobs` 的计数符合当前验收预期。

当 `audit:baseline` 在当前运行库暴露闭环表为 0 时，先用隔离临时库证明代码链路是否仍可参与闭环：

```powershell
npm.cmd run smoke:closed-loop-participation
```

该命令运行 P2 closed-loop 样例和 SignalOps paper-order 参与度断言，直接检查临时 SQLite 中 Analysis、Agent result、Portfolio、SignalOps、paper order、Backtest、Research evidence、Case、Knowledge patch/version、Evaluation 和 analysis job 表都有沉淀。它不写当前 `storage/tianyuan_quant.db`。

### 安全收口聚焦回归

修改 auth/RBAC、WebSocket stream、LLM/行情 egress、插件沙箱、Portfolio 导入或 RD-Agent trace 导入预算时，先跑：

```powershell
npm.cmd run test:backend -- backend\tests\test_http_auth.py backend\tests\test_stream_auth.py backend\tests\test_agent_runtime.py backend\tests\test_plugin_runtime.py backend\tests\test_portfolio_store.py backend\tests\test_research_trace_adapter.py backend\tests\test_research_store.py backend\tests\test_signalops_routes.py -q
```

该组检查 strict auth 下敏感读写 token、token 绑定 operator、防 header 提权、WebSocket token/query token、`egress_confirmed` 不绕过服务端 allowlist、Tushare HTTPS、插件 `external_json_stdio` 阻断、Portfolio 导入大小/行列/单元格限制、RD-Agent trace 预算限制和 SignalOps gate 字段服务端托管。

`npm.cmd run smoke:frontend` 需要先有 `frontend/dist`，会在 `127.0.0.1:4177` 临时启动静态预览，检查 `/`、`/new-task`、`/signalops`、`/research-lab`、`/research-lab/backtest`、`/config-versions`、`/backend`、`/backtest` redirect 等 SPA 路由，然后停止预览进程。它是路线 smoke，不替代完整浏览器交互测试。

`npm.cmd run smoke:research-closure` 会用隔离端口启动后端和 Vite dev server，默认后端从 `8766` 起找可用端口、前端从 `5796` 起找可用端口，并把 `TIANYUAN_QUANT_DB_URL` 指向 `.tmp/research-closure-smoke.db`。它检查 `/api/health`、`/api/research/summary`、`/research-lab/research`、`/research-lab/backtest`、`/quant-core`，再创建临时 Research loop，`auto_start=false` 创建 run，并验证 MFE/MAE retry 返回 warning 而不是 500。脚本只停止自己启动的进程，并尝试删除自己创建的分析 run。

可选浏览器补充：

```powershell
npm.cmd run smoke:research-closure:browser
```

该命令需要先运行 `npm.cmd run build` 生成 `frontend/dist`，然后复用 live smoke 的隔离后端和静态预览前端（`/api` 代理到临时后端）。Playwright 是硬门禁要求，不再在缺失 Playwright 时自动 skip。浏览器 smoke 覆盖：持仓样本创建、`/new-task` 关联、`/live-run` queued/worker path、MFE/MAE retry warning、Retry disabled reason、Closure health summary、Backtest 深链点击、P2 闭环 sample 的 run/backtest/research/case/knowledge/evaluation/knowledge-version ID 可见。失败时会输出当前 URL、当前路由、最后一次 API 请求/响应、console error，以及 backend/frontend stdout/stderr tail。

当前 root `.venv\Scripts\python.exe` launcher 在本地可能无法创建进程。后端编译检查优先使用与 `scripts/test-backend.ps1` 一致的工作路径：

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
$python = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
uv run --no-project --no-python-downloads --python $python --with-requirements backend\requirements.txt python -m py_compile backend\app\api\routes_analysis.py backend\app\api\routes_research.py backend\app\core\research_store.py backend\app\core\research_verdict_store.py
```

Backtest / Research Lab focused regression:

Backtest parameter scan focused regression:

```powershell
npm.cmd run test:backend -- backend\tests\test_backtest_store.py::test_backtest_parameter_scan_creates_bounded_runs_and_best_summary -q --basetemp=.tmp\pytest-backtest-parameter-scan
npm.cmd run test:backend -- backend\tests\test_backtest_signalops_sample.py::test_backtest_parameter_scan_history_routes_expose_retained_trials -q --basetemp=.tmp\pytest-backtest-parameter-scan-history
npm.cmd run test:backend -- backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_completes_and_retains_scan_result backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_recovers_persisted_running_job backend\tests\test_backtest_signalops_sample.py::test_backtest_parameter_scan_job_routes_complete_and_expose_result -q --basetemp=.tmp\pytest-backtest-job-attempts
npm.cmd run test:backend -- backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_completes_and_retains_scan_result backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_lease_blocks_duplicate_attempt_claim backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_recovers_persisted_running_job backend\tests\test_backtest_signalops_sample.py::test_backtest_parameter_scan_job_routes_complete_and_expose_result -q --basetemp=.tmp\pytest-backtest-job-lease
npm.cmd run test:backend -- backend\tests\test_backtest_store.py::test_backtest_parameter_scan_job_completes_and_retains_scan_result backend\tests\test_backtest_signalops_sample.py::test_backtest_parameter_scan_job_routes_complete_and_expose_result -q --basetemp=.tmp\pytest-backtest-job-handoff
npm.cmd run test:backend -- backend\tests\test_backtest_store.py::test_backtest_experiment_package_exports_reproducible_hashes backend\tests\test_backtest_signalops_sample.py::test_research_backtest_canonical_routes_and_legacy_read_compatibility -q --basetemp=.tmp\pytest-backtest-experiment-package
npm.cmd run test:backend -- backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run -q --basetemp=.tmp\pytest-backtest-verdict-inputs
```

When checking the local async Backtest parameter-scan job surface, verify the job response and page status keep `idempotencyKey`, `attemptCount`, `currentAttemptId`, `lastAttemptStatus`, retained `attempts[]`, `leaseOwner`, `leaseId`, `leaseStatus`, `leaseExpiresAt`, `queueMode=LOCAL_DURABLE_JSON`, `simulationOnly=true`, and `isRealTrade=false`. A restored persisted `RUNNING` / `RECOVERING` job should expose an `INTERRUPTED` prior attempt with an `EXPIRED` lease before the recovery attempt completes. Duplicate local runner claims should not create a second `RUNNING` attempt while an active lease is held. With `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR` configured, completed jobs should hand off `backtest_parameter_scan_job_handoff_bundle_v1` plus `backtest_parameter_scan_job_handoff_manifest_v1` files and return `HANDED_OFF`; incomplete jobs must remain `BLOCKED`. If deployment tooling writes `shipper_status.json`, `GET /api/research/backtest/parameter-scan/jobs/{job_id}` should expose dynamic `handoffStatus` with `schema=backtest_parameter_scan_job_handoff_shipper_status_v1`, delivery/search/retention fields, `matchesLatestHandoff`, `matchesJob`, and redacted secret-like text; `handoffStatus` must not be persisted in `backtest_parameter_scan_jobs.json` or the handoff bundle. `npm.cmd run smoke:strict-auth-browser:research-backtest` proves the Backtest markers through `ok strict-auth browser Backtest parameter-scan async job`, `ok strict-auth browser Backtest parameter-scan handoff`, and `ok strict-auth browser Backtest parameter-scan handoff custody`; if the later Research closed-loop segment fails, diagnose that navigation/role path separately instead of weakening the Backtest job contract.

When changing `backtestClient` response guards or the strict-auth Backtest fixture, keep the client-side simulation-boundary guards and run `npm.cmd run smoke:frontend` plus `npm.cmd run smoke:strict-auth-browser:research-backtest`. Guarded Backtest endpoint calls should stay on `request<unknown>()` before the `assertBacktest...` / SignalOps Backtest guards run, so `/research-lab/backtest` never relies on compile-time-only generic trust for backend payload shape. `backtestClient` should reject malformed or real-trade-looking payloads for parameter scans, retained scan history, async jobs, append-only handoff manifests, experiment packages, SignalOps experiments, random validation jobs, run parameters, signal metadata, summary counters, and delete results before `/research-lab/backtest` stores them in page state or refreshes run lists.

Market + technical analyst merge focused regression:

```powershell
npm.cmd run test:backend -- backend\tests\test_agent_runtime.py backend\tests\test_agent_executor.py backend\tests\test_technical_kline_agent.py backend\tests\test_analysis_workflow.py backend\tests\test_plugin_runtime.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
```

The expected active DAG contains `quant_core` instead of the old active market/technical/bottom/quant/scenario chain. Current research output is `run.mfeMaeResearch`; legacy fields `run.market`, `run.technicalKline`, `run.bottomResearch`, `run.quantEngine`, and `qiam.technicalKlineConstraint` remain part of the public contract for historical payloads and older clients.

```powershell
npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_backtest_signalops_sample.py backend\tests\test_research_store.py backend\tests\test_research_verdict_store.py backend\tests\test_research_artifact_store.py backend\tests\test_closed_loop_sample.py backend\tests\test_evaluation.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
```

Manual browser acceptance for this surface should cover `/research-lab/backtest`, `/backtest` redirect, `/research-lab/backtest?run_id=BT_...` deep link selection, Research Lab `Backtest: BT_...` links, and `/signalops` review queue / random validation / simulation-only labels.

### 前端构建

```powershell
npm.cmd run typecheck
npm.cmd run build
npm.cmd run smoke:frontend
```

根目录 `npm.cmd run build` 已转发到活跃前端 `frontend/`。旧根目录 `src/` 前端已删除，不要恢复为产品前端入口。
`smoke:frontend` also guards Settings adapter refresh resilience: the page must keep partial `Promise.allSettled` loading, adapter load-error hooks, and the adapter list hook so config-load failures do not hide successfully loaded health rows.

`smoke:frontend` also guards SignalOps selected-signal detail race prevention: the page must keep `signalDetailRequestSeq`, stale-response checks after detail/artifact loads, and selected-detail DOM hooks so rapid signal switching cannot regress to stale detail overwrites.
It also guards Audit Log response contracts before `/audit` stores event payloads: `auditClient` must keep `assertAuditLogEvents()`, `assertAuditLogEvent()`, required string checks for timestamp/runId/node/eventType/message/statusBefore/statusAfter/inputHash/outputHash/auditId, `.then(assertAuditLogEvents)`, and the `/analysis/runs/${runId}/audit` endpoint marker. This guard is frontend response validation only; it must not change backend audit generation, auth, run-snapshot fallback, or JSON export behavior for valid events.
It also guards K-line market-data response contracts before Dashboard K-line cards or `/market` store chart payloads: `klineClient` must keep `assertKlineResponse()`, `assertKlineRow()`, period/range/status/dataMode enum checks, required OHLC row validation, optional numeric checks for pre-close/change/volume/amount fields, `.then(assertKlineResponse)`, and the `/market-data/kline` endpoint marker. This guard is frontend response validation only; it must not change backend K-line fetching, adapter/cache policy, SignalOps K-line quality gates, or trading boundaries.
It also guards Global Market overview response contracts before `/global-market` stores index, fund-flow, sector-rank, temperature, source-chain, and arbitration payloads: `globalMarketClient` must keep `assertGlobalMarketOverviewPayload()`, root/container validation, row-level K-line/fund-flow/sector-rank finite-number checks, nested source/conflict/arbitration checks, temperature reason string-array validation, `request<unknown>('/market-data/global?range=4m')`, and guarded normalization wiring. This guard is frontend response validation only; it must not change backend global-market fetching, provider arbitration, fallback normalization, order routing, or trading boundaries.
It also guards Portfolio file import against regressing to raw `fetch`: `portfolioClient.importPortfolioSnapshot()` must build `FormData`, call the shared `request('/portfolio/imports')`, keep response guards for snapshot summaries, full snapshots, import responses, import jobs, and delete results, keep stable file/submit hooks, keep `portfolio-import-error-detail`, `portfolio-import-observed-headers`, `portfolio-import-row-preview`, `portfolio-import-template-hint`, and `portfolio-import-repair-suggestions` for malformed-file guidance, keep `ApiError.detail` available for structured error rendering, and retain the strict-auth browser upload and multi-broker markers for malformed CSV, Eastmoney, HTSC, GTJA, Futu/Moomoo, and Tiger fixtures. The malformed CSV path must prove observed headers, missing required fields, a visible row preview, a broker-template confidence hint, and broker-specific repair suggestions before moving on to valid imports. The strict-auth browser flow also verifies `new-task-portfolio-risk-preflight` before creating the portfolio-backed run, including `Portfolio risk`, `Pre-task holding risk prompt`, broker-template context, and a concrete holding or concentration/loading note. After the same run reaches Final Writer, the strict-auth flow verifies Dashboard and Final Writer source freshness sections (`dashboard-source-freshness` and `final-writer-source-freshness`), then opens `/audit`, verifies `GET /api/analysis/runs/{run_id}/audit` uses Bearer auth, and requires a visible run lifecycle audit event.
Portfolio snapshot write coverage also requires `/portfolio` to keep sample creation, manual snapshot creation, and file-import submit behind the shared `researcher+` browser role boundary, while delete remains `admin`. Keep `PortfolioPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'admin')`, `portfolio-write-role`, `portfolio-write-disabled-reason`, `portfolio-create-sample`, `portfolio-create-manual`, `portfolio-import-submit`, and handler-level `if (!canWritePortfolioSnapshots)` short-circuits guarded by `smoke:frontend`. Snapshot listing, malformed-file diagnostics, broker-template context, and New Task handoff links remain visible without write permission.
It also guards Data Compression response contracts before `/data-compression` stores evidence-compression payloads: `dataPipelineClient` must keep `assertCompressionOverview()`, `assertDataQualityScore()`, `assertDataFingerprint()`, `assertRunCompressionSummary()`, `assertKnowledgeDistillationGroup()`, string-array checks for fingerprint keys, guardrail/evidence summaries, item ids, and shared tags, numeric retention-action checks, `.then(...)` wiring, and `/data-pipeline/overview`, `/data-pipeline/runs/${runId}/quality`, `/summary`, `/compress`, and `/data-pipeline/knowledge/distill` endpoint markers. This guard is frontend response validation only; it must not change compression write-back, retention policy, or Knowledge distillation decisions.

Data Compression write-back coverage requires `/data-compression` to keep `compressRun()` behind the shared `researcher+` browser role boundary. Keep `DataCompressionPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `data-compression-write-role`, `data-compression-write-disabled-reason`, `data-compression-write-summary`, the handler-level `if (!canWriteDataCompression)` short-circuit, and the disabled expression `!selectedRunId || saving || selectedRunCompressed || !canWriteDataCompression` guarded by `smoke:frontend`. Reads, previews, quality scoring, retention display, and Knowledge distillation grouping remain visible without this write permission.
It also guards Case Library client contracts before `/case-library`, `/research-lab/evaluation`, `/research-lab/versions`, Dashboard knowledge-regression cards, promotion, rollback, and delete state consume backend payloads: `caseLibraryClient` must keep response guards and `.then(...)` wiring for case summaries/items, review tags, error ledger rows, knowledge patches, evaluation runs, strategy experiment reports, knowledge versions, post-publish regression metadata, version diffs, rollback results, and delete responses. `smoke:frontend` must keep the guard-name and high-risk endpoint markers. `smoke:strict-auth-browser:platform` should be run for Knowledge Versions and Evaluation Sandbox fixture consumption, and `smoke:strict-auth-browser:research-backtest` should keep the Backtest selected-run route retry plus Agent DAG Bearer API fallback so timing misses do not hide real regressions.
Case Library write coverage also requires `/case-library` to keep case creation, case review saves, review tagging, and patch review/evaluation/promotion behind the shared `researcher+` browser role boundary, while case/error/patch deletes remain `admin`. Keep `CaseLibraryPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'admin')`, `case-library-write-role`, `case-library-write-disabled-reason`, `case-library-create-case`, `case-library-add-tag-`, `case-library-save-review-`, `case-library-approve-with-evaluation-`, `case-library-review-approve-`, `case-library-review-reject-`, `case-library-review-archive-`, and handler-level `if (!canWriteCaseLibraryItems)` short-circuits guarded by `smoke:frontend`. Reading, refreshing, expanding cases, simulation-case display, and delete disabled reasons remain visible without this write permission.
It also guards the standalone Knowledge iteration client before `/knowledge` stores summary or item payloads: `knowledgeClient` must keep `assertKnowledgeSummary()`, `assertKnowledgeItem()`, `assertKnowledgeItemList()`, string-array checks for evidence/guardrail notes/tags, numeric category-count checks, `.then(...)` wiring, and `/knowledge/summary`, `/knowledge/items`, `/knowledge/items/${itemId}/review`, and `/knowledge/from-run/${runId}` endpoint markers. This guard is frontend response validation only; it must not change Knowledge review, archive, active-context, or run-generation policy.

Knowledge iteration write coverage requires `/knowledge` to keep run-derived generation, manual item creation, and pending-item approve/reject behind the shared `researcher+` browser role boundary, while archive/delete remains `admin`. Keep `KnowledgeIterationPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'admin')`, `knowledge-write-role`, `knowledge-write-disabled-reason`, `knowledge-archive-disabled-reason`, `knowledge-generate-from-run`, `knowledge-create-manual`, `knowledge-review-approve-`, `knowledge-review-reject-`, `knowledge-archive-item-`, and handler-level `canWriteKnowledgeItems` / `canArchiveKnowledgeItems` short-circuits guarded by `smoke:frontend`. Reading, filtering, expanding, and refreshing Knowledge items remain visible without write permission.
It also guards Knowledge Versions post-publish regression on the canonical `/research-lab/versions` route: `caseLibraryClient.rerunKnowledgeVersionRegression()` must stay wired to `/case-library/knowledge-versions/${versionId}/regression`, the page must keep stable regression hooks, draft versions must remain non-rerunnable, and `smoke:strict-auth-browser` must keep the Bearer-auth list/rerun assertions plus the `ok strict-auth browser Knowledge Versions post-publish regression` runtime marker. Knowledge Versions write coverage also requires manual draft creation and published regression reruns to stay behind the shared `researcher+` browser role boundary, while rollback remains `admin`. Keep `KnowledgeVersionsPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `roleAllows(operator.role, 'admin')`, `knowledge-version-write-role`, `knowledge-version-write-disabled-reason`, `knowledge-version-rollback-role`, `knowledge-version-rollback-disabled-reason`, `knowledge-version-create-draft`, `knowledge-version-rerun-regression-`, `knowledge-version-rollback-`, handler-level `if (!canWriteKnowledgeVersions)` and `if (!canRollbackKnowledge)` short-circuits, and disabled create/rerun/rollback expressions guarded by `smoke:frontend`. Version listing, diffs, post-publish regression summaries, impact panels, waiver metadata, and rollback disabled reasons remain visible without this write permission.
It also guards Knowledge regression case-set quality visibility and policy: backend reports must keep `case_set_quality`, `case_set_quality_policy`, `case_set_quality_policy.remediation`, and `quality_warnings`; Knowledge Versions must keep the `knowledge-version-regression-quality-`, `knowledge-version-regression-policy-`, and `knowledge-version-regression-remediation-` hooks; Dashboard must merge quality warnings into the Knowledge regression warning list and keep `dashboard-knowledge-regression-quality-policy` plus `dashboard-knowledge-regression-remediation`; and the strict-auth browser fixture must keep the `LOW_COVERAGE`, `Missing modules: 1`, `WARN_ONLY`, `ACTION_REQUIRED`, and `case_library_reviewer` runtime assertions. Dashboard also keeps the Research Lab closed-loop sample entry wired through `dashboard-research-closed-loop-entry` / `dashboard-create-closed-loop-sample`; `smoke:strict-auth-browser` must keep the Bearer-auth `Dashboard Research closed-loop sample creation` assertion, returned run/iteration ID visibility, and the `ok strict-auth browser Dashboard run/provenance/knowledge regression and closed-loop entry` marker.
It also guards Knowledge impact analytics as observation-only metadata: backend post-publish reports must keep `knowledge_impact.policy_id=knowledge_post_publish_impact_summary_v1`, `mode=OBSERVATION_ONLY`, and `auto_blocks_promotion=false`; Knowledge Versions must keep `knowledge-version-regression-impact-`; Dashboard must keep `dashboard-knowledge-regression-impact`; and the strict-auth browser fixture must keep `REGRESSION_ATTENTION`, `OBSERVATION_ONLY`, and `review_regressions_before_policy_trust` visible on `/research-lab/versions`.
It also guards Evaluation Sandbox on the canonical `/research-lab/evaluation` route: `caseLibraryClient.runPatchEvaluation()` and `runPatchStrategyExperiment()` must stay wired to the shared `request()` paths, the page must keep stable patch/evaluation/experiment hooks, and `smoke:strict-auth-browser` must keep the Bearer-auth list, forced evaluation payload, strategy-config payload, rendered evaluation summary, rendered A/B winner, and `ok strict-auth browser Evaluation Sandbox patch evaluation and strategy experiment` runtime marker. Evaluation Sandbox run coverage also requires forced patch evaluation and strategy A/B experiment actions to stay behind the shared `researcher+` browser role boundary. Keep `EvaluationSandboxPage` wired to `useOperatorContext()`, `roleAllows(operator.role, 'researcher')`, `evaluation-sandbox-write-role`, `evaluation-sandbox-write-disabled-reason`, `evaluation-sandbox-run-`, `evaluation-sandbox-experiment-`, handler-level `if (!canRunEvaluationSandbox)` short-circuits, and disabled run/experiment expressions guarded by `smoke:frontend`. Patch/evaluation listing, summaries, history expansion, and rendered experiment reports remain visible without this run permission.
It also guards the Case Library promotion chain: the active `评估+批准` path must run forced patch evaluation, pass `evaluation_id`, call `approvePatchWithEvaluation()`, preserve risk-boundary context, and keep per-patch `case-library-promotion-feedback-` rendering so backend rejection reasons remain visible after a regressed evaluation blocks promotion. Backend `test_evaluation.py` must keep the regression-promotion gate that rejects evaluation evidence with `regressed_cases > 0` before a patch can become an active knowledge version.
Backend `test_evaluation.py` also guards the audited regression-waiver path: incomplete waivers stay rejected, and a complete API-level waiver must carry `allow_regression_override=true`, `regression_override_approval_id`, `regression_override_approver_role=admin`, and a bounded reason, then persist `approval_record.regression_waiver` plus a `regression_waiver` evidence ref. Knowledge Versions must keep the `knowledge-version-regression-waiver-` hook, render `approval_record.regression_waiver` metadata on `/research-lab/versions`, and the strict-auth browser fixture must keep the `WAIVER-BROWSER-001`, `knowledge_promotion_regression_waiver_v1`, and `AUDITED_OVERRIDE` runtime assertions.
It also guards Plugin artifact retention cleanup dry-run against regressing to static-only coverage: `smoke:strict-auth-browser` must keep the cleanup endpoint POST, Bearer assertion, `dry_run=true` payload assertion, `DRY_RUN` response counters, `plugin-artifact-cleanup-result` rendering, and the `ok strict-auth browser Plugin artifact cleanup dry-run` runtime marker.
It also guards Backtest research validation, parameter-scan, experiment-package, and Research verdict-input linkage: `BacktestPage` must keep the research-grade score panel, validation protocol panel, data-package hash display, parameter-scan submit button, parameter-scan async job button/status/cancel/handoff controls, handoff status panel, handoff custody panel/refresh button, parameter-scan result notice, retained parameter-scan history, experiment-package download button, Backtest -> verdict-inputs button, and verdict-inputs notice; `backtestClient` must keep `createBacktestParameterScan()` wired to `/research/backtest/parameter-scan`, `createBacktestParameterScanJob()` / `getBacktestParameterScanJob()` / `cancelBacktestParameterScanJob()` / `handoffBacktestParameterScanJob()` wired to `/research/backtest/parameter-scan/jobs`, `listBacktestParameterScans()` wired to `/research/backtest/parameter-scans`, and `getBacktestExperimentPackage()` wired to `/research/backtest/runs/{run_id}/experiment-package`; `BacktestParameterScanJob`, `BacktestParameterScanJobAttempt`, and `BacktestParameterScanJobHandoff` must keep idempotency, local lease, dynamic handoff status, checksum, and manifest fields; `researchClient` must keep `createResearchBacktestVerdictInputs()` wired to `/research/backtest/runs/{run_id}/verdict-inputs`, Research Lab backtest links must use `researchBacktestPath()` to preserve `iteration_id`, Research Lab SignalOps links must preserve the selected signal from single/plural metrics or `SIGNALOPS` evidence links, and `smoke:strict-auth-browser` must keep the `Backtest experiment package download`, `Backtest parameter-scan validation protocol`, `Backtest parameter-scan async job`, `Backtest parameter-scan handoff`, `Backtest parameter-scan handoff custody`, `Research Backtest verdict inputs`, and `Research SignalOps selected deep link` runtime markers.

Backtest research-validation detail coverage requires `BacktestPage` to keep `backtest-validation-detail`, `backtest-validation-out-of-sample`, `backtest-validation-benchmark`, `backtest-validation-parameter-scan`, `backtest-validation-package-hashes`, `backtest-validation-required-components`, `backtest-parameter-scan-history`, and `backtest-parameter-scan-history-open-best`. `smoke:strict-auth-browser` must continue asserting the parameter-scan path renders the OOS window, walk-forward mode, benchmark symbol/type/source, scan id, package hashes, required research-grade components, and retained scan-history row before printing `ok strict-auth browser Backtest parameter-scan validation protocol`.

### P1 配置安全 smoke

用于修改 LLM/行情 API Profile、`base_url` 提示、API Key 输入或生产配置文档后：

```powershell
npm.cmd run build
npm.cmd run test:backend -- backend\tests\test_http_auth.py backend\tests\test_agent_runtime.py -q
```

`backend\tests\test_http_auth.py` includes full-app ASGI boundary regressions for `GET /api/agents/runtime` response redaction and SignalOps strict-auth simulation/live-disabled config/status behavior. Keep these in the P1 security smoke when changing runtime public DTOs, auth middleware, or SignalOps automation boundaries.

Launcher guardrail: `start-dev.ps1 -Install` must not silently remove an existing broken `backend\.venv`. Use `.\start-dev.ps1 -Install -RecreateBackendVenv` only when intentionally replacing that backend virtualenv. `backend\tests\test_repo_hygiene.py` statically guards this behavior.

Architecture guardrail: `backend\tests\test_repo_hygiene.py` scans lower backend layers (`backend/app/core`, `backend/app/modules`, `backend/app/db`, and `backend/app/models`) for both normal imports and dynamic string references to API route modules (`app.api`, `backend.app.api`, `routes_analysis`, and `routes_*`). Keep route modules above services; do not reintroduce lower-layer dependencies on `backend/app/api/routes_*`.

人工检查 `/settings`：

- Agent runtime 顶部应显示 LLM Base URL、行情 Base URL、Key 与配置 audit 三个状态卡。
- 使用内置 provider 端点时显示预设可信或本地预设；输入非预设远程 LLM `base_url` 时应显示自定义风险，并要求勾选白名单/审批确认后才能保存、应用或真实连通测试，即使该 profile 暂未配置 API Key。
- 输入非预设行情 `base_url` 或绝对 `quote_path` 时应显示自定义风险；生产 strict 模式下只有 `MARKET_DATA_BASE_URL_ALLOWLIST`/`MARKET_DATA_EGRESS_ALLOWLIST`/`MARKET_DATA_ALLOWED_HOSTS` 能放行，前端确认不能绕过后端策略。
- API Key/Token 输入框只应是 password；后端已保存状态只显示 `api_key_set` 和脱敏 mask；页面不应提供“保存到本机历史”或从 localStorage 回填明文 Key 的入口。
- 生产 strict 配置必须保留 `APP_ENV=production`、`API_AUTH_MODE=strict`、`API_WRITE_TOKEN` 或 `SUPER_API_WRITE_TOKEN`；自定义 `base_url` 的验收记录不得包含明文 Key，并应记录是否由 LLM 或 Market Data allowlist 放行。

Latest verified result on 2026-05-20:
- `npm.cmd run build`: passed.
- `npm.cmd run test:backend -- backend\tests\test_http_auth.py backend\tests\test_agent_runtime.py -q`: `22 passed, 4 warnings`. The sandboxed run timed out during first-time dependency downloads; rerunning the same command outside the sandbox completed.

### 后端测试

统一入口：

```powershell
npm.cmd run test:backend
```

该命令通过 `scripts/test-backend.ps1` 设置 workspace-local `UV_CACHE_DIR`，绕过损坏的 root `.venv`；同时把 `TEMP` / `TMP` 指向系统临时目录下的 `tianyuan-quant-agent-ui` 子目录，避免 OneDrive 工作区内的 `uv-trampoline-*.exe` 临时文件锁导致预合并门禁误失败。若仓库内 `.uv-cache` 被 OneDrive 或文件扫描器锁住，可临时设置 `TIANYUAN_UV_CACHE_DIR=C:\tmp\super-uv-cache` 后重跑同一命令；未设置时默认行为不变。默认执行 P0/运行基线和高风险模块参与度核心套件：

```powershell
backend\tests\test_http_auth.py
backend\tests\test_config_routes.py
backend\tests\test_agent_runtime.py
backend\tests\test_analysis_workflow.py
backend\tests\test_analysis_lifecycle_core_services.py
backend\tests\test_analysis_run_compare.py
backend\tests\test_mfe_mae_quant_core_chain.py
backend\tests\test_market_data_runner.py
backend\tests\test_market_data_adapter.py
backend\tests\test_data_reliability_routes.py
backend\tests\test_portfolio_store.py
backend\tests\test_auto_paper_trading.py
backend\tests\test_auto_paper_routes.py
backend\tests\test_signalops_lifecycle_store.py
backend\tests\test_signalops.py
backend\tests\test_signalops_routes.py
backend\tests\test_backtest_engine.py
backend\tests\test_backtest_signalops_sample.py
backend\tests\test_backtest_store.py
backend\tests\test_research_store.py
backend\tests\test_research_artifact_store.py
backend\tests\test_research_verdict_store.py
backend\tests\test_evaluation.py
backend\tests\test_plugin_store.py
backend\tests\test_plugin_runtime.py
backend\tests\test_analysis_job_sqlite.py
backend\tests\test_analysis_job_reconciliation.py
backend\tests\test_observability_routes.py
backend\tests\test_repo_hygiene.py
```

如需只跑部分测试，可把 pytest 参数传给脚本：

```powershell
.\scripts\test-backend.ps1 backend\tests\test_http_auth.py -q
```

如需全量后端回归：

```powershell
npm.cmd run test:backend:all
```

全量命令会执行 `backend\tests -q`，首次运行可能需要较长时间同步 AkShare、pandas、numpy 等依赖。

### 2026-05-20 closure verification

Use this suite after changes touching the 2026-05-20 closed P0-P3 backlog work. The old `OPEN_DEVELOPMENT_BACKLOG.md` file has been removed; closure evidence is retained in `DEVELOPMENT_LOG.md`. The local root `.venv` launcher may be broken on Windows, so prefer the unified backend test entry or `uv run` with a workspace-local cache.

```powershell
$env:UV_CACHE_DIR=(Resolve-Path .\.uv-cache).Path
uv run python -m pytest backend\tests\test_http_auth.py backend\tests\test_agent_runtime.py backend\tests\test_market_data_adapter.py backend\tests\test_backtest_store.py backend\tests\test_research_store.py backend\tests\test_technical_kline_agent.py backend\tests\test_plugin_store.py backend\tests\test_plugin_runtime.py backend\tests\test_evaluation.py backend\tests\test_analysis_workflow.py backend\tests\test_analysis_run_compare.py backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q
```

Latest verified result on 2026-05-20: `115 passed, 736 warnings`.

After cross-module frontend changes, run the active frontend build:

```powershell
npm.cmd run build
```

Browser smoke for this backlog closure covered `/plugins`, `/research-lab/evaluation`, `/research-lab/versions`, `/settings`, and `/data-reliability`; all loaded without console errors.

### SignalOps 自动模拟交易 focused tests

```powershell
$env:UV_CACHE_DIR=(Resolve-Path .\.uv-cache).Path
uv run python -m pytest backend\tests\test_analysis_workflow.py backend\tests\test_analysis_run_compare.py backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q
```

2026-05-20 current note: root `.venv` and `backend/.venv` may report `Unable to create process` for pytest. Use `uv` with a workspace-local cache so the command does not depend on the broken venv launchers.

```powershell
$env:UV_CACHE_DIR=(Resolve-Path .\.uv-cache).Path
uv run python -m pytest backend\tests\test_auto_paper_trading.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_signalops.py -q
```

Decision tree focused checks are part of `backend\tests\test_auto_paper_trading.py` and cover low confirmation, active branch creation, non-ending single conditions, lifecycle close, review generation, tuning caps, and simulation-only flags.

```powershell
npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py -q
npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_signalops.py -q
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Latest verified results:
- 2026-06-01 Agent DAG viewport/node/failure interaction follow-up: `node --check scripts\smoke-strict-auth-browser.mjs`, `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run smoke:frontend`, `npm.cmd run build`, and `npm.cmd run smoke:strict-auth-browser` passed after making the DAG ReactFlow view read-only and adding zoom/fit controls, pane drag/pan, mouse-click, multi-node keyboard selected evidence, deterministic LLM degraded/failed fixture coverage, and deterministic source-classification state matrix coverage; the strict-auth browser output included `ok strict-auth browser Agent DAG viewport controls`, `ok strict-auth browser Agent DAG viewport pan`, `ok strict-auth browser Agent DAG node interaction`, `ok strict-auth browser Agent DAG multi-node keyboard interaction`, `ok strict-auth browser Agent DAG failure/degraded fixture`, and `ok strict-auth browser Agent DAG state matrix fixture`.
- 2026-05-27 SignalOps decision tree: `.\.venv\Scripts\python.exe -m py_compile backend\app\core\signalops_decision_tree.py backend\app\core\auto_paper_trading.py backend\app\core\signalops_store.py backend\app\models\auto_paper_trading.py backend\app\api\routes_auto_paper_trading.py backend\tests\test_auto_paper_trading.py` passed; `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py -q` passed with `57 passed`; `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_signalops.py -q` passed with `76 passed`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed. In-app browser automation was blocked by the local sandbox, so smoke fallback confirmed `/signalops required text`.
- 2026-05-24 SignalOps K-line gate hardening: `.\.venv\Scripts\python.exe -m py_compile backend\app\core\kline_signal_quality.py backend\app\core\auto_paper_trading.py backend\app\models\auto_paper_trading.py` passed; `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q` passed with `55 passed`; SignalOps focused regression passed with `74 passed`; Backtest/Research focused regression passed with `72 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed, including `ok /signalops required text`. K-line unavailable/empty data now blocks simulated buys, K-line invalidation overrides LLM/manual open decisions, and cached snapshots are reused until refresh intervals expire.
- 2026-05-24 SignalOps strategy stability gate: `.\.venv\Scripts\python.exe -m py_compile backend\app\core\strategy_stability_quality.py backend\app\core\auto_paper_trading.py backend\app\core\backtest_store.py` passed; `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_backtest_store.py -q` passed with `71 passed`; SignalOps focused regression passed with `78 passed`; Backtest/Research focused regression passed with `76 passed, 4 warnings`; `npm.cmd run test:backend -- backend\tests\test_kline_service.py -q` passed with `4 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed. Stability scoring now limits high-volatility regimes, can block meta-label-negative simulated buys, adds triple-barrier validation fields, and preserves public SignalOps backtest `metadata_json.source`.
- 2026-05-23 SignalOps experiment validation gate hardening: `npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_auto_paper_routes.py backend\tests\test_auto_paper_trading.py -q` passed with `62 passed`; SignalOps focused regression passed with `65 passed`; Backtest/Research focused regression passed with `72 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed. The experiment runner now requires independent benchmark data for external benchmarks, records `experiment_validation_state`, exposes review queue sync warnings, and drops cleaned-history replay records without explicit in-window `signal_date`.
- 2026-05-22 SignalOps reproducible experiment loop: `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py backend\tests\test_backtest_store.py -q` passed with `58 passed`; SignalOps focused regression passed with `64 passed`; Backtest/Research focused regression passed with `69 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed. Daily review now emits `BACKTEST_PENDING` until `POST /backtest/signalops-experiment` validates the candidate package; frontend smoke checks experiment hash, Benchmark, Research package, `SUPERSEDED`, and `EXPIRED` text.
- 2026-05-22 SignalOps review hardening follow-up: `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q` passed with `43 passed`; full SignalOps focused regression passed with `62 passed`; Backtest/Research focused regression passed with `67 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed.
- Review approval regressions now cover two failure-prone paths: blocked approval must not mutate `review_queue_state`, and malformed candidate thresholds/position ratios are clamped before `APPLIED_TO_SIMULATION`.
- 2026-05-22 SignalOps persistent review queue: SignalOps focused backend regression passed with `60 passed`; Backtest/Research focused regression passed with `67 passed, 4 warnings`; `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` passed. Frontend smoke now also checks `/signalops` built assets for review queue labels plus `READY_FOR_REVIEW` and `APPLIED_TO_SIMULATION`.
- SignalOps review-queue contract: `cleaned_record_history` records are normalized with `record_id`, `signal_date`, `source_type`, `source_id`, `decision_id`, `outcome`, `sample_quality`, and `evidence_refs`; LOW / SUPPORTING_ONLY evidence cannot promote candidates. Daily review emits `BACKTEST_PENDING` for candidate packages, `READY_FOR_REVIEW` requires the dedicated SignalOps Backtest experiment, and `APPLIED_TO_SIMULATION` requires `POST /signalops/auto-paper/review-decisions`.
- 2026-05-22 SignalOps intelligent review loop: SignalOps focused backend regression passed with `56 passed`; Backtest/Research focused regression passed with `67 passed, 4 warnings`; `npm.cmd run lint`, `npm.cmd run typecheck`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` all passed.
- Current `/signalops` review-queue smoke: route smoke returned `ok /signalops`, `http://127.0.0.1:5174/signalops` returned HTTP 200, and built assets contain `审查队列`, `待审查`, `审查卡`, `通过审查`, `驳回建议`, `继续观察`, `要求补丁`, `系统自动运行，人只审查`, `仅模拟：是`, and `真实交易：否`.
- Playwright CLI DOM verification for the review queue was not run in this pass because sandbox escalation for executing `@playwright/cli` was rejected by security policy.
- 2026-05-22 SignalOps win-quality gate: `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py -q` passed with `34 passed`.
- 2026-05-22 SignalOps focused regression: `npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_signalops.py -q` passed with `56 passed`.
- 2026-05-22 frontend checks: `npm.cmd run lint`, `npm.cmd run typecheck`, `npm.cmd run build`, and `npm.cmd run smoke:frontend` all passed; route smoke included `/signalops`.
- SignalOps win-quality semantics: `performance_stats` stores rolling global/symbol/factor/trigger buckets; wins require `pnl_rate > 1%` and no invalidation; no-trade samples are counted separately and never as wins.
- Daily tuning now emits `recommended_parameters`, `applied_parameters`, `application_status`, `application_reason`, and `performance_summary`. Config mutation only happens when trade count, evidence weight, confidence, and directional support pass the conservative gate; otherwise the review is recommendation-only.
- Browser DOM verification on `http://127.0.0.1:5174/signalops` confirmed the labels `win-quality panel`, `rolling win rate`, `trade samples`, `expectancy`, `factor ranking`, and `low-quality triggers`; Playwright reported 0 console errors.
- `backend\tests\test_auto_paper_trading.py -q`: `23 passed` after adding AI 做 T、模拟做空、回补 coverage and short-position command/cash-value regression checks.
- `backend\tests\test_auto_paper_routes.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_research_store.py -q`: `20 passed`.
- `backend\tests\test_auto_paper_trading.py backend\tests\test_signalops_lifecycle_store.py backend\tests\test_research_store.py -q`: `34 passed` for SignalOps x Research Lab daily paper-review tuning.
- `backend\tests\test_analysis_workflow.py backend\tests\test_analysis_run_compare.py backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q`: `27 passed`.
- Previous legacy SignalOps focused suite: `29 passed`.

Do not use the old Coze SignalOps bridge test command; the Coze-facing bridge is no longer an active surface.

2026-05-21 current note: SignalOps 主入口已收敛为 AI 全自动托管。浏览器 smoke 应检查：

- `AI 全自动托管`
- `股票代码`
- `最初买入信号`
- `最终卖出信号`
- `加入并启动 AI 托管`
- `高级资金和运行参数`
- `A 股规则：T+1 已启用`
- `股市交易手续费`
- `佣金率（%）` 默认 `0.01`
- `最低手续费（元）` 默认 `5`
- `最低计费金额（元）` 默认 `50000`
- `卖出印花税（%）` 默认 `0.05`
- 股票池行默认展示 `AI 托管`，强制开仓/平仓/移出只在 `人工接管` 折叠区出现。
后端回归应覆盖：同日 `SIM_BUY` 后触发 `SIM_T_SELL` 时返回 `a_share_t_plus_one_blocked`，隔日持仓允许卖出；自动下单在非交易时段返回 `a_share_trading_session_closed`，强制跟进只作为模拟覆盖；接近涨停阻断买入/回补、接近跌停阻断卖出/开空；无长仓卖出返回 `no_long_position_to_reduce`；买入自动成交的 `simulated_fill.fees` 默认低于 5 万元为 `5`，卖出自动成交需额外计入 `stamp_duty_fee` 和 `total_fee`。

如果测试环境仍出现 `Unable to create process`，至少先运行语法 smoke、`npm.cmd run lint`、`npm.cmd run build` 和浏览器 smoke，并在交付说明里标明 pytest 被本地 Python/uv 启动器阻断。

### SignalOps 语法 smoke

```powershell
$env:UV_CACHE_DIR=(Resolve-Path .\.uv-cache).Path
uv run python -m py_compile backend\app\core\auto_paper_trading.py backend\app\core\signalops_store.py backend\app\main.py
```

### 浏览器 smoke

- 打开 `http://localhost:5174/signalops`。
- 应看到 `AI 全自动托管`、`股票代码`、`最初买入信号`、`最终卖出信号`、`加入并启动 AI 托管`、`高级资金和运行参数`。
- 不应看到旧的 `信号资产` 侧栏、`从当前 run 沉淀`、手动条件保存入口 `保存条件` 或固定条件选项 `放量突破关键区间`。

- 2026-05-19 additionally confirm `立即跟进`, `最小模拟订单金额`, `K线刷新间隔秒`, `周/月线刷新间隔秒`, `最小下单间隔秒`, `启用 LLM 判断`, and `自动撮合 SIM 订单` are visible.
- 2026-05-20 additionally confirm the status panel shows `RUNNING`/`STOPPED`, recent heartbeat, next tick, seconds left, and latest tick partial/error details.
- 2026-05-20 SignalOps x Research Lab update: confirm `收盘复盘`, `买入阈值`, `失效阈值`, and `Research 复盘` are visible on `/signalops`.
- 2026-05-20 order detail update: confirm `AI 自动交易细节` shows `最近一次` by default and historical SIM actions are under the collapsed `其他交易细节` section.
- 2026-05-20 console/action update: confirm `SignalOps 控制台`, `AI 开仓`, `强制平仓`, `平仓移除`, `选入控制台`, `AI 自动判断做T / 做空 / 回补 / 仓位比例`, and the paper action labels `模拟做T买回`, `模拟做T卖出`, `模拟做空`, `模拟回补` are visible when corresponding data exists.
- 2026-05-20 simplified UI update: confirm `自动模拟控制台`, `长期配置`, `低频修改`, `加入股票池`, and `交易明细` are visible; long-lived global parameters such as pool cash, refresh intervals, LLM budget, minimum order value, and auto-fill are grouped under `#signalops-long-config`.
- 2026-05-20 save-mode regression: typing a draft stock code should only be consumed by `加入股票池`; `启用`/`停止` and `保存自动设置` must not append that draft code to the stock pool or clear it.

### SignalOps 状态 API smoke

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/signalops/auto-paper/status
```

## Subagent 续作

历史 backlog 文档已删除，不再作为当前计划或归档入口。当前开发、验证和闭环状态以 [PROJECT_DEVELOPMENT_ASSESSMENT.md](./PROJECT_DEVELOPMENT_ASSESSMENT.md)、[QUANT_SYSTEM_IMPROVEMENT_PLAN.md](./QUANT_SYSTEM_IMPROVEMENT_PLAN.md)、[DEVELOPMENT_GUIDE.md](./DEVELOPMENT_GUIDE.md) 和 [DEVELOPMENT_LOG.md](./DEVELOPMENT_LOG.md) 为准。

---

## 旧手工清单处理

旧的根级完整运行清单和本文件尾部的手工勾选项已经退役。它们仍引用 legacy analyze 接口、旧 Agent 数量、旧表级断言和直接 pytest 调用，与当前 `npm.cmd` 脚本、10 Agent 注册表、Phase 1-3 闭环验收和 strict-auth browser smoke 不一致。

当前检查入口以本文上方命令矩阵为准：

- 后端聚焦回归：`npm.cmd run test:backend -- <paths> -q`
- 前端静态和类型：`npm.cmd run typecheck`、`npm.cmd run lint`、`npm.cmd run build`
- 路由和弱链：`npm.cmd run smoke:frontend`
- 闭环浏览器：`npm.cmd run smoke:research-closure:browser`
- strict-auth 分组：`npm.cmd run smoke:strict-auth-browser:<group>`
- Phase 0 基线：`npm.cmd run audit:baseline`
