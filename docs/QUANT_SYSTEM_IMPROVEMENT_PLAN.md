# 量化系统完善开发计划

Current follow-up note (2026-06-04): Knowledge Versions rollback now has explicit browser-visible admin role evidence. `/research-lab/versions` renders `knowledge-version-rollback-role` and `knowledge-version-rollback-disabled-reason`, gives rollback controls stable `knowledge-version-rollback-*` hooks, and routes viewer/operator attempts through the same admin disabled reason before any rollback call. Typecheck, `smoke:frontend`, lint, build, repo hygiene, and `smoke:strict-auth-browser:platform` passed. This closes a UI consistency gap only; backend strict auth, Knowledge rollback semantics, regression/waiver governance, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-04): Plugin Registry lifecycle and artifact admin actions now have explicit browser-visible role evidence. `/plugins` renders `plugin-lifecycle-action-role` and `plugin-lifecycle-action-disabled-reason`, applies the same disabled reason to toggle/archive/upgrade/upload/cleanup controls, and short-circuits those handlers when the current role is not `admin`. Typecheck, `smoke:frontend`, lint, build, repo hygiene, and `smoke:strict-auth-browser:portfolio-live-plugin` passed. This closes a UI consistency gap only; backend strict auth, plugin audit/lifecycle/artifact APIs, sandbox policy, read-only/no-code defaults, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-04): Config Versions approved restore now has explicit browser-visible admin role evidence. `/config-versions` renders `config-approved-restore-role` and `config-approved-restore-disabled-reason`, adds the same disabled reason to the approved restore opener, and keeps governed modal submission blocked when the current role is not `admin`. Typecheck, `smoke:frontend`, lint, build, repo hygiene, and `smoke:strict-auth-browser:platform` passed. This closes a UI consistency gap for an existing high-risk restore action only; `/api/config/external-restore`, approval id/reason/secret-safe checks, Agent Runtime surface-scoped restore behavior, strict auth, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-04): Research Lab P2 closed-loop secondary controls now show and enforce the same frontend role-boundary evidence as the main Research workflow actions. The guide panel disables secondary create/materialize options for non-`researcher+` roles, renders `research-closed-loop-secondary-disabled-reason`, and is guarded by `smoke:frontend` together with the main `research-lab-workflow-role` hooks. This closes a UI consistency gap only; backend Research APIs, strict auth, verdict/evidence gates, SignalOps/Backtest bridges, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-04): Dashboard now has an explicit decision-workbench read model and startup readiness no longer waits on slow market-data status before reporting core READY. `/analysis/runs/{run_id}` returns additive `dashboardSummary.schema=analysis_dashboard_summary_v1` with trade-boundary flags, evidence score, source/agent counts, blockers, warnings, and next-review rows; `/` renders these through stable Dashboard hooks and strict `simulationOnly=true` / `isRealTrade=false` copy. Analysis run lists keep using the summary index and only reconcile loaded/recoverable rows, while detail reads reconcile only the requested run. Startup warmers run local optional components concurrently and mark `market_data_status` as a deferred degraded component if it fails or times out. SignalOps also compresses generated automation noise by hiding `P2_CLOSED_LOOP_SAMPLE` rows from normal selectors and separating auto-paper signals from lifecycle history. Remaining future work is broader browser E2E around complex cross-page state, plus deployment-owned market-data monitoring and external worker infrastructure; this pass does not introduce broker connectivity, order routing, or real-trade execution.

Current follow-up note (2026-06-03): Ready checks and Plugin sandbox actor attribution now close another review-document stability gap. `/api/ready` keeps dependency status useful while redacting local database/storage paths and raw exception text from browser-visible output. Plugin sandbox run/preview audit actors now come from `current_operator()` instead of client payload fields, and the Plugin Registry frontend no longer sends an actor override. Focused tests, typecheck, lint, build, and frontend smoke passed; plugin sandbox policy, observations, strict auth, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-03): SignalOps and Backend Status now expose browser-visible role evidence for their remaining high-risk handoff/control surfaces. `/signalops` renders review-event export role/disabled-reason hooks plus lifecycle-write, manual-control, and runtime-config role evidence; lifecycle writes remain `researcher+`, manual controls and signed review-event verify/handoff remain `operator+`, and runtime config writes remain `admin`. `/backend` renders production-alert dispatch/handoff admin evidence and ops-log handoff evidence while leaving sanitized export/query reads available. Focused DOM checks with system Chrome verified viewer-role blocks and enabled read-only paths, and `smoke:frontend` guards the static hooks and handler short-circuits. This is frontend UX consistency evidence only; backend strict auth, handoff custody, external provider deployment, and simulation/live-trading boundaries remain unchanged.

Current follow-up note (2026-06-03): Portfolio malformed-file diagnostics now include broker-specific repair suggestions and template-confidence explanations. Failed `/portfolio/imports` responses and failed import jobs carry bounded `observedHeaders`, `matchedFields`, `missingRequiredFields`, `rowPreview`, `brokerTemplateHint`, `templateConfidenceNote`, and `repairSuggestions`; `/portfolio` renders the Futu/Moomoo template hint and repair text through stable hooks before any invalid file can become a snapshot; focused backend tests and strict-auth browser assertions cover both generic malformed input and a Futu/Moomoo malformed broker export. Remaining future work is a larger real-broker export corpus and broker-account connectivity design as a separate governed project. This remains diagnostic file-import UX only and does not create broker connectivity, order routing, or real-trade authority.

Current follow-up note (2026-06-03): Dashboard and Backend Status now consume backend-reported LLM live-call success rate and production trend evidence. `/api/metrics.productionHealth.windows[*].llmCallFailureRate` validates retained `llmTrace` evidence into `successRate`, `failureRate`, redacted `failureReasons`, bounded `sampleFailures`, and token totals; `/api/metrics.productionHealth.windows` includes `24h`, `7d`, and `30d`, `trend` compares 24h-vs-7d, and `longTrend` compares 24h-vs-30d. Dashboard renders the backend success value through `dashboard-llm-live-call-success-rate` and both 7d/30d LLM deltas through `dashboard-llm-live-call-trend`, while Backend Status renders `backend-production-health-trend-deltas` plus the 30d Health Trends row for run success, LLM success/failure, market fallback, and SignalOps tick. Strict-auth browser smoke proves the same Bearer-auth metrics fixture across Dashboard and Backend Status, including visible Dashboard `75.0%`, 7d/30d deltas, Backend Status trend-delta rendering, and the shared redacted LLM failure reason. Remaining future work is broader cross-page complex-state E2E beyond this production-health path plus deployment-owned retention/analytics beyond local 30d windows; this read-only path does not trigger live LLM calls or change simulation/live trading boundaries.

Current follow-up note (2026-06-02): Analysis Job external queue sidecar status now reports provider readiness. `/analysis/jobs/summary.external_queue_status` validates `analysis_job_external_queue_status_v1` from `TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE` / `ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE`, redacts secret-like text, and exposes claim backend/status, idempotency scope, audit stream, DLQ, visibility timeout, and lease-renewal state; `/backend` renders this through `backend-analysis-job-external-queue-readiness`. Remaining future work is still a real external queue broker, broker-backed claims, distributed lease enforcement, retry mutation ownership, and production scheduler operation outside the app.

Current follow-up note (2026-06-02): Data Health external monitoring sidecar status is now visible. `/data-health/snapshot.externalMonitorStatus` validates `data_health_external_monitor_status_v1` from `TIANYUAN_DATA_HEALTH_EXTERNAL_MONITOR_STATUS_FILE` / `DATA_HEALTH_EXTERNAL_MONITOR_STATUS_FILE`, supports BOM-compatible bounded JSON, redacts secret-like text, and exposes provider/backend, freshness, retention, incident counts, latency p95, and search-index readiness; `/data-health` renders this through `data-health-external-monitor-status`. Remaining future work is still actual provider monitor deployment, retention enforcement, alerting, provider search lifecycle, and long-run provenance storage outside the app.

Current follow-up note (2026-06-02): Plugin package external scan sidecars now expose provider-readiness evidence. Upload verdicts under `TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR` / `PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR` support BOM-compatible JSON, secret-like redaction, artifact checksum matching, provider/threat-intel status, signature/engine versions, definitions timestamp, and scan id; Plugin Registry renders provider, threat-intel, signature, engine, and checksum-match evidence. Remaining future work is still actual vendor scanner deployment, live threat-intel feed synchronization, production object-storage lifecycle, and any higher-permission plugin sandbox design.

Current follow-up note (2026-06-02): Production alert outbox deployment shipper sidecar status now reports provider readiness. `/ops/alerts/status.handoff_status.shipper_status` validates `production_alert_outbox_export_shipper_status_v1` from `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR/shipper_status.json`, supports BOM-compatible JSON, redacts secret-like text, matches latest handoff id/checksum, and exposes object key, retention/custody state, KMS key reference, search index, and search readiness; `/backend` renders this through `backend-production-alert-shipper-readiness`. Remaining future work is still actual external upload, centralized provider search ownership, vendor alert delivery, provider retention enforcement, and KMS/object-storage custody outside the app.

Current follow-up note (2026-06-02): Ops Log deployment shipper sidecar status now reports provider readiness. `/ops/logs/status.handoff_status.shipper_status` validates `ops_log_export_shipper_status_v1` from `OPS_LOG_EXPORT_HANDOFF_DIR/shipper_status.json`, supports BOM-compatible JSON, redacts secret-like text, matches latest handoff id/checksum, and exposes object key, retention/custody state, KMS key reference, search index, and search readiness; `/backend` renders this through `backend-ops-log-shipper-readiness`. Remaining future work is still actual external upload, centralized provider search ownership, provider retention enforcement, and KMS/object-storage custody outside the app.

Current follow-up note (2026-06-02): Production alert rule policy now shows deployment-reported provider acceptance status. `/ops/alerts/status.alert_rule_policy.provider_acceptance` validates `production_alert_rule_provider_acceptance_v1` from `PRODUCTION_ALERT_RULE_PROVIDER_ACCEPTANCE_FILE`, redacts secret-like text, and reports policy id/rule-count/rule-id matching against the current app-side alert policy; `/backend` renders accepted/provider/match/rule-count evidence through `backend-production-alert-rule-provider-acceptance`. Remaining future work is still actual vendor rule deployment, centralized alert delivery, provider retention, and KMS/object-storage custody outside the app.

Current follow-up note (2026-06-02): SignalOps signed review-event handoffs now show deployment-reported custody sidecar status. `/signalops/auto-paper/status.review_decision_event_ledger.handoff_shipper_status` reads `AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR/shipper_status.json` with `signalops_review_decision_event_export_shipper_status_v1`, redacts secret-like text, matches handoff id/checksum/latest event hash to the latest local manifest, and `/signalops` renders delivered/search-ready state through `signalops-review-event-export-shipper-status`. Remaining future work is still actual external object storage upload, KMS/legal-hold custody, provider retention/search lifecycle, and compliance storage outside the app.

Current follow-up note (2026-06-02): Backtest parameter-scan handoff artifacts now show deployment-reported custody sidecar status. `GET /api/research/backtest/parameter-scan/jobs/{job_id}.handoffStatus` reads `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR/shipper_status.json` with `backtest_parameter_scan_job_handoff_shipper_status_v1`, redacts secret-like text, matches the sidecar to the latest local manifest/checksum/job/scan, and `/research-lab/backtest` renders delivered/search-ready state through `backtest-parameter-scan-job-handoff-custody`. Remaining future work is still actual external object storage upload, KMS/legal-hold custody, provider retention/search lifecycle, and distributed queue ownership.

Current follow-up note (2026-06-02): Backend Status now exposes local structured ops-log query before external aggregation. `/ops/logs/status` advertises `ops_log_query_v1`, `/ops/logs/query` filters sanitized events by level/type/source/text/since, and `/backend` provides `backend-ops-log-query-*` controls with strict-auth browser coverage. This narrows the local searchability gap but remains app-local JSONL diagnostics; real centralized log search, provider retention, remote index lifecycle, and KMS/object-storage custody still belong to deployment.

Current follow-up note (2026-06-02): Production alert outbox events now include alert rule/routing metadata. `/ops/alerts/status.alert_rule_policy` exposes `production_alert_rule_policy_v1`, default severity rules, optional sanitized `PRODUCTION_ALERT_RULE_POLICY_FILE` mappings, and `/backend` renders `backend-production-alert-rule-policy`; dispatch/export/handoff preserve event rule id, routing key, escalation target, dedupe window, source, and provider evidence. Remaining future work is still real vendor rule deployment, provider-side acceptance/retention, centralized alert delivery, and KMS/object-storage custody.

Current follow-up note (2026-06-02): Backend Status now shows read-only analysis job external queue sidecar status. `/analysis/jobs/summary.external_queue_status` validates `analysis_job_external_queue_status_v1` from `TIANYUAN_ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE` / `ANALYSIS_JOB_EXTERNAL_QUEUE_STATUS_FILE`, redacts secret-like text, and `/backend` renders provider, queue, worker, pending/running, lease backend, and `LOCAL_JSON_SQLITE_DIAGNOSTIC` local-mode evidence. Remaining future work is still a real external queue broker, distributed lease enforcement, cross-host concurrency limits, and production scheduler ownership.

Current follow-up note (2026-06-02): Backend Status now shows read-only deployment shipper sidecar status. `/ops/logs/status.handoff_status.shipper_status` and `/ops/alerts/status.handoff_status.shipper_status` read deployment-written `shipper_status.json`, validate the expected sidecar schemas, redact secret-like values, and report whether the sidecar handoff id/checksum matches latest local inventory. Remaining future work is still real external upload, centralized log/search, vendor alert rules, provider retention, and KMS/object-storage custody.

Current follow-up note (2026-06-02): Backend Status now shows local handoff inventory integrity. `/ops/logs/status.handoff_status.inventory` and `/ops/alerts/status.handoff_status.inventory` scan generated manifest/bundle pairs, verify schema and checksum consistency, expose verified/missing/mismatch counts, and `/backend` renders the counts after handoff actions. Remaining future work is still real shippers, centralized log/search, vendor alert rules, provider retention, and KMS/object-storage custody.

Current follow-up note (2026-06-02): Backend Status now shows deployment handoff readiness before write actions. `/ops/logs/status` and `/ops/alerts/status` expose handoff status schemas, configured destination, expected manifest schema, writability, and create-on-handoff hints; `/backend` renders those rows and strict-auth browser smoke checks the visible destination/schema path. Remaining future work is still real shippers, centralized log/search, vendor alert rules, provider retention, and KMS/object-storage custody.

Current follow-up note (2026-06-02): Production alert exports now include a deployment-side handoff input. `POST /api/ops/alerts/export/handoff` writes the sanitized alert export bundle and `production_alert_outbox_export_handoff_manifest_v1` under `PRODUCTION_ALERT_EXPORT_HANDOFF_DIR`; `/backend` exposes an admin-only handoff button and strict-auth browser smoke checks `HANDED_OFF`, manifest custody, and checksum rendering. Remaining future work is still vendor alert rules, centralized alert delivery, long-term provider retention, and KMS/object-storage custody.

Current follow-up note (2026-06-02): Ops log exports now include a deployment-side handoff input. `POST /api/ops/logs/export/handoff` writes the sanitized export bundle and `ops_log_export_handoff_manifest_v1` under `OPS_LOG_EXPORT_HANDOFF_DIR`; `/backend` exposes an admin-only handoff button and strict-auth browser smoke checks `HANDED_OFF`, manifest custody, and checksum rendering. Remaining future work is still centralized log search, vendor retention, object-store custody, and real external log delivery.

Current follow-up note (2026-06-02): Backtest parameter-scan async jobs now include a deployment-side handoff input for completed scan artifacts. `POST /api/research/backtest/parameter-scan/jobs/{job_id}/handoff` requires completed simulation-only scan evidence, then writes a checksum-bound bundle and manifest under `BACKTEST_PARAMETER_SCAN_HANDOFF_DIR`; strict-auth browser smoke checks the page button, `HANDED_OFF`, manifest custody, and simulation/live boundary. Remaining future work is still external object storage/KMS custody plus a true external queue/worker lease model if long-window scans need production scheduling.

Current follow-up note (2026-06-02): Backtest parameter-scan async jobs now include stable idempotency keys, retained attempt accounting, and a local worker lease claim guard. The local durable job surface exposes `idempotencyKey`, `attemptCount`, `currentAttemptId`, `lastAttemptStatus`, `attempts[]`, `leaseOwner`, `leaseId`, `leaseStatus`, and lease timing fields; duplicate local runner claims cannot reuse the same active attempt. Remaining future work is still an external queue/worker lease model with deployment-grade exactly-once guarantees if long-window scans need production scheduling.

Current follow-up note (2026-06-02): SignalOps review decision event exports now have a deployment handoff input. `POST /api/signalops/auto-paper/review-decision-events/handoff` requires a `VALID` signed export, then writes the bundle and `signalops_review_decision_event_export_handoff_manifest_v1` to `AUTO_PAPER_REVIEW_DECISION_EXPORT_HANDOFF_DIR`; `/signalops` exposes `Handoff signed export` and strict-auth browser smoke proves the page path. Remaining future work is still external object storage/KMS custody, but the app now refuses unsigned/tampered handoff bundles.

Current follow-up note (2026-06-02): SignalOps review decision event exports now have app-side verification. `POST /api/signalops/auto-paper/review-decision-events/verify` checks the signed export bundle, and `/signalops` can run `Verify signed export` from the automation log panel; strict-auth browser smoke proves both valid verification and tampered-bundle rejection. Remaining future work is still deployment-owned external retention/KMS if production compliance requires custody outside the app process.

Current follow-up note (2026-06-02): SignalOps review decision event exports now have optional HMAC-SHA256 signatures. Configuring `AUTO_PAPER_REVIEW_DECISION_EXPORT_SIGNING_KEY` makes the append-only export return `export_signature_status=SIGNED` plus a signature block bound to `bundle_checksum`; strict auth now has negative coverage for unauthenticated export reads. Remaining future work is still external/signed retention outside the app process if production compliance requires it.

Current follow-up note (2026-06-02): Backtest parameter-scan async jobs now have local durable recovery. Jobs persist to `backtest_parameter_scan_jobs.json`, active persisted jobs restart as `RECOVERING`, interrupted active attempts are retained as `INTERRUPTED`, and the Backtest page/API expose `LOCAL_DURABLE_JSON`, idempotency, and attempt metadata. Remaining future work is an external queue/worker with leases and exactly-once semantics if long-window scans need production scheduling; this local surface remains simulation-only research orchestration.

Current follow-up note (2026-06-02): SignalOps review checksum history now survives bounded JSON-state rotation through a local append-only event ledger. Review decisions append `signalops_review_decision_event_v1` records with event hash, previous-event hash, parameter diff checksum/summary, and simulation-only flags; `/api/signalops/auto-paper/review-decision-events` exports a bounded bundle with a bundle checksum for cross-deployment comparison. Remaining future work is external/signed compliance storage if production governance requires it.

Current follow-up note (2026-06-02): SignalOps review approvals/rejections now retain a compact parameter-diff audit snapshot. Each review decision carries `parameter_diff_summary`, `parameter_diff_checksum`, reviewed counts, and a matching queue-item `reviewed_parameter_diff_checksum`, so future review can tie a decision to the exact candidate delta that was approved or rejected without changing promotion gates or simulation-only boundaries.

Current follow-up note (2026-06-01): Backtest bounded parameter scans now have a retained scan-history surface. `GET /api/research/backtest/parameter-scans` groups generated trial runs by `parameters.parameter_scan.scanId`, returns best-run/trial/score/simulation-boundary metadata, and `/research-lab/backtest` renders the history with an "Open best run" action. 2026-06-02 follow-up: bounded scans now accept retained multi-window trial orchestration, and the Backtest page sends/displays derived full/validation windows plus a local async parameter-scan job entry. This closes the local in-process multi-window and operator-responsiveness gap; external long-window workers remain future work.

Current follow-up note (2026-06-03): Portfolio broker-template coverage now includes Eastmoney, HTSC, Guotai Junan / GTJA, Futu/Moomoo, and Tiger file-export fixtures, plus malformed-file diagnostics. Backend parsing maps common spaced/symbolic English headers into normalized holdings, including `Stock Code`, `Available to Sell`, `Average Cost`, and `P&L`; focused tests persist `brokerTemplateId=futu` and `brokerTemplateId=tiger`; failed imports now persist `importError` with reason/job id/expected columns; and strict-auth browser smoke first verifies malformed CSV `NO_VALID_HOLDING_ROWS` guidance, then uploads all five fixtures through `/portfolio` before continuing the Portfolio -> New Task risk-preflight -> Live Run chain. This remains file import/template parsing only, not broker account connectivity or real-trade execution.

Current follow-up note (2026-06-01): Data Health adapter/source checks now write local `DataAdapterEventDB` events and expose them through `/data-health/snapshot`, `/data-health/events`, and the `/data-health` page. This turns the existing adapter-event schema into an active review trail for fallback, partial, failed, ready, and skipped source states while keeping external provider monitoring and long-term production retention as future work.

Current follow-up note (2026-06-01): Ops Event Log now supports optional local time-based retention pruning. Configure `OPS_LOG_RETENTION_DAYS` or `TIANYUAN_OPS_LOG_RETENTION_DAYS` to prune JSONL events older than the configured age during record/status/export paths; Backend Status and export bundles expose the policy. This is local retention hygiene, not centralized logging or vendor retention.

Current follow-up note (2026-06-01): Backend Status worker diagnostics now include status-filtered totals. `GET /analysis/jobs` accepts repeatable `status`, `/analysis/jobs/summary` returns total/filtered/status counts, and `/backend` renders filter/total controls while protecting the visible queue rows from stale responses and slow summary calls. This improves local diagnostics only; external worker queue ownership, distributed lease enforcement, and cross-host concurrency limits remain future work.

Current follow-up note (2026-06-01): Backend Status worker diagnostics now have bounded pagination. `GET /analysis/jobs` and `GET /analysis/jobs/attempts` accept `offset`, the local SQLite/JSON store applies offset pagination, and `/backend` exposes queue/attempt page ranges plus `Newer` / `Older` controls. This fixes the local first-page-only diagnostics gap, but true external queue orchestration, distributed lease enforcement, and cross-host concurrency limits remain future production work.

Current follow-up note (2026-06-01): local structured ops logs now have an external aggregation handoff contract. `/ops/logs/status` exposes export readiness, schema, retention policy, and redaction policy; `/ops/logs/export` returns bounded sanitized `ops_log_export_v1` bundles with checksums for deployment-side shippers. This remains local export readiness, not a deployed centralized log/search/retention service.

Current follow-up note (2026-06-01): Plugin package governance now ingests external malware-scan sidecar verdicts before storage. Uploads record external scan status/provider/required metadata in response, manifest, lifecycle, and audit; strict-auth browser smoke enables required scan, writes a temporary PASSED verdict, and proves Plugin Registry renders the evidence. This remains no-code/review-only and does not provide vendor scanner deployment or a higher-permission plugin sandbox.

Current follow-up note (2026-06-01): Backtest research validation is now reviewable from the active report page, not just the experiment package. The page renders out-of-sample, walk-forward, benchmark, parameter-scan, package-hash, and required-component details from `validationProtocol`, and strict-auth browser smoke verifies those details after the bounded parameter-scan run.

Current follow-up note (2026-06-01): SignalOps candidate review now has a visible parameter-delta layer. The review card compares bounded baseline/candidate config leaves from `strategy_experiment`, `smoke:frontend` guards the hook/fixture contract, and strict-auth browser smoke proves the rendered delta before approval/rejection. 2026-06-02 follow-up: SignalOps now derives `parameter_diff_summary` on the server for real review queue items, including bounded changed/added/removed/unchanged counts and rows, while the page uses that summary before local fallback. Plugin Registry UI state also preserves uploaded artifact and upgraded lifecycle evidence from backend responses so the governed package path remains stable under browser timing.

Current follow-up note (2026-06-01): Data Engine now participates in the P1-2 provenance acceptance chain. `/data-engine` renders the active run id, shared data provenance, source freshness, and fallback chain from `buildDashboardProvenanceSummary(currentRun)`; `smoke:frontend` guards the hooks and `smoke:strict-auth-browser` verifies the seeded run plus Bearer-auth adapter loading with `ok strict-auth browser Data Engine provenance/freshness`.

Current follow-up note (2026-06-01): Backend Status now renders productionHealth LLM failure reasons beside its 24h/7d health trends, and the research-closure browser smoke proves the redacted reason/sample-run fixture on `/backend`. New Task also hands off to `/live-run` immediately after `startAnalysisRun()` succeeds, so transient run-detail hydration delays no longer block the main Portfolio -> New Task -> Live Run browser path.

Current follow-up note (2026-06-01): Dashboard now consumes production LLM live-call health. `/api/metrics.productionHealth.windows[*].llmCallFailureRate` includes redacted `failureReasons` and bounded `sampleFailures`, Dashboard renders the 24h success/failure/skipped/token summary plus top failure reason, and strict-auth browser smoke checks Bearer-auth `/api/metrics` loading. The path remains read-only and `externalCalls=false`, so it does not trigger live LLM calls or affect simulation/live trading boundaries.

Current follow-up note (2026-06-01): Knowledge impact analytics now has a concrete first layer: post-publish regression reports include `knowledge_impact` with observation-only status/risk/action/net-impact metadata, and Dashboard plus `/research-lab/versions` render it. This keeps automatic blocking out of the impact summary while giving reviewers a clearer read on whether a published Knowledge version is improving, regressing, coverage-limited, or review-heavy.

Current follow-up note (2026-06-01): Research Lab workflow write entries are now role-aware. `ResearchLoopsPage` uses the shared operator context and requires `researcher+` for loop/sample/iteration/evidence/materialization/draft/feedback writes, shows a viewer-facing disabled reason, and strict-auth browser smoke verifies `viewer` is blocked before restoring `admin` for the P2 closed-loop sample.

Current follow-up note (2026-06-01): Technical Kline case governance now has representative case-set and parameter-version review metadata. `savedGovernance.caseImpact` reads all retained governance cases, reports reviewed-case count, symbol diversity, missing `valid` / `misjudge` / `insufficient_data` coverage, remediation next actions, and current-vs-baseline config rate deltas; `/quant-core` renders the panels and strict-auth browser smoke verifies them through the active page. The policy remains review-only and cannot create trade actions.

Current follow-up note (2026-06-01): Research Lab `workflow_state` now includes an explicit maturity profile in addition to `maturity_score`: `maturity_level`, `maturity_label`, and `maturity_reasons`. The backend derives the profile from stage/blockers, the Research Lab P2 guide renders it, `researchClient` validates it, and strict-auth browser smoke verifies the `missing_sample` / weak-evidence profile in the closed-loop sample.

Current follow-up note (2026-06-01): Knowledge Versions now renders audited regression-waiver metadata from `approval_record.regression_waiver` on `/research-lab/versions`. The frontend shows the waiver policy, approval id, approver role, regressed-case count, evaluation id, mode, timestamp, and reason; `smoke:strict-auth-browser` verifies the seeded waiver fixture is visible, so backend waiver governance is no longer hidden from reviewers.

Current follow-up note (2026-06-01): Knowledge promotion regression override is now explicit and audited. The default promotion gate still blocks evaluation evidence with regressed cases, while an API-level waiver must include an admin approver role, approval id, and bounded reason; the approval record persists waiver policy metadata and a waiver evidence reference for later review.

Current follow-up note (2026-06-01): Dashboard's `Research Lab closed-loop sample` write entry is now role-aware. The button requires `researcher` or above through the shared operator context, shows a viewer-facing disabled reason, and the strict-auth browser smoke toggles `viewer` -> `admin` before completing the Bearer-auth sample-chain POST. This closes the immediate RBAC UX gap for the new Dashboard write surface while preserving backend auth as the enforcement layer.

Current follow-up note (2026-06-01): Dashboard now has a `Research Lab closed-loop sample` entry that can rebuild the deterministic P2 sample chain through the existing `createP2ClosedLoopSample()` API and then render run, SignalOps, backtest, Research iteration, case, knowledge, evaluation, and knowledge-version IDs. Strict-auth browser smoke clicks the Dashboard action with Bearer auth and verifies `simulation_only=true` / `is_real_trade=false`, so Dashboard and Research Lab both provide an active entry into the reviewable sample chain without creating any real-trading path.

Current follow-up note (2026-06-01): Research Lab `workflow_state.steps[]` now carries per-step review guidance: source, source timestamp, evidence strength, missing items, and next action. The Research Lab closed-loop wizard renders those fields, `researchClient` validates workflow-state shape, and smoke guards keep the source/strength/missing/next hooks in place. This improves operator reviewability without auto-accepting verdicts, changing artifact materialization policy, or touching simulation/live-trading boundaries.

Current follow-up note (2026-06-01): Knowledge regression case-set policy now carries remediation metadata while remaining warn-only. Reports expose `case_set_quality_policy.remediation` with reviewer owner, required actions, reviewed-case and symbol deltas, missing affected modules, target case mix, and next actions; Knowledge Versions and Dashboard render the remediation path. This clarifies what evidence must be added before any future blocking/override policy, without changing promotion approval, evaluation scoring, or runtime behavior.

Current follow-up note (2026-06-01): Knowledge regression representative case-set quality and policy are now visible in post-publish reports. Backend reports expose `case_set_quality`, `case_set_quality_policy`, and `quality_warnings`; Knowledge Versions renders quality and policy; Dashboard merges warnings and shows the policy; strict-auth browser smoke verifies a deterministic `LOW_COVERAGE` / missing-module / `WARN_ONLY` case. Remaining work is to decide whether a future policy version should block low coverage or require an audited override.

Current follow-up note (2026-06-01): Knowledge Versions post-publish regression rerun is now covered by `smoke:strict-auth-browser` on canonical `/research-lab/versions`. The smoke verifies Bearer-auth `GET /api/case-library/knowledge-versions?limit=30`, Bearer-auth `POST /api/case-library/knowledge-versions/{version_id}/regression`, refreshed `REGRESSION` rendering, and stable page hooks while keeping `/knowledge-versions` as a legacy redirect. Representative case-set quality is now visible as warning metadata; remaining work is automatic regression gating policy and longer-term knowledge-impact analytics.

Current follow-up note (2026-06-01): Evaluation Sandbox is now covered by `smoke:strict-auth-browser` on canonical `/research-lab/evaluation`. The smoke verifies Bearer-auth `GET /api/case-library/patches?limit=30`, Bearer-auth `GET /api/case-library/evaluations?limit=30`, forced `POST /api/case-library/patches/{patch_id}/evaluate`, `POST /api/case-library/patches/{patch_id}/strategy-experiment`, rendered evaluation summary, and rendered candidate A/B winner. Representative case-set quality now has a visible warn-only policy; remaining work is automatic promotion/regression gating policy beyond the completed regressed-evidence block.

Current follow-up note (2026-06-01): Knowledge promotion now has a concrete regression gate. `approve-with-evaluation` rejects evaluation evidence with `regressed_cases > 0` before patch approval or active knowledge-version creation; focused backend regression now covers that path. Representative case quality is visible as warn-only policy metadata. Remaining work is explicit audited override policy and longer-run post-publish governance analytics.

更新日期：2026-05-21

## 1. 文档定位

本文基于当前代码、文档、本地数据库和验证命令，对 `super` 量化系统后续需要完善的部分重新整理。

重要边界：

- 本文不是恢复旧 backlog 的未完成项；旧 `OPEN_DEVELOPMENT_BACKLOG.md` 已删除，N1-N6 当前仍视为本轮闭环范围内的 `Verified Done`，闭环证据保留在 `DEVELOPMENT_LOG.md`。
- 本文面向下一阶段产品化、样例闭环和研究能力增强。
- 当前系统应继续定位为本地量化研究与模拟交易控制台，不应被描述为生产级实盘自动交易系统。
- SignalOps 继续保持 `simulation_only=true`，真实下单、券商账户直连、自动实盘交易不纳入当前默认能力。

## 2. 当前验证基线

当前主验收入口：

- `npm.cmd run validate:phase1-3`：阶段闭环验收，覆盖 baseline audit、module participation、typecheck、lint、build、static smoke 和 Research closure browser smoke。
- `npm.cmd run validate:premerge`：提交前稳定性验收，覆盖 closed-loop sample、analysis worker、默认后端回归、typecheck、lint、build、static smoke、frontend responsive smoke 和 strict-auth browser matrix。
- `npm.cmd run validate:module-participation`：模块参与验收，覆盖 SignalOps、MFE/MAE Quant Core、closed-loop persistence、analysis worker、Portfolio、Backtest、Research、Evaluation、Plugin、Data Health 和 observability。
- `npm.cmd run smoke:research-closure:browser`：临时 SQLite 真实浏览器闭环。
- `npm.cmd run smoke:strict-auth-browser:matrix`：strict auth 下的跨页面浏览器矩阵。

当前数据状态口径：

- 当前运行库 `storage/tianyuan_quant.db` 不是验收样例写入目标；E2E 和 closed-loop 验收必须使用 `.tmp` 下临时 SQLite，避免污染本地长期运行库。
- 数据闭环是否成立以 `audit:baseline`、`validate:module-participation`、`validate:phase1-3` 和 `smoke:research-closure:browser` 输出为准，而不是用某次旧本地库空表快照判断。
- `audit:baseline` 会输出关键表计数、`closure_required_tables`、`closure_gaps` 和不可回退边界，作为当前只读基线。

当前综合判断：

- 系统功能面已经很宽，主链路、模拟交易、安全边界和测试基线可用。
- 当前审查修复与 Phase 1-3 本地闭环已有可执行验收入口；剩余短板主要是长期生产化能力，例如外部 worker/queue、跨主机 lease、集中日志/告警 provider、生产级插件存储治理和更高权限插件沙箱。

## 2.1 2026-05-21 后续阶段闭环更新

本轮按 P1-P4 的真实剩余缺口补齐以下能力：

- P1/P3 权限治理：`/signalops` 前端接入 operator role 策略，生命周期写入、强制跟进、收盘复盘、人工接管、强平、移除和高级运行配置保存会按 `researcher` / `operator` / `admin` 分层禁用，并显示当前 operator/role。
- P2 端到端样例链：`/research/p2/closed-loop-sample` 默认生成 evaluation，并在具备 patch/evaluation 证据时自动提升为 knowledge version；响应和 Research Lab 闭环向导现在包含 portfolio、run、SignalOps、backtest、research、knowledge、case、evaluation、knowledge version 全链路步骤。
- P2-1 Backtest research validation follow-up: `BacktestReport.validationProtocol` now exposes parameter-scan status, walk-forward status, benchmark availability, required research-grade checks, and deterministic parameter/market-data/signal/benchmark/data-package hashes. Research-grade scoring now weights `walk_forward` and `parameter_scan`, so reports without those checks remain `supporting_only`.
- 2026-06-01 P2-1 follow-up: `POST /api/research/backtest/parameter-scan` now creates bounded parameter-grid Backtest runs, ranks the generated trials, returns a best-run summary, and exposes a Backtest page `Parameter scan` entry. `GET /api/research/backtest/parameter-scans` and the Backtest page history panel now retain the scan-level result view. 2026-06-02 follow-up: bounded scans now run each capped parameter combination across retained windows, expose `window_count` / `summary.totalTrials`, render window evidence in Backtest notice/history/detail panels, and can be submitted through a local async job via `POST /api/research/backtest/parameter-scan/jobs`. External queues/distributed long-window workers remain future work.
- 2026-06-01 P2-1 follow-up: `smoke:strict-auth-browser` now clicks the Backtest experiment-package download for a seeded sample run, verifies Bearer-auth transport, parses the downloaded JSON, and checks package id/schema/hash/run-id/simulation boundary fields.
- 2026-06-01 P2-1 follow-up: `smoke:strict-auth-browser` now also drives the Backtest `Parameter scan` action, verifies Bearer-auth transport, checks bounded scan/best-run/validation-protocol fields, and confirms the selected best run renders parameter-scan, walk-forward, and data-package evidence in the page.
- P3 配置治理：`/config/versions?include_external=true` 返回外部 runtime 配置的 `approval_required`、`effective_scope`、`snapshot_redacted` 和 `rollback_policy`；Config Versions 页面支持按 surface、actor、status 过滤，并明确 secret-safe rollback 阻断原因；Agent Runtime approved restore 已改为审批弹窗和 surface-scoped 后端执行器，不再使用 `window.prompt`。
- P4 smoke 自动化：`npm.cmd run smoke:frontend` 基于 `frontend/dist` 临时启动静态预览并检查核心路由，并守住 Settings adapter partial-load error/list hooks、Portfolio import shared `httpClient` FormData/operator-header path；`npm.cmd run smoke:research-closure:browser` 已覆盖 `/backend` productionHealth 24h/7d 趋势/sourceErrors、Portfolio -> New Task -> Live Run、direct-load DAG/Debate/Final、Research Lab backtest deep link、一键 closed-loop sample 和 Backtest stale request cancellation；`npm.cmd run smoke:strict-auth-browser` 已覆盖 Dashboard run/provenance/knowledge regression、Backend Status attempt diagnostics、analysis job queue、run_id drill-down、seeded attempt row、Config Versions approved restore 弹窗、Bearer token、无 prompt、SignalOps strict-auth、SignalOps forced tick、daily review、manual command、review-decision approval/rejection、SignalOps -> Research evidence click path、Research Lab P2 closed-loop sample、Research -> Backtest -> verdict-inputs click path、Research -> SignalOps selected-signal deep link、Agent DAG/Debate linked-run LLM evidence、Agent DAG ReactFlow zoom/fit controls、pane drag/pan、mouse-click/multi-node keyboard selected evidence、failure/degraded fixture 和 source-classification state matrix fixture、Live Run stream query-token、terminal `STREAM_TIMEOUT` / `RUN_STALE_RECOVERED` event retention 和 New Task -> Live Run -> Final report；后端 stream 回归已覆盖 SSE stale/cancelled done、WebSocket `STALE`/`CANCELLED` status-specific terminal events、WebSocket RUN_REMOVED 和 STREAM_TIMEOUT 分支；`npm.cmd run smoke:db-backup-restore` 已覆盖临时 SQLite source -> backup manifest/checksum -> restore dry-run -> force restore -> integrity/marker verification 的脚本级备份恢复链路，生成物限定在 `.tmp\db-backup-restore-drill`；`npm.cmd run smoke:db-offhost-backup` 已覆盖临时 SQLite backup + manifest 复制到模拟离机目录并按 checksum 校验；`npm.cmd run smoke:storage-offhost-restore` 已覆盖临时 backend-storage、secret vault 和 key file 的模拟离机复制、恢复和逐文件 SHA-256 校验。
- 2026-06-01 follow-up: `smoke:strict-auth-browser` also covers Config Versions multi-surface filtering and governed restore for `agent_runtime:data_sources_config` and `agent_runtime:market_data_adapter_config`.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` also covers Backtest experiment-package browser download, including the Blob/download path and downloaded JSON package assertions.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` also covers Backtest parameter-scan validation-protocol rendering from the active page, including bounded scan response checks, retained scan-history rendering, and simulation-only generated-run assertions.
- 2026-06-01 follow-up: `/data-health` now renders a source freshness and fallback-chain summary from snapshot history, and `smoke:strict-auth-browser` verifies Bearer-auth loading plus deterministic partial/fallback rendering for latest source, adapter context, fallback count, and slowest latency.
- 2026-06-01 follow-up: Dashboard and Final Writer now render run-level source freshness from `dataSources.sources[*]` next to fallback chain, missing fields, and review points; `smoke:frontend` and `smoke:strict-auth-browser` guard both `dashboard-source-freshness` and `final-writer-source-freshness`.
- 2026-06-01 follow-up: Data Engine now renders the same shared provenance summary and source freshness with `data-engine-data-provenance`, `data-engine-source-freshness`, and `data-engine-fallback-chain`; `smoke:strict-auth-browser` opens `/data-engine` for the seeded run and verifies Bearer-auth adapter health loading.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` now covers `/settings` adapter partial-load behavior under strict auth by preserving visible adapter health rows when adapter config loading fails, including refresh-all `live_check=true` verification.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` now uploads an Eastmoney-style CSV and a Huatai/HTSC TSV through `/portfolio`, verifies Bearer-auth multipart `FormData`, checks imported broker-template metadata for both fixtures, and then continues through the existing Portfolio -> New Task -> Live Run chain.
- 2026-06-01 follow-up: the same strict-auth chain now asserts `new-task-portfolio-risk-preflight` before run creation, including `Portfolio risk`, `Pre-task holding risk prompt`, broker-template context, and a concrete holding/concentration/loading note.
- 2026-06-01 follow-up: after Final Writer, the strict-auth chain now opens `/audit`, verifies Bearer-auth run audit loading through `GET /api/analysis/runs/{run_id}/audit`, and requires a visible lifecycle audit event for the same run.
- 2026-06-01 follow-up: `smoke:frontend` also guards SignalOps selected-signal detail stale-response prevention by requiring `signalDetailRequestSeq`, stale request checks, and stable selected-detail DOM hooks. This protects the R13 UI race fix without changing SignalOps simulation-only automation boundaries.

仍保留为长期工程项：真正外部 worker/queue、更系统的跨页面复杂状态矩阵 E2E、外部集中日志/告警 provider、生产级插件 object-storage lifecycle/恶意软件扫描、任意代码插件沙箱和实盘交易系统设计。它们不是当前 simulation-only 研究控制台的默认能力。

## 2.2 2026-05-21 数据闭环优先审查落盘

本次审查确认：下一阶段不要重新打开已删除的旧 backlog，也不要先做大范围重构。优化顺序固定为：

1. 先补真实数据闭环：用现有 `POST /api/research/p2/closed-loop-sample` 作为唯一主入口，确保 portfolio、run、SignalOps、backtest、Research、case、knowledge、evaluation、knowledge version 都生成可追踪 ID。
2. 再补浏览器交互 E2E：在现有 `smoke:frontend` 路由 smoke 之上，逐步覆盖 `/portfolio`、`/new-task`、`/live-run`、`/research-lab/research`、`/research-lab/versions` 的真实按钮和错误态。
3. 最后推进长期工程：外部 worker/queue、生产告警、SQLite/JSON 状态收敛和更高权限插件沙箱。以上都不得弱化 `simulation_only=true`、`SIM_*` 和人工确认边界。

本次落盘补强的最小实现面：

- Research Lab 闭环向导暴露 knowledge version promotion 开关，并继续消费后端 `steps[]`、`warnings[]`、`knowledge_version_id`。
- 后端新增 ASGI route-level 闭环测试，覆盖 middleware、response model 和 SQLite 沉淀，不新增平行 API。
- `DATABASE_SCHEMA.md` 与 `STORAGE_DESIGN.md` 改用当前 51 个业务 ORM 表模型和 SQLite + JSON 混合存储口径，避免继续引用旧“13 张表”描述。

## 3. 优先级总览

| 优先级 | 目标 | 处理策略 |
| --- | --- | --- |
| P0 | 消除会误导用户或阻断闭环的当前运行问题 | 先修复状态、样例、入口和可见证据 |
| P1 | 建立一条真实可复核研究闭环 | 让 run、SignalOps、backtest、Research、Case、Knowledge、Evaluation 串起来 |
| P2 | 提升研究级可信度和策略验证深度 | 增强 backtest、数据 provenance、技术面治理和评估统计 |
| P3 | 产品化和多用户/生产部署能力 | 增加权限、审计、监控、配置治理和任务平台化 |
| P4 | 平台扩展和长期工程治理 | 插件、迁移、性能、E2E、文档和清理 |

## 4. P0：当前运行状态与闭环阻断项

本轮开发状态（2026-05-20）：

- `P0-1` 已完成代码修复：`/analysis/jobs`、`/analysis/runs/{run_id}/job`、runs list/detail/start 统一触发 run/job 对账；过期 `RUNNING` / `PENDING` 会恢复为 `STALE`，并写入 recovery、audit、stream event 和 job stale reason。
- `P0-2` 已完成后端闭环硬化：现有 `/research/sample-loop/from-latest-run` 和 `/research/p2/closed-loop-sample` 链路可继续物化 case、knowledge、patch、evaluation；样例证据明确标记为 `supporting_only`，弱 backtest 不允许被当作强研究结论。
- `P0-3` 已完成前端入口：`/portfolio` 支持一键最小样例、手动 snapshot、文件导入、快照列表和“用于新任务”；`/new-task` 可通过 `portfolio_snapshot_id` 预选快照，并明确展示是否会发送 portfolio context。
- 额外修复：外部行情适配器测试不依赖本机是否安装可选数据包，缺失依赖场景由测试显式模拟。
- 历史 P0 结果已被当前 `validate:phase1-3`、`validate:premerge` 和扩展后的默认后端回归取代。不要再用旧的单次全量失败记录判断当前系统状态。

### P0-1 清理并统一历史 run/job 状态

问题：

- 本地 JSON run 中仍有多个 `RUNNING` / `LIVE_PENDING` 记录。
- `analysis_jobs.json` 中已有 watchdog 标记的 `STALE` job，但部分 run 文件仍可能让前端看到运行中状态。
- Live Run Console、Dashboard 和 Research Lab 可能对旧任务状态产生误判。

涉及模块：

- `backend/app/api/routes_analysis.py`
- `backend/app/core/analysis_job_store.py`
- `backend/app/storage/runs/`
- `frontend/src/components/live/LiveRunConsole.tsx`
- `frontend/src/components/dashboard/DashboardPage.tsx`

完成标准：

- 历史 `RUNNING` run 在查询、启动、列表和详情接口中状态一致。
- 前端统一展示 `STALE` / `FAILED` / `CANCELLED`，不再把旧任务显示为仍在执行。
- 提供一个安全的本地修复脚本或管理 API，用于扫描并恢复过期运行。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py -q`
- 人工检查 `/live-run` 和 `/` 的历史状态展示。

### P0-2 建立第一条端到端样例数据

问题：

- 当前数据库中 `backtest_runs=0`、`case_library=0`、`knowledge_versions=0`、`evaluation_runs=0`。
- Research Lab 有结构和少量 evidence，但缺一条可复核的完整闭环样例。

涉及模块：

- `backend/app/api/routes_analysis.py`
- `backend/app/api/routes_signalops.py`
- `backend/app/api/routes_backtest.py`
- `backend/app/api/routes_research.py`
- `backend/app/api/routes_case_library.py`
- `backend/app/api/routes_evaluation.py`
- `frontend/src/components/research/ResearchLabPage.tsx`
- `frontend/src/components/backtest/BacktestPage.tsx`
- `frontend/src/components/caseLibrary/CaseLibraryPage.tsx`

完成标准：

- 至少有一条样例链：持仓或手工输入 -> analysis run -> SignalOps -> backtest -> Research verdict -> case -> knowledge version -> evaluation。
- 每一步都有可点击 ID、来源字段、时间戳、证据强度和缺失项说明。
- 新用户进入 Research Lab 时可以一键生成或查看这条样例链。

验证建议：

- DB 计数不再为 0：`backtest_runs`、`case_library`、`knowledge_versions`、`evaluation_runs`。
- `npm.cmd run test:backend -- backend\tests\test_research_store.py backend\tests\test_case_library.py backend\tests\test_evaluation.py -q`

### P0-3 明确真实持仓入口和样例

问题：

- 持仓导入、手工录入和快照模型存在，但当前本地 `portfolio_snapshots=0`、`holding_positions=0`。
- 系统还没有形成“从用户真实组合出发”的稳定演示链路。

涉及模块：

- `backend/app/api/routes_portfolio.py`
- `backend/app/core/portfolio_store.py`
- `frontend/src/components/portfolio/PortfolioPage.tsx`
- `frontend/src/components/task/NewTaskPage.tsx`

完成标准：

- 提供一条最小手工持仓样例，能绑定到新建 analysis run。
- 新建任务页明确显示当前使用的持仓快照、现金、成本、可卖数量和风险约束。
- 持仓样例进入最终报告和风险模块的 provenance。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py backend\tests\test_analysis_workflow.py -q`

## 5. P1：真实闭环与数据可信度

本轮开发状态（2026-05-20）：

- `P1-1` 已完成：新增 `POST /api/backtest/signalops-sample`，可从已沉淀 SignalOps 生命周期信号生成弱证据回测样例；回测报告返回 signal source、market data source、sample window、limitations 和 evidence strength，并明确 `canSupportResearchVerdict=false`。
- `P1-2` 已完成：`dataProvenance.ts` 输出 Dashboard、Final Writer、Data Engine 共用的数据可信摘要，前置展示 fallback 链、缺失字段、复核点和来源等级。
- 2026-06-01 follow-up: `dataProvenance.ts` now also emits `freshnessItems`, and Dashboard/Final Writer render source freshness for the active run under static and strict-auth browser guards.
- `P1-3` 已完成：普通 `run_agent_llm()` 成功、失败、跳过都会沉淀到 LLM profile health；`/new-task` 展示默认 LLM profile 最近 live call 状态；`/agent-dag` 和 `/debate` 区分真实 LLM 输出、LLM 降级/失败、规则引擎和 mock/sample，并展示 profile、token、latency、finish reason、error 和降级原因。
- `P1-4` 已完成：自动纸面交易 tick 写入 `decision_card`，包含 action、reason、capital before/after、cash、position value、budget used、blockers、research tuning refs 和 capital attribution；SignalOps 页面重建为可运行控制台，支持自动 tick、daily review、资金归因、股票池命令、生命周期条件/迁移/复核和 paper order -> case 入口。
- 本轮验证通过：`npm.cmd run build`、`npm.cmd run lint`、`.venv\Scripts\python.exe -m py_compile ...`、`npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q`、`npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_backtest_signalops_sample.py -q`、`npm.cmd run test:backend -- backend\tests\test_auto_paper_trading.py backend\tests\test_auto_paper_routes.py -q`、`npm.cmd run test:backend`。

### P1-1 Backtest 从“结构可用”升级为“样例可复核”

问题：

- Backtest 引擎已有 T+1、涨跌停、成本、滑点、benchmark 和证据强度字段。
- 当前本地没有 backtest run，无法证明策略验证链路已实际跑通。

涉及模块：

- `backend/app/core/backtest_engine.py`
- `backend/app/core/backtest_store.py`
- `backend/app/api/routes_backtest.py`
- `frontend/src/components/backtest/BacktestPage.tsx`

完成标准：

- SignalOps 产生的模拟信号可以直接生成 backtest。
- backtest report 包含 signal source、market data source、sample window、benchmark、slippage、cost、evidence strength。
- Research verdict 不允许把低样本、mock 或无样本外验证的结果当作强证据。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_backtest_engine.py backend\tests\test_backtest_store.py -q`
- 本地 DB `backtest_runs > 0`、`backtest_signals > 0`。

### P1-2 数据来源 provenance 前置展示

问题：

- 行情、K 线、辅助数据、fallback 和 mock 状态已经有字段，但用户需要跨页面判断数据是否可信。
- 当前 run 多为 `MIXED`，需要更直观地解释哪些数据是真实、哪些是 fallback、哪些缺失。

涉及模块：

- `backend/app/core/market_data_runner.py`
- `backend/app/core/market_data_adapter.py`
- `frontend/src/utils/dataProvenance.ts`
- `frontend/src/components/dashboard/DashboardPage.tsx`
- `frontend/src/components/final/FinalWriterPage.tsx`
- `frontend/src/components/agents/DataEnginePage.tsx`

完成标准：

- Dashboard 第一屏展示本次 run 的数据来源摘要。
- Final Writer 报告第一段明确数据可信等级、fallback 链、缺失字段和人工复核点。
- 每个 run 固化 market data provenance，后续行情变化不影响复盘解释。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_market_data_runner.py backend\tests\test_data_health_routes.py -q`
- 浏览器检查 Dashboard、Final Writer、Data Engine。

### P1-3 LLM READY 与实际调用成功率继续收紧

当前状态（2026-05-20）：已完成。

问题：

- 当前 LLM profile 已区分 `CONFIGURED`、`READY`、last call、last error。
- 已补齐：`/new-task`、`/agent-dag` 和 `/debate` 的 LLM live-call / output-source evidence 已进入 `smoke:frontend` 弱链 guard，防止 New Task 默认 LLM 状态卡、Agent DAG/Debate 真实 LLM/降级/规则/mock 分类、token metering、Agent DAG ReactFlow viewport hook、mouse/keyboard selection handler、degraded/source counts 和 selected evidence 面板被静默移除；`smoke:strict-auth-browser` 也会用 P2 closed-loop sample 的真实 run 打开 `/dag?run_id=...` 与 `/debate?run_id=...`，验证 source summary、metering status、per-agent row 证据，点击 zoom-in/fit-view 控件，点击 `orchestrator` 节点、键盘选中第二个真实节点确认 selected-node evidence 会切换渲染，并用 deterministic failure 和 state-matrix fixtures 覆盖 LLM degraded/failed 以及 LLM / rule / plugin / mock source classification 节点。

涉及模块：

- `backend/app/core/llm_runner.py`
- `backend/app/core/llm_profile_tester.py`
- `backend/app/core/agent_runtime_store.py`
- `frontend/src/components/task/NewTaskPage.tsx`
- `frontend/src/components/dag/AgentDagPage.tsx`
- `frontend/src/components/agents/AgentRuntimeSection.tsx`
- `frontend/src/components/debate/AgentDebatePage.tsx`
- `frontend/src/types/index.ts`

完成标准：

- 新建任务前提示默认 LLM profile 最近一次 live call 状态。
- Agent Results 中区分规则输出、LLM 成功输出、LLM 降级输出。
- Debate/token 页面显示本次运行每个 Agent 的 token、latency、error 和降级原因。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q`
- `npm.cmd run build`
- `npm.cmd run lint`

### P1-4 SignalOps 决策卡和资金归因

问题：

- SignalOps 是当前最成熟模块，但多股票资金归因、tick 决策原因、失败原因和收益归因仍可更清晰。

涉及模块：

- `backend/app/core/auto_paper_trading.py`
- `backend/app/core/signalops_store.py`
- `frontend/src/components/signalops/SignalOpsPage.tsx`

完成标准：

- 每次 tick 生成审计决策卡：为何开仓、为何持有、为何关闭、为何跳过。
- 多股票展示资金分配、占用、浮盈亏、失败原因和自动调参来源。
- tick 结果可以一键沉淀为 Research evidence 或 Case。

验证建议：

- `npm.cmd run test:backend -- backend\tests\test_auto_paper_routes.py backend\tests\test_auto_paper_trading.py backend\tests\test_signalops.py -q`

## 6. P2：研究级策略验证能力

### P2-1 Backtest 研究级增强

问题：

- 当前 backtest 已有研究字段，但还不够支撑策略有效性证明。

待完善：

- 参数扫描。
- 样本外分段。
- walk-forward 验证。
- 指数/行业 benchmark。
- 成交可达性和停牌/流动性处理。
- 多策略对比和置信区间。

完成标准：

- Backtest report 产生研究级评分：样本量、样本外覆盖、benchmark 超额收益、最大回撤、交易约束、统计置信。
- 弱样本自动进入 `supporting_only`。

Current progress (2026-06-01):

- `BacktestReport.validationProtocol` records parameter-scan status, walk-forward status, benchmark availability, required research-grade checks, and reproducible package hashes.
- `researchGradeScore.components` now includes weighted `walk_forward` and `parameter_scan` dimensions in addition to sample count, out-of-sample coverage, benchmark excess return, drawdown, execution constraints, and statistical confidence.
- `provenance` now exposes `parameterHash`, `marketDataHash`, `signalPackageHash`, `benchmarkDataHash`, and `dataPackageHash`, giving Research Lab and reviewers a stable way to compare the exact experiment package.
- Missing walk-forward or parameter-scan evidence is an explicit limitation and keeps the report as `supporting_only`.
- `POST /api/research/backtest/parameter-scan` creates bounded parameter-grid runs, ranks generated trials, and opens the best run in the Backtest page.
- `GET /api/research/backtest/runs/{run_id}/experiment-package` now exports the run, trades, signals, validation protocol, provenance, package hashes, research usage, limitations, and simulation/live boundary as a reproducible JSON package; the Backtest detail page can download it.
- `smoke:strict-auth-browser` now verifies the experiment-package browser download path for a seeded Backtest run and parses the downloaded JSON package before accepting the flow.
- `smoke:strict-auth-browser` now verifies the parameter-scan browser path for a seeded Backtest scan, including Bearer auth, generated-run simulation boundaries, best-run validation protocol evidence, and visible parameter-scan / walk-forward / data-package rendering.

### P2-2 Research Lab 工作流向导

问题：

- Research Lab 能力很多，但路径复杂。

待完善：

- 一键从最近 run 创建 loop。
- 一键从 SignalOps tick 创建 evidence。
- 一键从 backtest 创建 verdict inputs。
- 一键 materialize case/knowledge/patch/evaluation。
- 研究成熟度评分：缺数据、缺样本、可进入评估、可发布知识版本。

完成标准：

- 新用户不需要理解所有子页面，也能完成一条研究闭环。
- 每个 loop 有明确下一步建议和阻塞原因。

当前进展（2026-05-21）：

- 已新增 `ResearchLoopDetail.workflow_state` 后端契约，返回成熟度评分、阶段、下一步动作、阻塞原因和步骤状态。
- Research Lab 研究迭代页已接入 `workflow_state`，后端未连接时保留前端推导回退。
- 已覆盖无轮次、缺 run/backtest、缺 evaluation、可反馈等路径测试。
- 2026-06-01 follow-up: `ResearchWorkflowStep` now includes source, source timestamp, evidence strength, missing items, and per-step next action; the closed-loop wizard renders those fields and the frontend client validates workflow-state shape before rendering.
- 2026-06-01 follow-up: Backtest details opened from a Research iteration now preserve `iteration_id` in the deep link and can call `POST /api/research/backtest/runs/{run_id}/verdict-inputs` to attach the selected Backtest run and refresh `ResearchVerdictInputs` in one action. Weak/supporting-only evidence still stays behind the existing verdict gates.
- 2026-06-01 follow-up: SignalOps selected signals opened with `iteration_id` context can now call `POST /api/research/signalops/signals/{signal_id}/evidence` to attach `SIGNALOPS` and `SIGNALOPS_TICK` evidence and refresh `ResearchVerdictInputs`. The bridge records tick/decision/module/portfolio context as supporting-only research evidence and keeps `simulation_only=true` / `is_real_trade=false` / `strong_conclusion_allowed=false`.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` now covers the SignalOps -> Research evidence button with a deterministic selected-signal/tick fixture, Bearer request assertion, supporting-only response checks, and visible success notice.
- 2026-06-01 follow-up: Research Lab SignalOps evidence links now preserve a selected signal from `signalops_signal_id`, `signalops_signal_ids[]`, or `SIGNALOPS` evidence links, and strict-auth browser smoke clicks the Research-origin link into `/signalops?iteration_id=...&signal_id=...`.
- 2026-06-01 follow-up: `smoke:strict-auth-browser` now also covers the Research -> Backtest -> verdict-inputs round trip from a P2 closed-loop sample, including `iteration_id` propagation, selected Backtest run rendering, Bearer-auth POST, supporting-only Backtest evidence checks, and visible success notice.
- 2026-06-01 follow-up: Dashboard now exposes a one-click `Research Lab closed-loop sample` card that calls the existing P2 closed-loop API, renders the returned chain IDs, links into canonical `/research-lab/research`, and is covered by strict-auth browser smoke.

### P2-3 Case / Knowledge / Evaluation 持续沉淀

问题：

- API 和表结构存在，但当前本地沉淀为空。

待完善：

- 从 completed run 自动提取 learning candidate。
- 从 SignalOps daily review 自动创建 case。
- 知识版本发布后自动回归代表性 case。
- Dashboard 展示知识版本改善率、退化率、待复核项。

完成标准：

- `case_library`、`knowledge_versions`、`evaluation_runs` 有真实样例。
- 知识 patch 的影响模块、风险边界和回滚影响可追踪。

当前进展（2026-05-21）：

- Subagent 复核确认 completed analysis run 会自动沉淀 learning candidate，SignalOps daily review 会写入 review、case/evidence/Research iteration，KnowledgeVersion active/review/rolled_back 发布后会生成 `post_publish_regression` 并支持手动 rerun。
- Dashboard 已新增 `知识版本回归 / Knowledge regression` 区块，读取最新知识版本回归摘要并展示改善率、退化率、待复核项、代表案例数、影响模块和 warnings；API 不可用或暂无发布版本时显示安静空态。
- Knowledge Versions 页面发布回归摘要补充 `Review` 待复核数量/比例，避免待复核项只在主 Dashboard 暴露。
- 当前本地没有有效发布回归时，页面显示 `No published regression yet` 空态；发布真实知识版本后将直接消费后端 `post_publish_regression`。

审查修复（2026-05-21）：

- 发布后回归已补真实退化判定路径，能在放松风险/数据/复核门禁并命中已复核问题 case 时产生 `REGRESSION`、`regressed_cases` 和 `regression_rate`。
- 空 `{}` 回归报告不再被当作有效报告；Dashboard 和 Knowledge Versions 只消费带 `report_id/status` 的有效报告，并拉取最近 30 个版本避免 draft 遮挡已发布版本。
- draft 版本禁止手动执行 post-publish regression，前端按钮改为“发布后可回归”；当前无发布报告时显示 `No published regression yet`。

### P2-4 Technical Kline 误判复盘

Current implementation note (2026-06-01):

- Technical Kline case sedimentation is now reachable from canonical `/quant-core`; the legacy `/technical-kline` route remains redirected to `/quant-core`.
- `/api/technical-kline/cases` records local governance cases and mirrors them into Case Library with classification, config hash, prompt version, run id, status, and bias context.
- `smoke:strict-auth-browser` now proves the active page can record a `misjudge` case and render the returned Case Library id under Bearer auth.
- `/api/technical-kline/governance` now exposes `savedGovernance.caseImpact`, and `/quant-core` renders reviewed-case impact by config hash, current-config case count, misjudge/insufficient-data rates, low-sample warnings, and the `REVIEW_ONLY_PARAMETER_GOVERNANCE` / `NO_DIRECT_TRADE_ACTION` policy.
- `savedGovernance.caseImpact` now also exposes `representativeCaseSet`, `parameterVersionReview`, and `longWindowRegression`: reviewers can see reviewed-case minimums, symbol diversity, missing `valid` / `misjudge` / `insufficient_data` coverage, remediation next actions, current-config case counts, baseline config count, current-vs-baseline classification-rate deltas, and retained reviewed-case windows for local long-window regression review.
- Remaining future work is external long-window real-market regression jobs and production-grade multi-window experiment retention; no Technical Kline output directly creates trade actions.

问题（历史背景）：

- Technical Kline 已接入真实 K 线和下游约束，但误判复盘还没有形成持续闭环。

已完成/待完善：

- 已完成：将技术面 case 记录送入 Case Library，并在 `/quant-core` active 页面显示返回的 Case Library id。
- 已完成：标注有效、误判、样本不足，并携带备注、run/config/prompt/status/bias 证据。
- 已完成：用代表性 case-set 元数据和参数版本 delta 对当前配置做 review-only 复核。
- 待完善：对长期真实行情窗口做系统化回归评估和沉淀。

完成标准：

- 技术面参数变更能看到历史案例影响。
- 技术面输出只影响折扣、风险约束或失效条件，不直接生成交易动作。

2026-06-03 follow-up: local retained reviewed-case long-window regression coverage is now visible through `savedGovernance.caseImpact.longWindowRegression`; external long-horizon real-market jobs and production-grade multi-window retention remain future work.

## 7. P3：产品化、权限和生产部署

### P3-1 读写权限从 API token 扩展为用户/RBAC

当前开发状态（2026-05-21）：

- 已新增本地 operator profile，支持 `X-Operator-ID` / `X-Operator-Role` 和 `LOCAL_OPERATOR_*` / `SUPER_OPERATOR_*` 环境变量；默认开发 operator 为 `local_workbench/admin`，不引入 cookie/session。
- 写入认证中间件保留 `API_WRITE_TOKEN` / strict 模式，并新增 `viewer`、`researcher`、`operator`、`admin` RBAC：`viewer` 禁写，`researcher` 不能做 config/plugins/SignalOps command/delete，`operator` 可执行 SignalOps command，`admin` 可做 config/plugins/delete。
- 配置中心 runtime/draft/apply/rollback 的 audit payload 和 config version `created_by` 已绑定 operator。
- 前端新增本地 operator context，Backend Status 页面可切换 operator id/role，统一 HTTP client 自动发送 `X-Operator-ID` / `X-Operator-Role`。
- 插件启停按钮已按角色禁用：只有 `admin` 能启用/禁用插件，非 admin 会看到当前 operator 和禁用原因。
- SignalOps 页面已继续补齐 role-aware 禁用：`researcher` 可做生命周期写入，`operator` 才能执行强制跟进、收盘复盘、人工接管、强平和移除，`admin` 才能保存运行配置和股票池托管配置。
- Agent Runtime 写入/测试已按 `admin` 禁用，Config Versions approved restore 已按 `admin` 禁用并要求 governed modal，History/Backtest/Portfolio/Case/Knowledge 删除或回滚入口也已有 role-aware admin guard；`smoke:frontend` 会检查这些高风险入口的前端 guard 标记。
- 已覆盖角色拒绝、strict token 兼容和配置审计 operator 测试。
- 后续可继续扩展到未来新增高风险页面的细粒度按钮和更完整用户/会话体系，但当前主要配置、删除、回滚和 SignalOps 人工动作入口已具备前端 guard。

问题：

- 生产写入保护已有，但没有完整用户、角色、会话和操作权限。

待完善：

- 更完整用户登录/session 体系；当前本地 operator profile 已可用。
- 未来新增高风险入口继续接入 viewer、researcher、operator、admin 分层。
- 继续统一跨页面禁用原因和审计提示。

完成标准：

- 所有高风险操作都能追溯到 operator。
- 前端根据角色隐藏或禁用危险操作。

### P3-2 后台任务平台化

当前开发状态（2026-05-21）：

- 保留现有 JSON job store API，同时新增 SQLite `analysis_jobs` 镜像表和 `0002_analysis_jobs` migration。
- `start/mark_running/cancel/fail/stale/complete/reconcile` 会继续写 JSON，并 upsert SQLite；JSON 缺失时可从 SQLite 查询 job，stale reconciliation 会纳入 SQLite-only job。
- job 字段新增 `queue_name`、`concurrency_group`、`concurrency_limit`、`worker_id`、`worker_heartbeat_at`、`history`、`recovery`，并提供 worker heartbeat 记录能力。
- 已覆盖 SQLite lifecycle、状态查询、JSON 缺失恢复、SQLite-only stale reconciliation 和 migration 测试。
- 已补齐：SQLite worker mirror 现在包含独立 `analysis_job_attempts` 表，按 `(run_id, attempt)` 保留每次执行/重试的状态、worker、错误、retry source 和历史；`GET /api/analysis/jobs/attempts` 与 Backend Status 的 `Analysis Job Attempts` 面板已经提供只读诊断入口，支持按 run_id drill-down 过滤，并由 strict-auth browser smoke 通过真实创建/启动的 seeded attempt row 验证非空渲染。
- 已补齐：Backend Status 新增 `Analysis Job Queue` 只读队列视图，读取 `GET /api/analysis/jobs?limit=12`，展示 queued/running/stale/failed 计数、queue name、concurrency group/limit、worker id、heartbeat、lease status/expiry 和 updated time；strict-auth browser smoke 会验证 seeded worker-mode run 出现在队列表格中且请求携带 Bearer auth。
- 已补齐：SQLite job/attempt mirror 增加 `lease_status`、`lease_expires_at`、`lease_seconds`，claim/heartbeat 会刷新 active lease，terminal job 会显示 released，便于运营判断 worker 是否仍持有本地租约。
- 已补齐：worker heartbeat、mark running、completed/failed/cancelled terminal 写入在提供 `worker_id` 时会校验当前 lease owner；非 owner 更新返回 `WORKER_LEASE_OWNER_MISMATCH`，不会覆盖当前 job row。
- Completed follow-up (2026-06-01): local job and attempt diagnostics now support bounded offset pagination. `GET /analysis/jobs?limit=12&offset=...` and `GET /analysis/jobs/attempts?limit=12&offset=...` feed Backend Status queue/attempt `Newer` / `Older` controls, and the attempts panel no longer slices retry rows locally.
- 仍未完成：真正外部 worker/队列调度器、跨主机分布式 lease enforcement 和跨进程分布式并发限流；当前仍是本地 SQLite/JSON 镜像式闭环。

问题：

- 当前已有 job store、cancel、retry、stale recovery，但仍是轻量 JSON + in-process task。

待完善：

- SQLite job table 与本地 lease metadata。
- worker 心跳。
- 任务队列。
- 并发限制。
- failed node resume。
- 更完整的跨进程 retry history drill-down、分页和外部队列执行视图；当前已有本地 SQLite 队列视图和本地 owner guard，但仍不是分布式外部队列。

完成标准：

- 后端重启后任务状态一致。
- 可以区分 queued、running、cancel requested、cancelled、failed、stale、completed。

### P3-3 生产监控与告警

当前开发状态（2026-05-21）：

- `/api/metrics` 保持原字段兼容，并新增 `productionHealth`。
- `productionHealth` 只读聚合本地 run/job/SignalOps 状态，不触发 LLM 或行情 live call。
- 指标覆盖 24h/7d run 成功率、LLM 调用失败率、market data fallback/mock 率、SignalOps tick 成功率、stale job 数、error budget、alerts 和 sourceErrors。
- Backend Status 页面已读取 `/api/metrics` 并展示 `Production Health`，包括 24h 摘要卡、24h/7d `Health Trends`、LLM failure、market data fallback、SignalOps tick、stale jobs、error budget、alerts/source errors 和 externalCalls 标记。
- 已补齐：`GET /api/ops/alerts/status` 和 admin-gated `POST /api/ops/alerts/dispatch` 会把当前 `productionHealth.alerts` 记录到本地 JSONL outbox；Backend Status 提供 alert channel 状态、最新告警和 admin dispatch 操作。
- 已补齐：设置 `PRODUCTION_ALERT_WEBHOOK_URL` 后，alert dispatch 会尝试 generic JSON webhook 投递，记录 `external_provider`、`external_delivery_status`、`delivery_status`、`delivery_error`、attempt count/limit，并在失败时继续保留本地 outbox；`PRODUCTION_ALERT_WEBHOOK_MAX_ATTEMPTS` 提供 1-5 次 bounded retry。
- 已补齐：`GET /api/ops/logs/status` 会读取本地 structured ops JSONL，Backend Status 提供 ops event log 状态、计数、路径、最新事件和刷新入口；请求日志只记录 request id、method、path、status、duration 和 client，不记录 header/body/query。
- Completed follow-up (2026-06-01): structured ops logs now expose local export readiness for external aggregation. `/ops/logs/status` reports `external_aggregation_ready`, `export_schema`, `retention_policy`, and `redaction_policy`; `/ops/logs/export` returns bounded sanitized `ops_log_export_v1` event bundles with SHA-256 checksum, level/since filters, and no request headers/bodies/query strings.
- 已覆盖 metrics 聚合、本地 alert outbox 和 structured ops log 测试；SignalOps tick 成功率当前明确标注 `latest_only`，因为本地状态只有最近 tick 结果。
- 后续仍需具体厂商告警适配、外部集中日志聚合/长期留存、部署侧调度规则和更长周期趋势图；当前 Backend Status 已具备 24h/7d 可见化入口、本地 outbox 通道、generic webhook provider、bounded retry 展示和本地 ops log 入口。

问题：

- `/api/ready`、`/api/metrics`、本地 alert outbox、`/api/ops/alerts/export` sanitized export bundle、generic webhook alert provider、本地 structured ops log API/UI 已有；厂商级告警规则和集中日志聚合/长期留存仍需部署侧接入。

待完善：

- run 成功率。
- LLM 调用失败率。
- market data fallback 率。
- SignalOps tick 成功率。
- stale job 数。
- error budget。
- productionHealth alert 本地 outbox。

完成标准：

- Backend Status 页面显示近 24 小时/7 天健康趋势、本地 alert outbox、alert export bundle 和本地 structured ops log；外部告警 provider 和集中日志聚合仍需部署侧接入。
- 指标可用于部署告警。

### P3-4 配置中心扩展

当前开发状态（2026-05-21）：

- 配置中心已有 SQLite version/draft/rollback/audit；本轮新增 operator 绑定，配置版本 `created_by` 不再固定为 `system`。
- Agent runtime 写路径已接入统一配置治理审计：runtime settings、LLM profile、market data profile、agent LLM assignment、data_sources_config 和 market_data_adapter_config 会写入 `config_versions` / `audit_logs`，记录 scope/surface/subject、operator、diff、summary、audit_id 和 version_id。
- `/config/versions?include_external=true` 与 Config Versions 页面已能展示 Backend Tuning 和 Agent runtime 外部配置版本；审计/版本快照会脱敏 API key、token、secret、authorization 等字段。
- Config Versions 现在显示 `approval_required`、`effective_scope`、`snapshot_redacted`、`rollback_policy` 和 `approval_gate`，并支持按 surface、actor、status 过滤；外部 runtime 配置会明确标记 `secret_safe_rollback_required`，避免把脱敏 snapshot 当作可直接恢复的密钥来源。
- 已补齐：外部 Agent Runtime 配置版本会暴露公开的不可变 `runtime-secret:v1:...:version:...` vault ref 清单和 `BLOCKED_PENDING_VAULT_VERSION_APPROVAL` 审批门证据。
- 已补齐：`POST /api/config/external-restore` 提供 admin-only approved restore executor，会校验 approval id、reason、`confirm_secret_safe=true` 和可打开的 vault-version refs 后按 Agent Runtime surface 恢复指定配置面；`data_sources_config` 恢复只应用 data-source 配置和对应 secret refs，并同步恢复后的 Tushare token 到行情 profile token wiring，不再过度恢复无关 runtime 配置。Config Versions approved restore UI 已从 `window.prompt` 改为 governed modal，要求 approval id、reason 和 secret-safe checkbox 后才能提交。
- 已补齐：`npm.cmd run smoke:strict-auth-browser` 通过 SPA 导航覆盖 `/config-versions` approved restore 弹窗，验证无浏览器 prompt、提交体包含审批字段和 `confirm_secret_safe=true`，且请求携带 strict-auth Bearer token；浏览器 smoke 现在还会列出、筛选并恢复 `agent_runtime:data_sources_config` 与 `agent_runtime:market_data_adapter_config`，避免只覆盖单一恢复面。
- 仍未完成：非 Agent Runtime 外部配置面若未来进入 `config_versions`，还需要各自的 surface-specific restore executor；无审批的 unattended automatic rollback 仍保持禁用。

问题：

- Backend Tuning 已迁入 SQLite，但 schema 偏窄。

待完善：

- Agent runtime、market data profile、Backend Tuning 三套配置统一版本治理。
- 所有配置写入统一 audit log。
- 配置 diff、回滚、审批人和生效范围。
- Secret-safe rollback：外部 runtime 配置回滚时不得从脱敏 snapshot 还原密钥材料。

完成标准：

- 任意配置变更都可回溯、回滚和复核。

## 8. P4：平台扩展和长期工程治理

### P4-1 插件系统从 sandbox preview 到平台化

问题：

- 当前插件系统安全边界正确：read-only、schema、sandbox、交易动作硬阻断。
- 已补齐：插件 archive 生命周期已上线，`POST /api/plugins/{plugin_id}/archive` 会禁用插件、写 `ARCHIVE` audit、记录 lifecycle metadata，并从 runtime plan 排除；Plugin Registry 页面提供 admin-gated archive action，strict-auth browser smoke 会验证 Bearer auth 和归档状态渲染。
- 已补齐：插件 runtime plan 返回 `resource_summary`，每个 agent 的 `resource_limits` 会按 `MAX_SANDBOX_LIMITS` 裁剪并返回 `resource_limit_warnings`；Plugin Registry 页面展示资源配额摘要，strict-auth browser smoke 会验证该摘要通过 Bearer-auth API 返回并可见渲染。
- 已补齐：插件 upgrade 生命周期已上线，`POST /api/plugins/{plugin_id}/upgrade` 会校验新版本、拒绝降级/同版本、写 `UPGRADE` audit、记录 `upgrade_history` 和 operator；Plugin Registry 页面提供 admin-gated upgrade action，strict-auth browser smoke 会在 archive 前验证升级路径。
- 已补齐：插件 package artifact migration 元数据已接入 upgrade 请求，记录 artifact id/source/checksum、`package_migration.steps`、upgrade-history package evidence，并拒绝需要代码执行的迁移步骤。
- 已补齐：插件真实 package artifact storage/upload/hash verification 已具备基础链路，`POST /api/plugins/{plugin_id}/artifacts` 会存储上传包、计算并校验服务端 SHA-256、执行 local SHA-256 denylist scan、metadata-only zip path scan 和 external malware-scan sidecar verdict ingestion、记录 retention metadata，并写入 manifest/lifecycle/audit；`POST /api/plugins/artifacts/cleanup` 提供 admin-gated local retention cleanup，默认 dry-run，实际删除需要显式 `dry_run=false` 且路径必须限制在 artifact root；Plugin Registry 和 strict-auth browser smoke 覆盖上传、外部扫描证据、校验、cleanup dry-run、verified artifact upgrade 和 archive。
- 还不是完整插件运行平台。

待完善：

- 插件生命周期：install/register、disable、archive、governed upgrade、package artifact migration metadata 和真实 artifact storage/upload/hash verification 已具备基础链路。
- 插件资源配额已有 runtime plan 可见化和上限裁剪；运行统计已有基于 `plugin_audit` 的近期窗口聚合、按日 usage history 和 Plugin Registry 可视化；artifact retention metadata、local SHA-256 denylist scan、metadata-only zip path scan、external scan sidecar verdict ingestion 和 local retention cleanup/dry-run 已具备，生产级 object-storage lifecycle、厂商扫描服务部署和威胁情报 feed 同步仍需设计。
- 插件输出只进入 observation、review note 或 evidence，不绕过 DVG/Risk/Execution。
- 更高权限插件另开安全设计，不默认开放。

### P4-2 SQLite + JSON 状态收敛

问题：

- 目前 SQLite 和 JSON 并存，排障成本高。

待完善：

- 将核心 runtime artifacts、analysis jobs、auto paper config、run snapshots 逐步迁入 SQLite 或建立明确归档策略。
- JSON 只保留可导出 artifact 或兼容导入。
- SQLite 备份/恢复脚本已有本地演练入口，已有模拟离机复制 checksum 演练，且 `smoke:storage-offhost-restore` 已覆盖临时 `deploy/backend-storage`、secret vault 和 key file 的模拟离机复制/恢复/逐文件 SHA-256 校验；真实离机目标、保留策略、调度责任、访问控制和周期性生产恢复记录仍需生产 runbook。

完成标准：

- 每类状态有唯一权威存储位置。
- backup/restore 明确覆盖哪些状态。

### P4-3 E2E 和浏览器可见状态测试

问题：

- 当前 build/lint/backend tests 通过，但缺少稳定浏览器 E2E。

当前进展（2026-05-21）：

- 新增 `scripts/smoke-frontend-routes.ps1` 和 `npm.cmd run smoke:frontend`。
- `scripts/smoke-research-closure-browser.mjs` 已扩展 `/backend` browser-visible 断言：注入 `/api/metrics.productionHealth` 24h/7d + sourceErrors fixture，并验证 `Health Trends`、Source Errors、Portfolio/New Task/Research closed-loop 主链路。
- smoke 会基于 `frontend/dist` 临时启动静态预览，检查 `/`、`/new-task`、`/signalops`、`/research-lab`、`/config-versions`、`/backend`、`/backtest` 均能返回 React 根文档，并自动停止预览进程；Research closure browser smoke 已覆盖 Backtest 深链和 stale request cancellation，strict-auth browser smoke 已覆盖 Dashboard run/provenance/knowledge regression、Backend Status attempt diagnostics、analysis job queue、run_id drill-down、seeded attempt row、Config Versions approved restore 弹窗和多 surface 筛选/恢复、SignalOps 边界、SignalOps forced tick、daily review、manual command、review-decision approval/rejection、Research Lab closed-loop sample、Agent DAG zoom/fit controls / pane drag-pan / mouse-click / multi-node keyboard selected evidence / failure-degraded fixture / source-classification state matrix fixture、Live Run stream、New Task -> Live Run -> Final report 和 Backtest sample run。

待完善：

- 已补齐：Dashboard strict-auth browser smoke 会用 seeded analysis run 验证 run history/detail、knowledge regression API、数据可信区和 Agent 执行链可渲染。
- 已补齐：Backend Status analysis job queue strict-auth browser smoke 会用 seeded worker-mode run 验证 `/api/analysis/jobs?limit=12` 携带 Bearer auth、队列视图渲染同一 run、queue name、worker/concurrency 元数据可见。
- Config Versions 非 Agent Runtime 恢复面、Live Run stream 和复杂页面多状态的更完整 Playwright E2E；Agent Runtime approved restore 弹窗路径与 `data_sources_config` / `market_data_adapter_config` 多 surface 筛选恢复已有 strict-auth browser smoke，Agent DAG zoom/fit 控件、pane drag-pan、鼠标点击、二节点键盘选中详情、基础 LLM degraded/failed fixture 和 source-classification state matrix fixture 已有 strict-auth browser smoke，SignalOps forced tick / daily review / manual command / review-decision 已有 strict-auth browser smoke。
- 已补齐：New Task -> Live Run -> Final report strict-auth browser smoke 会创建任务、验证 Live Run stream query token、Live Run 任务面板和 Final Writer report API/页面同 run 渲染。
- 已补齐：SignalOps forced tick strict-auth browser smoke 会在页面 Boundary / manual operations 窗口点击 `强制跟进`，验证 `POST /api/signalops/auto-paper/tick` 携带 Bearer auth，且响应保持 `SIM_*`、`CONFIGURED_DISABLED` 和 simulation active module 边界。
- 已补齐：SignalOps daily review 和 manual command strict-auth browser smoke 会点击页面 `收盘复盘` 与股票池 `FORCE_OPEN_BUY` 沙箱指令，验证 `POST /api/signalops/auto-paper/daily-review`、`POST /api/signalops/auto-paper/command` 携带 Bearer auth，并检查响应和页面摘要保持 simulation-only / no-real-trade 边界。
- 已补齐：SignalOps review-decision strict-auth browser smoke 使用确定性审查队列 fixture，在页面审查窗口点击 approval 和 rejection，验证 `POST /api/signalops/auto-paper/review-decisions` 的 Bearer auth、payload review fields、`APPROVE_SIMULATION_CANDIDATE` / `REJECT_CANDIDATE` 响应边界和页面 `已应用到模拟` / `已驳回` 渲染。
- 已补齐：Research Lab closed-loop strict-auth browser smoke 会 SPA 进入 `/research-lab/research`，点击一键 P2 样例闭环按钮，验证 `POST /api/research/p2/closed-loop-sample` 携带 Bearer auth、返回 portfolio/run/SignalOps/backtest/research/case/knowledge/evaluation/knowledge version 全链路 ID，并在页面渲染同一批 ID 和弱证据阻断原因。
- 已补齐：Research Lab -> SignalOps selected-signal strict-auth browser smoke 会从 P2 样例轮次点击 SignalOps evidence 链接，验证 `iteration_id` 与 `signal_id` 进入 `/signalops`，并确认所选 SignalOps detail 通过 Bearer-auth API 加载。
- 已补齐：Backtest sample run strict-auth browser smoke 会 SPA 进入 `/research-lab/backtest`，点击页面运行按钮创建 MOCK 样例回测，验证 Bearer auth、`signal_source=MOCK` 和同一 run id 的详情渲染。
- 已补齐：Backtest experiment-package strict-auth browser smoke 会点击 `Experiment package`，验证 `/api/research/backtest/runs/{run_id}/experiment-package` 携带 Bearer auth，并解析浏览器下载的 JSON package，检查 `BTEP_`、schema、run id、dataPackageHash 和 simulation-only 边界。

完成标准：

- 最小 E2E 可在本地一键执行。
- 页面可见状态不再只靠人工检查。

### P4-4 文档和历史编码清理

问题：

- 保留文档总体可用，但历史文档和部分运行 artifact 中仍可见乱码或旧 mock 描述。

待完善：

- README 和核心 docs 保持 UTF-8 可读。
- 旧 mock/legacy 内容明确标记为示例或归档。
- 新开发者入口只指向 `frontend/` 和当前启动脚本。
- 已补齐：`backend/tests/test_repo_hygiene.py` 的 UTF-8/mojibake guard 现在覆盖 `README.md`、`docs`、`frontend/src` 和 `backend/app`。
- 已补齐：旧 `OPEN_DEVELOPMENT_BACKLOG.md` 已删除，`docs/TESTING_GUIDE.md` 不再把它标记为当前计划或归档入口，repo hygiene guard 会防止其重新成为当前计划来源。

完成标准：

- `README.md`、`docs/DEPLOYMENT.md`、`docs/TESTING_GUIDE.md`、`docs/API_CONTRACT.md` 能无乱码阅读，并被 repo hygiene 编码 guard 覆盖。
- root `src` 只作为历史参考或被清理。

## 9. 当前执行顺序

当前开发不再按旧 P0-P4 待办清单推进；旧 backlog 已删除，闭环证据以 `DEVELOPMENT_LOG.md`、`NEXT_DEVELOPMENT_PLAN.md` 和本文件最新 follow-up 为准。

1. 审查修复类变更：2026-05-21 代码审查修复指南已完成并归档删除；维持 R1-R13、T1-T3、D1-D3 的已闭环状态。新增审查建议应写入 `DEVELOPMENT_LOG.md` 并同步当前契约文档，不恢复旧专项指南。
2. 当前 Phase 1-3 本地能力：继续以 `validate:phase1-3` 和 `validate:module-participation` 证明研究闭环、真实浏览器 E2E、本地 worker/queue 和模块参与。
3. 生产化长期能力：外部队列、集中日志/告警、对象存储生命周期、插件沙箱和实盘架构只作为独立设计或部署项目，不混入默认 simulation-only 研究控制台。

## 10. 每轮开发验收命令

按改动面选择最小但足够的验收；涉及广泛模块、审查修复或稳定性收尾时，优先跑根级门禁：

```powershell
npm.cmd run validate:phase1-3
npm.cmd run validate:premerge
```

局部开发常用入口：

```powershell
npm.cmd run test:backend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
npm.cmd run smoke:frontend
```

模块参与和浏览器闭环：

```powershell
npm.cmd run validate:module-participation
npm.cmd run smoke:research-closure:browser
npm.cmd run smoke:strict-auth-browser:matrix
```

涉及页面体验时，仍可启动本地开发环境检查：

- 启动：`.\start-dev.ps1 -Open`
- 检查：`http://127.0.0.1:5174` 或启动器打印的实际前端地址
- 重点页面：`/`、`/portfolio`、`/new-task`、`/live-run`、`/signalops`、`/research-lab/*`、`/backend`、`/plugins`

## 11. 当前目标状态

当前 simulation-only 研究控制台的本轮目标状态：

- 2026-05-21 代码审查修复指南已完成并归档删除；R1-R13、T1-T3、D1-D3 没有剩余当前开发项。
- Phase 1-3 本地闭环有根级验收命令和浏览器 smoke 证据。
- 每个主要模块可通过 `validate:module-participation` 参与当前研究闭环。
- 用户能在核心页面判断数据来源、证据强度、缺失项、权限边界和模拟交易状态。
- 系统继续保持 `simulation_only=true`、`is_real_trade=false`、`SIM_*` 和无真实券商下单 API 的安全边界。
- 外部 worker/queue、厂商告警、对象存储生命周期、任意代码插件沙箱和实盘交易系统仍是独立长期工程或设计项目，不属于当前默认能力。
