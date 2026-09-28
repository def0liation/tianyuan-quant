# Development Log

## How to read this log

- Recent entries stay detailed enough to audit exact scope, validation, and risk.
- Older entries are compressed by date and theme so the current planning signal remains readable.
- Detailed pre-compression wording is intentionally removed from this working document; use git history if exact old command transcripts are needed.
- New entries should be prepended above the current detailed section and include Scope, Changes, Validation, and Risk.

## 2026-07-02 - External worker/queue design contract (P3 kickoff)

Type: production-engineering design contract / queue platform planning / documentation-only slice

Scope: land the P3 "external worker/queue" design contract as `docs/EXTERNAL_WORKER_QUEUE_DESIGN.md`. This slice changes no runtime code, no schema, no API, and no trading/simulation boundary.

Changes:
- Added the design doc with a verified current-state inventory (BEGIN IMMEDIATE claim CAS, heartbeat-derived lease metadata, stale reconcile on read paths, worker loop with cooperative cancel, `analysis_job_external_queue_status_v1` sidecar), the concrete gap list (no DLQ, no lease-expiry reclaim, no queue backend abstraction, single-host SQLite, JSON dual-write), a `QueueBackend` protocol, a backend decision matrix recommending Postgres `FOR UPDATE SKIP LOCKED` with SQLite kept as the default reference implementation, an incremental state machine adding `DEAD_LETTER`, fencing/idempotency rules keyed on `(run_id, attempt, worker_id)`, phased delivery A-D with per-phase acceptance commands, and a risk list.

Validation:
- Documentation-only diff; current-state claims were verified against `backend/app/core/analysis_job_store.py` and `backend/app/core/analysis_worker.py` in this session.

Risk:
- None to runtime behavior. Phase A (local DLQ + lease reclaim) is the next implementation entry point and requires Windows-side focused pytest plus `smoke:analysis-worker`.

## 2026-07-02 - New Task preflight workbench redesign landed with Material evidence compliance

Type: frontend page redesign completion / shared Material evidence guard / repo EOL hygiene

Scope: complete and land the in-flight New Task page redesign (preflight rail, checklist, run-mode cards, agent-chain preview, governance evidence block) while keeping every existing new-task smoke contract, role boundary, and simulation-only boundary copy intact. This slice does not change backend APIs, auth/session behavior, SignalOps semantics, database migrations, or the simulation-only trading boundary.

Changes:
- Landed the redesigned NewTaskPage: sticky PREFLIGHT rail with live verdict, form-derived checklist, run-mode/task-type cards, representative agent-chain preview, and the governance panel; the non-blocking Live Run handoff (`void retryTransientTaskStep(getAnalysisRun)`) is preserved.
- Restored the shared Material data-presentation evidence required by `smoke:frontend`: the default LLM health chip now renders through `StatusPill` from `common/Material`, with `llmStatusPillTone` mapping runtime health to pill tones (replaces the page-local Badge usage for that chip only).
- Reverted 33 files that contained only CRLF line-ending churn back to their committed LF content, and added `.gitattributes` with `* text=auto` so editor CRLF conversion can no longer surface as whole-file diffs.

Validation:
- Green: frontend `tsc --noEmit` passed over the full source tree.
- Green: `eslint . --report-unused-disable-directives --max-warnings 0` passed using the repo-root plugin versions.
- Green: all `smoke-frontend-routes.ps1` NewTaskPage source assertions re-verified statically, including the shared-Material page gate, institution-table gates, researcher-gated run creation hooks, and the negated non-blocking-hydration check.
- Not rerun in this environment (Linux sandbox; PowerShell/browser gates need the Windows dev machine): `npm.cmd run build`, `npm.cmd run smoke:frontend`, and `npm.cmd run smoke:strict-auth-browser:*`. Run these before merging the branch.

Risk:
- Medium-low frontend-only slice. All data-testid hooks, role short-circuits, and simulation boundary copy are preserved; the visual shell is new. The StatusPill swap changes the LLM health chip styling source, not its semantics. Windows-side build, frontend smoke, and strict-auth browser gates remain outstanding for this slice.

## 2026-06-27 - Market legacy redirect preserves run context

Type: legacy route redirect query preservation / strict-auth browser smoke / static frontend smoke

Scope: make legacy `/market?run_id=...` preserve its query/hash while redirecting into the current `/quant-core` module, so cold strict-auth deep links hydrate the intended analysis run and still show QuantCore's simulation-only boundary. This is a frontend routing and smoke-contract slice only; it does not change market-data fetching, analysis APIs, auth/session/cookie behavior, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Replaced routeManifest redirect rendering with `RedirectWithSearch`, which carries `location.search` and `location.hash` into the target route.
- Tightened `smoke:frontend` so `/market -> /quant-core` remains registered and legacy redirects must preserve query/hash.
- Added strict-auth browser coverage for `/market?run_id=...`, asserting redirect to `/quant-core?run_id=...`, authenticated run hydrate, visible QuantCore boundary, and the topbar run id.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `App legacy redirects must preserve query/hash for run-linked routes` before the redirect helper was added.
- Red diagnostic: `npm.cmd run smoke:strict-auth-browser:platform` originally timed out waiting for `market-page`, exposing that `/market` is a legacy redirect to `/quant-core`, not an active MarketPage route.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Market legacy redirect preserves run context`.

Risk:
- Low frontend routing change. Query/hash preservation applies to all routeManifest redirects, which is intended for run-linked legacy routes and should be benign for routes without query/hash. The full default `validate:premerge` gate was not rerun after this focused slice; script syntax, frontend smoke, typecheck, lint, build, and platform strict-auth browser gates passed.

## 2026-06-27 - Operator token reload persistence and clear regression coverage

Type: operator API token reload persistence / strict-auth browser smoke / static frontend smoke

Scope: close the browser-regression gap introduced by same-tab operator token persistence: prove reload keeps the current-tab token for API requests, and prove the Clear action removes that token before a reload. This is a frontend auth-token persistence and browser-smoke slice only; it does not change backend auth middleware, token values, role semantics, cookie name/domain/path/sameSite/secure behavior, API schemas, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Added a stable `backend-operator-token-clear` hook to the Backend Status operator token Clear control.
- Tightened `smoke:frontend` so Backend Status must expose both apply/clear token hooks and the strict-auth browser script must cover token reload persistence plus clear-after-reload rejection.
- Extended the strict-auth browser bootstrap to verify `/api/metrics` returns 200 with the expected Bearer header after reloading `/backend`, then verify clearing the token and reloading `/backend` makes `/api/metrics` return 401 without an Authorization header.
- Reapplied the token after the clear regression check so the existing portfolio/live/plugin/AntiConclusion scenario chain continues under the expected authenticated strict-auth session.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `BackendStatusPage strict-auth token controls are missing reload or clear browser coverage` after the static guard required clear/reload browser coverage.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser operator token reload persistence`, `ok strict-auth browser operator token clear removes reload auth`, and `ok strict-auth browser AntiConclusion cold deep link hydration`.

Risk:
- Low-medium frontend auth persistence change. This verifies header-based operator API auth across same-tab reload and Clear behavior, including the real request header on `/api/metrics`; it does not prove cookie auth behavior because this path does not use cookies. The full default `validate:premerge` gate was not rerun after this focused slice; frontend smoke, browser-script syntax, typecheck, lint, build, and portfolio-live-plugin strict-auth browser gates passed.

## 2026-06-27 - AntiConclusion cold deep-link hydrate and same-tab auth persistence

Type: AntiConclusion run-context hydrate / operator API token persistence / static frontend smoke / strict-auth browser smoke

Scope: make a cold `/anti-conclusion?run_id=...` load hydrate its own run context under strict-auth instead of relying on a previously hydrated Final Writer page. This is a frontend run-context and same-tab auth persistence slice only; it does not change backend analysis APIs, report generation, final-writer semantics, auth token values, role semantics, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Added `run_id` query hydration to AntiConclusion using `refreshRun(linkedRunId)`, with a loading state and visible `anti-conclusion-current-run-id`.
- Persisted the operator API token in current-tab `sessionStorage` so strict-auth page reloads keep the Authorization header, while keeping the token out of long-lived `localStorage`.
- Tightened `smoke:frontend` so AntiConclusion requires deep-link hydrate hooks, cold strict-auth browser coverage, and same-tab token persistence markers.
- Extended the strict-auth portfolio-live-plugin browser scenario to reload `/anti-conclusion?run_id=...` and verify the visible review-only simulation boundary after cold hydrate.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `AntiConclusionPage is missing visible review-only simulation-boundary guardrails` after the static guard required cold deep-link hydrate and browser coverage.
- Red diagnostic: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` initially failed after full reload because `/api/analysis/runs/...` returned 401 without same-tab token persistence.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser AntiConclusion cold deep link hydration`.

Risk:
- Medium-low frontend/auth persistence change. The token now survives reloads inside the same browser tab via `sessionStorage`, but is still cleared by the existing clear action and is not written to `localStorage`. This does not prove cross-tab, cookie, or domain/path behavior because this app path uses operator API token headers rather than cookie auth. The full default `validate:premerge` gate was not rerun after this focused slice; frontend smoke, browser-script syntax, typecheck, lint, build, and portfolio-live-plugin strict-auth browser gates passed.

## 2026-06-27 - AntiConclusion strict-auth browser boundary coverage

Type: AntiConclusion visible boundary / static frontend smoke / strict-auth browser smoke

Scope: verify the `/anti-conclusion` review-only simulation boundary on a real strict-auth browser path after the New Task -> Live Run -> Final Writer chain has hydrated the current run. This is a frontend smoke-contract and browser-coverage slice only; it does not change AntiConclusion rendering semantics beyond the existing visible boundary, final-writer generation, analysis-run APIs, auth/session/cookie behavior, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Tightened `smoke:frontend` so AntiConclusionPage now requires strict-auth browser coverage for `anti-conclusion-simulation-boundary`.
- Added `assertAntiConclusionVisibleBoundary` to the strict-auth browser smoke and routed the existing portfolio-live-plugin scenario from Final Writer into `/anti-conclusion`.
- Verified the browser-visible boundary preserves `simulation_only=true`, `is_real_trade=false`, `evidence_usage=anti_conclusion_review_only`, `strong_conclusion_allowed=false`, and `SIM_*`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `AntiConclusionPage is missing visible review-only simulation-boundary guardrails` after the static guard required strict-auth browser coverage.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser AntiConclusion visible review boundary`.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.

Risk:
- Low smoke-contract change. The browser path reuses the already-hydrated run context from Final Writer and only asserts the visible AntiConclusion boundary, so it does not prove a cold `/anti-conclusion` deep link can hydrate by itself. The full default `validate:premerge` gate was not rerun after this focused browser-coverage slice; frontend smoke, browser-script syntax, portfolio-live-plugin strict-auth browser, typecheck, lint, and build gates passed.

## 2026-06-27 - AntiConclusion review-only simulation boundary visibility

Type: AntiConclusion UI boundary / static frontend smoke

Scope: expose a visible review-only simulation boundary on the `/anti-conclusion` route so final-action consistency, allowed/forbidden action review, kill-switch status, and final output snippets are read as upstream gate review evidence only. This is a frontend UI and smoke-contract slice only; it does not change final-writer generation, analysis-run hydration, auth/session/cookie behavior, API schemas, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `simulation_only=true`, `is_real_trade=false`, `evidence_usage=anti_conclusion_review_only`, `strong_conclusion_allowed=false`, and `SIM_*` in `anti-conclusion-simulation-boundary`.
- Tightened `smoke:frontend` so AntiConclusionPage fails if the visible review-only simulation boundary is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `AntiConclusionPage is missing visible review-only simulation-boundary guardrails` after the static guard required the AntiConclusion boundary.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.

Risk:
- Low frontend UI and smoke-contract change. The boundary is static display text under the route title and does not alter the current-run store, backend report chain, final-writer content, or execution controls. This slice did not add strict-auth browser coverage for `/anti-conclusion`; a future loop can extend the existing New Task -> Live Run -> Final Writer browser chain to navigate into AntiConclusion with an already-hydrated run context. The full default `validate:premerge` gate was not rerun after this focused slice; static frontend and frontend type/lint/build gates passed.

## 2026-06-26 - Technical Kline QuantCore browser boundary coverage

Type: Technical Kline QuantCore-embedded governance boundary UI / static frontend smoke / strict-auth browser smoke

Scope: expose and verify the Technical Kline case-governance simulation boundary on the real `/quant-core` path, where Technical Kline governance and Case Library sedimentation are actually reachable. This is a frontend UI and smoke-contract slice only; it does not change Technical Kline backend APIs, Tushare access, governance save/rollback behavior, case persistence semantics, auth/session/cookie behavior, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `simulation_only=true`, `is_real_trade=false`, `evidence_usage=technical_kline_review_only`, `strong_conclusion_allowed=false`, and `SIM_*` in `technical-kline-case-governance-simulation-boundary`.
- Tightened `smoke:frontend` so the QuantCore-embedded Technical Kline case-governance card and its strict-auth browser assertion must both preserve the boundary.
- Added a strict-auth browser assertion in the existing platform Technical Kline case-governance flow before the Case Library sedimentation action.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `QuantCore is missing active Technical Kline Case Library sedimentation linkage or role gating` after the static guard required the browser assertion.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Technical Kline visible review boundary`.

Risk:
- Low frontend UI and smoke-contract change. The tested path is the real QuantCore-embedded Technical Kline governance card; the legacy `/technical-kline` redirect remains untouched. This slice does not exercise live Tushare provider behavior or backend Technical Kline calculations beyond the existing strict-auth governance/case fixtures. The full default `validate:premerge` gate was not rerun after this focused browser-coverage slice; static frontend, browser-script syntax, frontend type/lint/build, and platform strict-auth browser gates passed. Next loop boundary should look for another core path that still has only static coverage or weak failure-path proof.

## 2026-06-26 - Technical Kline review-only simulation boundary visibility

Type: Technical Kline UI boundary / static frontend smoke

Scope: expose a visible review-only simulation boundary on the Technical Kline page so technical bias, signal backtest, and governance/case actions are read as research evidence only. This is a frontend UI and smoke-contract slice only; it does not change Technical Kline API schemas, Tushare data access, governance save/rollback behavior, case sedimentation, auth/session/cookie behavior, database migrations, SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `simulation_only=true`, `is_real_trade=false`, `evidence_usage=technical_kline_review_only`, `strong_conclusion_allowed=false`, and `SIM_*` in `technical-kline-simulation-boundary`.
- Tightened `smoke:frontend` so TechnicalKlinePage fails if the visible review-only simulation boundary is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `TechnicalKlinePage is missing visible role-aware governance/case write gating` after the static guard required the Technical Kline boundary.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.

Risk:
- Low frontend UI and smoke-contract change. The boundary is static display text beside the existing role/governance guard; it does not exercise live Tushare provider behavior, backend Technical Kline endpoints, or strict-auth browser rendering. The full default `validate:premerge` gate was not rerun after this focused Technical Kline slice; the static frontend and frontend type/lint/build gates passed. Next loop boundary should prefer a browser-visible or backend contract slice for a path that is still not covered by strict-auth browser smoke.

## 2026-06-26 - New Task portfolio preflight simulation boundary visibility

Type: New Task portfolio-context preflight boundary UI / static frontend smoke / strict-auth browser smoke

Scope: expose a visible preflight-only simulation boundary inside the New Task portfolio risk prompt so portfolio snapshot risk, broker-template quality, and current-position context remain review evidence before creating a run. This is a frontend UI and smoke-contract slice only; it does not change portfolio import parsing, analysis-run creation/start behavior, Live Run handoff, auth/session/cookie behavior, API schemas, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `preflight_only=true`, `simulation_only=true`, `is_real_trade=false`, `evidence_usage=portfolio_context_only`, `strong_conclusion_allowed=false`, and `SIM_*` in `new-task-portfolio-risk-boundary`.
- Tightened `smoke:frontend` so NewTaskPage fails if the portfolio preflight boundary or its strict-auth browser assertion is removed.
- Added a strict-auth browser assertion that the real Portfolio -> New Task flow exposes the portfolio preflight boundary before the existing New Task run-governance boundary and Live Run handoff checks continue.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `NewTaskPage is missing portfolio pre-task risk prompt linkage` after the static guard required the portfolio preflight boundary.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser New Task portfolio risk boundary`.

Risk:
- Low frontend UI and smoke-contract change. The boundary is static display text plus browser-visible verification around the existing Portfolio -> New Task path; it does not alter backend run creation, task startup, portfolio persistence, or execution behavior. The full default `validate:premerge` gate was not rerun after this focused New Task slice; the static frontend, browser-script syntax, frontend type/lint/build, and portfolio-live-plugin strict-auth browser gates passed.

## 2026-06-26 - Data Reliability diagnostic-only boundary visibility

Type: Data Reliability diagnostic boundary UI / static frontend smoke / strict-auth browser smoke

Scope: expose a visible diagnostic-only boundary on the Data Reliability page so adapter, freshness, fallback, provenance, and symbol-check results are clearly audit evidence rather than trading conclusions. This is a frontend UI and smoke-contract slice only; it does not change data-reliability backend checks, external provider calls, auth/session/cookie behavior, API schemas, database migrations, Research/Backtest/SignalOps handoff behavior, or order routing.

Changes:
- Rendered `diagnostic_only=true`, `simulation_only=true`, `is_real_trade=false`, `evidence_usage=monitoring_only`, `strong_conclusion_allowed=false`, and `order_namespace=none` in `data-reliability-diagnostic-boundary`.
- Tightened `smoke:frontend` so DataReliabilityPage fails if the diagnostic-only boundary or strict-auth browser assertion is removed.
- Added a strict-auth browser assertion that the real `/data-reliability` DOM exposes the diagnostic-only boundary before provenance, freshness, fallback, adapter-event, adapter-check, and symbol-check assertions continue.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `DataReliabilityPage is missing source freshness/fallback/provenance coverage` after the static guard required the diagnostic-only boundary.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Data Reliability diagnostic boundary`.

Risk:
- Low frontend UI and smoke-contract change. The boundary is static display text and browser-visible verification around existing Data Reliability read/write-smoke paths; it does not validate live external provider behavior beyond the existing fixture coverage. The full default `validate:premerge` gate was not rerun after this focused Data Reliability slice; the static frontend, browser-script syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-26 - Global Market auto-stock strict-auth browser boundary

Type: Global Market auto-stock selector UI boundary / static frontend smoke / strict-auth browser smoke

Scope: add strict-auth browser coverage for the Global Market automatic stock-opportunity selector review-gate boundary. This is a browser-smoke and smoke-contract slice only; it does not change market-data adapters, Global Market response schemas, auth/session/cookie behavior, database migrations, Research/Backtest/SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Added a strict-auth browser fixture for `/api/market-data/global?range=4m` that verifies the request carries the expected Authorization bearer token.
- Asserted the real `/global-market` DOM renders `global-market-auto-stock-boundary`, a candidate card, source text, and the complete `simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*` boundary.
- Tightened `smoke:frontend` so GlobalMarketPage fails if the strict-auth browser scenario is removed or stops asserting the Global Market auto-stock boundary.
- Added the Global Market boundary scenario to the `platform` strict-auth browser group.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `GlobalMarketPage is missing auto stock selector research-only guardrails` after the static guard required strict-auth browser coverage.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Global Market auto-stock review boundary`.

Risk:
- Low browser-smoke and static-contract change. The fixture validates the browser-visible Global Market read path and bearer-token propagation, but this slice does not exercise live external market-data providers or backend adapter arbitration. The full default `validate:premerge` gate was not rerun after this focused Global Market slice; the static frontend, browser-script syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-26 - Global Market auto-stock review-gate boundary visibility

Type: Global Market auto-stock selector UI boundary / static frontend smoke

Scope: expose the complete review-gate simulation boundary in the Global Market automatic stock-opportunity selector. This is a frontend UI and smoke-contract slice only; it does not change market-data adapters, Global Market response schemas, auth/session/cookie behavior, database migrations, Research/Backtest/SignalOps handoff behavior, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `simulation_only=true`, `is_real_trade=false`, `evidence_usage=review_gate_only`, `strong_conclusion_allowed=false`, and `SIM_*` in `global-market-auto-stock-boundary`.
- Tightened `smoke:frontend` so GlobalMarketPage fails if the auto-stock selector drops the complete review-gate boundary.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `GlobalMarketPage is missing auto stock selector research-only guardrails` after the static guard required the complete review-gate boundary.
- Green: `npm.cmd run smoke:frontend` passed after the Global Market UI rendered the new boundary text.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.

Risk:
- Low frontend UI and smoke-contract change. This slice keeps Global Market auto-stock output as review-gated research candidates only; it does not add a strict-auth browser assertion because the current strict-auth scenario groups do not exercise `/global-market`. The full default `validate:premerge` gate was not rerun after this focused Global Market slice; the static frontend and frontend type/lint/build gates passed.

## 2026-06-26 - Live Run terminal stream boundary visibility

Type: Live Run terminal stream UI boundary / static frontend smoke / strict-auth browser smoke

Scope: expose `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` in Live Run terminal stream events that already declare `simulation_only=true`, `is_real_trade=false`, and the `SIM_*` order namespace. This is a frontend UI and smoke-contract slice only; it does not change SSE transport auth, backend stream generation, API schemas, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Live Run terminal stream boundary text so live SSE events render `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended the analysis store's persisted stream-event boundary text with the same fields so refreshed run history and current live events stay consistent.
- Tightened `smoke:frontend` so the Live Run component and analysis store fail if the terminal stream boundary drops those fields.
- Tightened the portfolio-live-plugin strict-auth browser fixture so terminal stream events send and assert the complete visible boundary in the real `/live-run` DOM.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `analysis store is missing same-run live/stream event merge protection or guarded streamEvents contract` after the static guard required the new Live Run stream boundary fields.
- Green: `npm.cmd run smoke:frontend` passed after Live Run and the analysis store rendered the new fields.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed for the broader platform scenario group.
- Green: `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser live-run terminal stream event`.

Risk:
- Low frontend UI and smoke-contract change. Missing stream payload `evidence_usage` still falls back to the display-safe `simulation_only` marker rather than making this slice a backend contract break; payloads that explicitly set `strong_conclusion_allowed=true` will display that value instead of hiding it. The full default `validate:premerge` gate was not rerun after this focused Live Run slice; the static frontend, browser-script syntax, frontend type/lint/build, platform strict-auth browser, and portfolio-live-plugin strict-auth browser gates passed.

## 2026-06-26 - Backtest verdict-inputs SIM boundary visibility

Type: Backtest Research verdict-inputs UI boundary / static frontend smoke / strict-auth browser smoke

Scope: expose the `SIM_*` marker in the visible Backtest verdict-inputs boundary after a Backtest run refreshes Research verdict inputs. This is a frontend UI and smoke-contract slice only; it does not change Backtest execution, Research verdict input generation, API schemas, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `SIM_*` beside `evidence_usage`, `supporting_only`, `simulation_only`, `is_real_trade`, and `strong_conclusion_allowed=false` in `backtest-verdict-inputs-boundary`.
- Tightened `smoke:frontend` so Backtest fails if the verdict-inputs boundary drops the `SIM_*` marker.
- Tightened the research-backtest strict-auth browser assertion so the real Backtest verdict-inputs DOM must include `SIM_*`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `BacktestPage is missing browser-visible sample-run hooks or strict-auth Backtest sample coverage` after the static guard required `SIM_*` in the verdict-inputs boundary.
- Green: `npm.cmd run smoke:frontend` passed after the Backtest UI rendered the new marker.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Research Backtest visible verdict-inputs boundary`.

Risk:
- Low frontend UI and smoke-contract change. The strict-auth research-backtest browser scenario validates the real Backtest verdict-inputs path, but this slice does not change backend verdict-input generation or Research enforcement. The full default `validate:premerge` gate was not rerun after this focused Backtest slice; the static frontend, browser-script syntax, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-26 - SignalOps Research evidence SIM boundary visibility

Type: SignalOps Research-evidence bridge UI boundary / static frontend smoke / strict-auth browser smoke

Scope: expose the `SIM_*` marker in the visible SignalOps Research evidence boundary after selected SignalOps evidence is attached to Research verdict inputs. This is a frontend UI and smoke-contract slice only; it does not change SignalOps evidence creation, Research verdict input generation, API schemas, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `SIM_*` beside `evidence_usage`, `supporting_only`, `simulation_only`, `is_real_trade`, and `strong_conclusion_allowed=false` in `signalops-research-evidence-boundary`.
- Tightened `smoke:frontend` so SignalOps fails if the Research evidence boundary drops the `SIM_*` marker.
- Tightened the SignalOps strict-auth browser assertion so the real selected-signal Research evidence DOM must include `SIM_*`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `SignalOps is missing the Research evidence bridge from selected tick/signal context` after the static guard required `SIM_*` in the Research evidence boundary.
- Green: `npm.cmd run smoke:frontend` passed after the SignalOps UI rendered the new marker.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:signalops` passed, including `ok strict-auth browser SignalOps visible Research evidence boundary`.

Risk:
- Low frontend UI and smoke-contract change. The strict-auth SignalOps browser scenario validates the real selected-signal Research evidence bridge, but this slice does not change backend evidence creation or verdict-input enforcement. The full default `validate:premerge` gate was not rerun after this focused SignalOps slice; the static frontend, browser-script syntax, frontend type/lint/build, and SignalOps strict-auth browser gates passed.

## 2026-06-26 - Research verdict override review-gate boundary visibility

Type: Research Lab verdict override weak-evidence UI boundary / static frontend smoke / strict-auth browser smoke

Scope: expose the existing verdict override `evidence_usage=review_gate_only` marker in the visible Research Loops override simulation boundary. This is a frontend UI and smoke-contract slice only; it does not change feedback submission, Research workflow state, API schemas, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `evidence_usage=review_gate_only` inside the `research-verdict-override-simulation-boundary-*` row beside `simulation_only`, `is_real_trade`, `strong_conclusion_allowed=false`, and `SIM_*`.
- Tightened `smoke:frontend` so ResearchLoopsPage fails if the override simulation boundary drops `evidence_usage`.
- Tightened the research-backtest strict-auth browser assertion so the real override boundary DOM must include `evidence_usage=review_gate_only`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchLoopsPage one-click closed-loop sample entry is missing UI or browser-smoke coverage` after the static guard required `evidence_usage` in the override boundary.
- Green: `npm.cmd run smoke:frontend` passed after the Research Loops UI rendered the new field.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Research Lab visible verdict override boundary`.

Risk:
- Low frontend UI and smoke-contract change. The strict-auth browser scenario validates the real Research Backtest override boundary, but this slice does not change backend verdict override enforcement or add backend tests. The full default `validate:premerge` gate was not rerun after this focused Research slice; the static frontend, browser-script syntax, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-26 - SignalOps random-validation supporting-only boundary visibility

Type: Backtest SignalOps random-validation weak-evidence UI boundary / static frontend smoke / strict-auth browser smoke

Scope: expose the existing SignalOps random-validation governance fields in the visible Backtest random-validation panel. This is a frontend UI and smoke-contract slice only; it does not change backend random-validation execution, API schemas, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Rendered `evidence_usage=supporting_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*` in the SignalOps random-validation governance row.
- Tightened `smoke:frontend` so Backtest fails if the random-validation visible simulation boundary drops those supporting-only fields.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `BacktestPage is missing browser-visible sample-run hooks or strict-auth Backtest sample coverage` after the static guard required the new random-validation boundary fields.
- Green: `npm.cmd run smoke:frontend` passed after the Backtest UI rendered the new fields.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed.
- Green: `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including the strict-auth Backtest and Research Backtest scenario group.

Risk:
- Low frontend UI and smoke-contract change. The strict-auth browser scenario validates the real Backtest SPA path, but this slice does not add a dedicated runtime assertion for an active SignalOps random-validation job state. The full default `validate:premerge` gate was not rerun after this focused Backtest slice; the static frontend, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-21 - Shared atomic JSON writes for state stores

Type: backend storage reliability / Windows file-lock retry behavior / focused backend tests

Scope: consolidate JSON state-file writes behind a shared helper for analysis job state and Backtest parameter-scan/handoff state. This is a persistence-hardening slice only; it does not change API schemas, auth/session/cookie behavior, database migrations, Backtest calculation semantics, order routing, or the simulation-only trading boundary.

Changes:
- Added `write_json_atomic()` to the shared file-system utility module so JSON payloads are serialized with `ensure_ascii=false`, written through a uniquely named temp file, atomically swapped into place, and retried through the existing Windows `PermissionError` path.
- Reused the shared helper in `analysis_job_store` for analysis job JSON state persistence instead of keeping local temp-file and replace logic.
- Reused the shared helper in `backtest_store` for parameter-scan job snapshots and Backtest handoff JSON artifacts, removing duplicate ad hoc temp-file writes.
- Added focused file utility tests covering parent-directory creation, successful payload writes, transient lock retries, cleanup after permanent replace failure, and non-native JSON serialization.

Validation:
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_file_utils.py backend\tests\test_backtest_store.py backend\tests\test_analysis_job_sqlite.py`: passed, `61 passed, 42 warnings`.

Risk:
- Low backend storage refactor. The two touched stores still write the same JSON-shaped state, but now share cleanup and retry behavior. The focused tests cover the helper and the two main callers; the full default `validate:premerge` gate was not rerun after this documentation update.

## 2026-06-19 - Backtest run-level supporting-only boundary visibility

Type: Backtest selected-run weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Backtest selected-run governance boundary at the top of the Backtest page. This is a frontend UI and smoke-contract slice only; it does not change backend run creation, report calculation, experiment package generation, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended `BacktestGovernance` with `evidence_usage=supporting_only` and `strong_conclusion_allowed=false`.
- Rendered those fields beside `simulation_only`, `is_real_trade`, and `SIM_*` in the top-level Backtest run governance row.
- Added a strict-auth browser assertion to the existing Backtest sample-run scenario so the real selected-run DOM must show context ID, evidence strength, blocker, next action, and the supporting-only simulation boundary.
- Tightened `smoke:frontend` so Backtest fails if the run-level visible boundary fields or browser marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `BacktestPage is missing visible run ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new run-level boundary fields.
- Red/adjust: `npm.cmd run typecheck` failed until `buildBacktestRunGovernance` returned the new `evidenceUsage` and `strongConclusionAllowed` fields.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth browser preview.
- Green: `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Backtest sample visible run boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA selected-run row, but this slice does not add backend tests or change Backtest run/report enforcement. The full default `validate:premerge` gate was not rerun after this focused Backtest slice; the static frontend, syntax, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-19 - Backtest parameter-scan review-gate boundary visibility

Type: Backtest parameter-scan weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Backtest parameter-scan review-gated evidence boundary in the immediate scan notice, async scan job status, and parameter-scan history row. This is a frontend UI and smoke-contract slice only; it does not change backend scan execution, job persistence, artifact handoff custody, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended `BacktestParameterScanGovernance` with `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false`.
- Rendered those fields beside `simulation_only`, `is_real_trade`, and `SIM_*` for the parameter-scan completion notice, async job governance row, and scan history governance row.
- Tightened `smoke:frontend` so Backtest fails if those three parameter-scan visible boundary fields are removed.
- Tightened the research-backtest strict-auth browser scenario so the real DOM text for scan notice, history, and async job must expose the review-gate boundary.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `BacktestPage is missing parameter-scan ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new fields.
- Green: `npm.cmd run smoke:frontend` passed after the Backtest UI rendered the new boundary fields.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run lint` passed.
- Green: `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth browser preview.
- Green: `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including the Backtest parameter-scan validation protocol, async job, handoff, and handoff custody checks.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA parameter-scan path, but this slice does not add backend tests or change scan/job enforcement. The full default `validate:premerge` gate was not rerun after this focused Backtest slice; the static frontend, syntax, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-19 - SignalOps paper-order boundary visibility and strict-auth coverage

Type: SignalOps paper-order weak-evidence UI boundary / selected-signal artifact fallback / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing SignalOps paper-order simulation-only boundary on the selected signal detail. This is a frontend UI and smoke-contract slice only; it does not change backend paper-order routes, auto-paper command execution, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended paper-order governance with `evidence_usage=simulation_only` and `strong_conclusion_allowed=false`, and rendered those fields beside `simulation_only`, `is_real_trade`, and `SIM_*` in the selected signal order row.
- Changed the selected signal detail to display a de-duplicated selected-signal order set from detail orders plus already loaded pool orders, so pool-level artifacts do not disappear from the selected detail when a detail artifact refresh is skipped by request sequencing.
- Added a deterministic strict-auth browser paper-order fixture to the existing SignalOps Research evidence scenario and asserted that the selected detail renders context ID, LOW evidence, blocker, next action, and the full simulation-only boundary.
- Tightened `smoke:frontend` so SignalOps fails if the paper-order boundary fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `SignalOps page is missing browser-visible core operation hooks or strict-auth high-risk write coverage` after the static guard required the new paper-order visible boundary and browser marker.
- Red/adjust: early `npm.cmd run smoke:strict-auth-browser:signalops` attempts timed out on the new paper-order DOM assertion until the scenario used a controlled paper-order fixture and the selected-detail UI consumed already loaded pool orders for the same signal.
- Green: `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- Green: `npm.cmd run smoke:frontend` passed.
- Green: `npm.cmd run typecheck` passed.
- Green: `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth browser preview.
- Green: `npm.cmd run smoke:strict-auth-browser:signalops` passed, including `ok strict-auth browser SignalOps paper order visible boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA detail row and Authorization-bearing paper-order read, but it does not add backend tests or change paper-order persistence/enforcement. The full default `validate:premerge` gate was not rerun after this focused SignalOps slice; the static frontend, syntax, frontend type/build, and SignalOps strict-auth browser gates passed.

## 2026-06-19 - SignalOps review-card boundary visibility and strict-auth coverage

Type: SignalOps weak-evidence review-card UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing SignalOps review-card simulation-only boundary before a candidate review decision is applied. This is a frontend UI and smoke-contract slice only; it does not change auto-paper config/status loading, review decision payloads, backend routes, auth/session/cookie behavior, database migrations, paper order routing, or the simulation-only trading boundary.

Changes:
- Extended the visible SignalOps review-card boundary row to show `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser assertion to the existing SignalOps review-decision scenario so the `rq-approve` review card must render context ID, evidence, blocker, next action, and the simulation-only review boundary before approval/rejection actions run.
- Tightened `smoke:frontend` so SignalOps fails if the review-card boundary fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `SignalOps page is missing browser-visible core operation hooks or strict-auth high-risk write coverage` after the static guard required the new visible review-card boundary and browser coverage.
- Green: `npm.cmd run smoke:frontend` passed after the SignalOps UI and strict-auth scenario markers were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- Red/adjust: `npm.cmd run smoke:strict-auth-browser:signalops` reached the new browser assertion and failed because the UI displays `MEDIUM` as localized text `中等证据`; the assertion was tightened to reject empty/high/strong evidence while allowing localized low/medium labels.
- Green: `npm.cmd run smoke:strict-auth-browser:signalops` passed, including `ok strict-auth browser SignalOps review decision visible boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA review window and DOM boundary, but it does not add backend tests or change SignalOps review-decision persistence/enforcement. The full default `validate:premerge` gate was not rerun after this focused SignalOps slice; the static frontend, syntax, frontend type/lint/build, and SignalOps strict-auth browser gates passed.

## 2026-06-19 - Guardrail Hub review boundary visibility and strict-auth coverage

Type: Guardrail Hub weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Guardrail Hub simulation-only review boundary. This is a frontend UI and smoke-contract slice only; it does not change canonical/legacy guardrail synthesis, DVG/risk/trade-micro calculations, quant-core handoff, backend routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Guardrail Hub governance to carry `evidence_usage=simulation_only` and `strong_conclusion_allowed=false`.
- Extended the visible Guardrail Hub boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser assertion to the existing platform route flow so `/guardrail-hub` must render context ID, evidence, blocker, next action, and the simulation-only review boundary before the scenario continues to Permission Matrix and Backend Status.
- Tightened `smoke:frontend` so Guardrail Hub fails if the UI fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `GuardrailHubPage is missing visible canonical/legacy ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new visible boundary fields and before the UI rendered them.
- Red: `npm.cmd run smoke:frontend` failed with `strict-auth browser smoke is missing Guardrail Hub visible review boundary coverage` after the static guard required browser coverage and before the browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Guardrail Hub UI and strict-auth scenario markers were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Guardrail Hub visible review boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA route and DOM boundary, but it does not add backend tests or change guardrail synthesis/enforcement. The full default `validate:premerge` gate was not rerun after this focused Guardrail Hub slice; the static frontend, syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-19 - Execution review boundary visibility and strict-auth coverage

Type: Execution weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Execution simulation-only review boundary. This is a frontend UI and smoke-contract slice only; it does not change execution reachability, allowed/prohibited action calculation, manual-confirmation logic, backend routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Execution governance to carry `evidence_usage=simulation_only` and `strong_conclusion_allowed=false`.
- Extended the visible Execution boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser assertion to the existing platform route flow so `/execution` must render context ID, evidence, blocker, next action, and the simulation-only review boundary before the scenario continues to Permission Matrix and Backend Status.
- Tightened `smoke:frontend` so Execution fails if the UI fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ExecutionPage is missing visible execution ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new visible boundary fields and before the UI rendered them.
- Red: `npm.cmd run smoke:frontend` failed with `strict-auth browser smoke is missing Execution visible review boundary coverage` after the static guard required browser coverage and before the browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Execution UI and strict-auth scenario markers were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Execution visible review boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA route and DOM boundary, but it does not add backend tests or change execution enforcement. The full default `validate:premerge` gate was not rerun after this focused Execution slice; the static frontend, syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-19 - Permission Matrix review boundary visibility and strict-auth coverage

Type: Permission Matrix weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Permission Matrix simulation-only review boundary. This is a frontend UI and smoke-contract slice only; it does not change permission calculation, DVG/QIAM/Execution/kill-switch logic, backend routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Permission Matrix governance to carry `evidence_usage=simulation_only` and `strong_conclusion_allowed=false`.
- Extended the visible Permission Matrix boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser assertion to the existing platform route flow so `/permission` must render context ID, evidence, blocker, next action, and the simulation-only review boundary before the scenario continues to Backend Status.
- Tightened `smoke:frontend` so Permission Matrix fails if the UI fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `PermissionMatrixPage is missing visible permission ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new visible boundary fields and before the UI rendered them.
- Red: `npm.cmd run smoke:frontend` failed with `strict-auth browser smoke is missing Permission Matrix visible review boundary coverage` after the static guard required browser coverage and before the browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Permission Matrix UI and strict-auth scenario markers were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Permission Matrix visible review boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA route and DOM boundary, but it does not add backend tests or change permission enforcement. The full default `validate:premerge` gate was not rerun after this focused Permission Matrix slice; the static frontend, syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-19 - New Task analysis-run review boundary visibility and strict-auth coverage

Type: New Task weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing New Task analysis-run preflight simulation boundary. This is a frontend UI and smoke-contract slice only; it does not change analysis-run creation/start semantics, portfolio snapshot loading, backend routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended New Task analysis-run preflight governance to carry `evidence_usage=simulation_only` and `strong_conclusion_allowed=false`.
- Extended the visible New Task run boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser assertion on the existing Portfolio -> New Task route flow so the real SPA must render context ID, evidence, blocker, next action, and the simulation-only review boundary before run creation continues.
- Tightened `smoke:frontend` so New Task fails if the UI fields, browser assertion, call site, or success marker are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `NewTaskPage is missing visible analysis-run ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required the new visible boundary fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the New Task UI and strict-auth scenario markers were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser New Task visible review boundary`.

Risk:
- Low frontend UI and smoke-contract change. The browser scenario validates the real strict-auth SPA path through Portfolio -> New Task -> Live Run -> Final Writer, but it does not add a backend unit test or change persisted analysis-run schema. The full default `validate:premerge` gate was not rerun after this focused New Task slice; the static frontend, syntax, frontend type/lint/build, and portfolio-live-plugin strict-auth browser gates passed.

## 2026-06-19 - Data Compression review boundary visibility and strict-auth coverage

Type: Data Compression weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose and browser-cover the existing Data Compression preview-only simulation evidence boundary. This is a frontend UI and smoke-contract slice only; it does not change compression summary generation, backend data-pipeline routes, analysis-run persistence, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Data Compression run governance to derive `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` from the existing LOW/MEDIUM preview-only review boundary.
- Extended the visible Data Compression run boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Added a strict-auth browser fixture scenario for `/data-compression` that serves deterministic run-list, overview, run-summary, and distillation-group responses while requiring the existing Bearer token on `/api/analysis/runs` and `/api/data-pipeline/*`.
- Connected the scenario to the `platform` strict-auth group and tightened `smoke:frontend` so the Data Compression static guard fails if the visible boundary fields or browser scenario markers are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `DataCompressionPage is missing visible run ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage`, `strong_conclusion_allowed`, and strict-auth browser scenario markers and before the UI/scenario existed.
- Green: `npm.cmd run smoke:frontend` passed after the Data Compression UI exposed the simulation-only review boundary fields and the strict-auth browser scenario/call site were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- First `npm.cmd run smoke:strict-auth-browser:platform` attempt failed because the scenario depended on a non-visible app link/URL wait; it was updated to use SPA `pushState` plus the governance row as the render gate.
- Second attempt failed because the fixture incorrectly expected `MEDIUM` evidence for a preview-only summary; the assertion was corrected to require the existing `LOW` preview-only boundary.
- Final `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Data Compression visible review boundary`.

Risk:
- Low frontend and smoke-script change. The scenario uses a browser route fixture and validates the real SPA route plus Authorization header propagation, but it does not exercise the backend compression implementation or persisted run store. The full default `validate:premerge` gate was not rerun after this focused Data Compression slice; the static frontend, syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-19 - Run Compare strict-auth review boundary coverage

Type: Run Compare weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: add strict-auth browser coverage for the visible Run Compare simulation-only review boundary. This is a smoke-contract slice only; it does not change Run Compare UI rendering, analysis-run comparison semantics, backend compare routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Added a strict-auth browser fixture scenario for `/run-compare` that serves deterministic run-list and compare responses while requiring the existing Bearer token on both `/api/analysis/runs` and `/api/analysis/runs/compare`.
- Added a browser assertion that the visible Run Compare governance row shows `LOW`, the expected compare context id, `simulation_only=true`, `is_real_trade=false`, `evidence_usage=simulation_only`, `strong_conclusion_allowed=false`, and `SIM_*`.
- Connected the scenario to the `platform` strict-auth group and tightened `smoke:frontend` so the Run Compare static guard fails if the browser scenario, call site, Bearer check, compare endpoint marker, or success marker is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `RunComparePage is not wired to render guarded compare summaries/diffs, governance boundaries, and API errors` after the static guard required the strict-auth browser scenario markers and before the scenario existed.
- Green: `npm.cmd run smoke:frontend` passed after the strict-auth browser scenario and call site were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Run Compare visible review boundary`.

Risk:
- Low smoke-only change. The scenario uses a browser route fixture and validates the real SPA route plus Authorization header propagation, but it does not exercise the backend compare implementation or persisted analysis-run store. The full default `validate:premerge` gate was not rerun after this focused Run Compare strict-auth slice; the static frontend, syntax, frontend type/lint/build, and platform strict-auth browser gates passed.

## 2026-06-19 - Run Compare review boundary visibility

Type: Run Compare weak-evidence UI boundary / static frontend smoke

Scope: expose the existing run-compare simulation-only evidence boundary in the visible compare governance row. This is a frontend UI and smoke-contract slice only; it does not change analysis-run comparison semantics, backend compare routes, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Run Compare governance to derive `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` from the existing LOW comparison-review boundary.
- Extended the visible Run Compare boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Tightened `smoke:frontend` so Run Compare fails if the visible compare governance row stops exposing the simulation-only/no-strong-conclusion boundary.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `RunComparePage is not wired to render guarded compare summaries/diffs, governance boundaries, and API errors` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Run Compare UI exposed the simulation-only review boundary fields.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run build` passed.

Risk:
- Low frontend-only visibility and smoke-script change. Run Compare still uses the existing `compareAnalysisRuns` response guard, LOW evidence strength, and audit-log review prompt; the added fields make the comparison result visibly review-only without changing compare results or trading semantics. A strict-auth browser route scenario and the full default `validate:premerge` gate were not rerun for this small Run Compare slice; the focused static frontend, syntax, typecheck, lint, and production build gates passed.

## 2026-06-19 - Research trace strict-auth review boundary coverage

Type: Research trace weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: add strict-auth browser coverage for the visible Research Traces supporting-only review boundary. This is a smoke-contract slice only; it does not change Research Traces UI rendering, trace import parsing, Research Loop persistence, backend trace adapter behavior, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Added a strict-auth browser fixture scenario for `/research-lab/traces` that serves a Research Loop as a trace list/detail response while requiring the existing Bearer token on both `/api/research/traces` requests.
- Added a browser assertion that the visible Research Trace governance row shows `simulation_only=true`, `is_real_trade=false`, `evidence_usage=supporting_only`, `strong_conclusion_allowed=false`, and `SIM_*`.
- Connected the scenario to the `research-backtest` strict-auth group and tightened `smoke:frontend` so the Research Traces static guard fails if the browser scenario, call site, Bearer check, or success marker is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchTracesPage must validate imported trace JSON, gate imports, and render LOW trace governance` after the static guard required the strict-auth browser scenario markers and before the scenario existed.
- Green: `npm.cmd run smoke:frontend` passed after the strict-auth browser scenario and call site were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Research Traces visible review boundary`.

Risk:
- Low smoke-only change. The scenario uses a browser route fixture and validates the real SPA route plus Authorization header propagation, but it does not exercise the backend trace adapter or persisted trace import path. The full default `validate:premerge` gate was not rerun after this focused Research Traces strict-auth slice; the static frontend, syntax, frontend type/lint/build, and research-backtest strict-auth browser gates passed.

## 2026-06-19 - Research trace review boundary visibility

Type: Research trace weak-evidence UI boundary / static frontend smoke

Scope: expose the existing external-trace research evidence boundary in the visible Research Traces detail governance row. This is a frontend UI and smoke-contract slice only; it does not change trace import parsing, Research Loop persistence, backend trace adapter behavior, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Research Trace governance to derive `evidence_usage=supporting_only` and `strong_conclusion_allowed=false` from the existing LOW external-trace boundary.
- Extended the visible Research Trace simulation boundary row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Tightened `smoke:frontend` so Research Traces fails if the visible trace governance row stops exposing the supporting-only/no-strong-conclusion boundary.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchTracesPage must validate imported trace JSON, gate imports, and render LOW trace governance` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Research Traces UI exposed the supporting-only review boundary fields.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.

Risk:
- Low frontend-only visibility and smoke-script change. Research Traces still maps external trace imports through the existing Research Loop API and keeps evidence strength LOW; the added fields make the supporting-only evidence boundary visible without changing backend schema or import behavior. A strict-auth browser route scenario and the full default `validate:premerge` gate were not rerun for this small Research Traces slice; the focused static frontend, typecheck, lint, and production build gates passed.

## 2026-06-19 - Dashboard run review boundary visibility

Type: Dashboard weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Dashboard run simulation-only evidence boundary in the visible default-entry governance row. This is a frontend UI and smoke-contract slice only; it does not change backend metrics, dashboard summary generation, current-run hydration, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Dashboard run governance to derive `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` from explicit trade-boundary/paper-trading fields when present, otherwise from the existing simulation-only run boundary.
- Extended the visible Dashboard run governance row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended Dashboard boundary classification so unexpected evidence usage or strong-conclusion allowance becomes a visible boundary violation and forces LOW evidence strength.
- Extended `smoke:frontend` and the strict-auth `platform` browser scenario so the default Dashboard entry fails if the visible run review boundary is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed in the Dashboard static guard block with `DashboardPage is not wired to the local mock fallback path` after the guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Dashboard UI exposed the simulation-only review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Dashboard visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. Dashboard still uses the existing run trade boundary, metrics fixture, current-run hydration, and research closed-loop entry behavior; the added fields make the default entry evidence boundary visible and block suspicious evidence flags without changing backend metrics or trading semantics. The full default `validate:premerge` gate was not rerun after this small Dashboard slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Final Writer review boundary visibility

Type: Final Writer weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Final Writer paper-trading simulation-only evidence boundary in the visible final-report governance row. This is a frontend UI and smoke-contract slice only; it does not change backend report generation, analysis-run persistence, LLM routing, report asset storage, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Final Writer governance to derive `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` from explicit final-writer/paper-trading fields when present, otherwise from the existing simulation-only paper-trading boundary.
- Extended the visible Final Writer governance row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended Final Writer boundary classification so unexpected evidence usage or strong-conclusion allowance becomes a visible `SIMULATION_BOUNDARY_VIOLATED` blocker.
- Extended `smoke:frontend` and the strict-auth `portfolio-live-plugin` browser scenario so the final-report chain fails if the visible Final Writer review boundary is removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `FinalWriterPage is missing visible report ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Final Writer UI exposed the simulation-only review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- First `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` attempt was started in parallel with `build` and failed because the preview served the previous Final Writer bundle without the new boundary text.
- Rerun after `build` completed passed, including `ok strict-auth browser Final Writer visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. Final Writer still uses the existing `paperTrading.simulation_only`, `paperTrading.is_real_trade`, `SIM_*` namespace, `SIM_` action checks, and human-confirmation gate; the added fields make the final-report evidence boundary visible and block suspicious evidence flags without changing report generation or trading semantics. The full default `validate:premerge` gate was not rerun after this small Final Writer slice; the focused frontend, build, static smoke, and portfolio-live-plugin strict-auth gates passed.

## 2026-06-19 - Agent Debate review boundary visibility

Type: Agent Debate weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Agent Debate paper-trading simulation-only evidence boundary in the visible debate governance row. This is a frontend UI and smoke-contract slice only; it does not change backend analysis-run persistence, debate generation, LLM routing, token metering semantics, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Agent Debate governance to derive `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` from the paper-trading boundary fallback when the backend does not return explicit evidence fields.
- Extended the visible Agent Debate governance row to show `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended Agent Debate boundary classification so unexpected evidence usage or strong-conclusion allowance becomes a visible `SIMULATION_BOUNDARY_VIOLATED` blocker.
- Extended `smoke:frontend` and the strict-auth `research-backtest` browser scenario so the Debate boundary assertion fails if those visible fields are removed.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `AgentDebatePage is missing visible debate ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Agent Debate UI exposed the simulation-only review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Agent Debate visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. Agent Debate still uses the existing `paperTrading.simulation_only`, `paperTrading.is_real_trade`, `SIM_*` namespace, and `SIM_` action checks; the added fields make the weak-evidence boundary visible and block suspicious evidence flags without changing debate generation or trading semantics. The full default `validate:premerge` gate was not rerun after this small Agent Debate slice; the focused frontend, build, static smoke, and research-backtest strict-auth gates passed.

## 2026-06-19 - Agent DAG node review boundary visibility

Type: Agent DAG weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Agent node simulation-only evidence boundary in the visible Agent DAG run and selected-node governance rows. This is a frontend UI and smoke-contract slice only; it does not change backend analysis-run persistence, Agent execution, LLM routing, DAG topology, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended Agent DAG run and selected-node governance rows to show `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended Agent DAG governance derivation to treat unexpected node evidence usage or strong-conclusion allowance as a visible blocker.
- Extended `smoke:frontend` so Agent DAG static guards fail if those visible boundary fields or the strict-auth browser assertion are removed.
- Extended the strict-auth `research-backtest` browser scenario to assert the visible Agent DAG run and selected-node boundaries after linked-run hydration.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `AgentDagPage is missing LLM output source and live-call evidence linkage` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Agent DAG UI exposed the run and selected-node review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Agent DAG visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by `analysisClient.assertAgentNodeBoundary`, so linked-run response validation, Agent execution, LLM call behavior, DAG interaction, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Agent DAG slice; the focused frontend, build, static smoke, and research-backtest strict-auth gates passed.

## 2026-06-19 - QuantCore read-only review boundary visibility

Type: QuantCore weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing QuantCore read-only simulation evidence boundary in the visible Quant Core governance row. This is a frontend UI and smoke-contract slice only; it does not change backend analysis-run persistence, QuantCore calculation semantics, Technical Kline case sedimentation, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Quant Core governance row to show `evidence_usage=simulation_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended the governance model to treat an unexpected QuantCore evidence usage or strong-conclusion allowance as a visible blocker.
- Extended `smoke:frontend` so the QuantCore static guard fails if those visible boundary fields or the strict-auth browser assertion are removed.
- Extended the strict-auth `platform` browser scenario to assert the visible QuantCore read-only boundary on `/quant-core?run_id=...` before the existing Technical Kline case-sedimentation check.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `QuantCorePage is missing visible ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the QuantCore UI exposed the read-only review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser QuantCore visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by `analysisClient.assertQuantCoreBoundary`, so analysis-run response validation, QuantCore calculations, Technical Kline case recording, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small QuantCore slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Portfolio snapshot review boundary visibility

Type: Portfolio weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Portfolio snapshot supporting-only evidence boundary in the visible snapshot governance row. This is a frontend UI and smoke-contract slice only; it does not change backend Portfolio persistence, import parsing, New Task binding, auth/session/cookie behavior, database migrations, order routing, broker connectivity, or the simulation-only trading boundary.

Changes:
- Extended the Portfolio snapshot governance row to show `evidence_usage=supporting_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended `smoke:frontend` so the Portfolio static guard fails if those visible boundary fields or the strict-auth browser assertion are removed.
- Extended the strict-auth `portfolio-live-plugin` browser scenario to assert the visible supporting-only Portfolio boundary immediately after creating a manual sample snapshot.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Portfolio snapshots are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Portfolio UI exposed the snapshot review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin` passed, including `ok strict-auth browser Portfolio visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by `portfolioClient` response guards, so snapshot creation, file import, malformed-file diagnostics, New Task context binding, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Portfolio slice; the focused frontend, build, static smoke, and portfolio-live-plugin strict-auth gates passed.

## 2026-06-19 - Knowledge item review boundary visibility

Type: Knowledge weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Knowledge item supporting-only evidence boundary in the visible Knowledge governance row. This is a frontend UI and smoke-contract slice only; it does not change backend Knowledge persistence, review actions, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Knowledge item governance row to show `evidence_usage=supporting_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, `SIM_*`, and `source_run_verified`.
- Extended `smoke:frontend` so the Knowledge item static guard fails if those visible boundary fields or the strict-auth browser assertion are removed.
- Added a strict-auth `platform` browser scenario that loads `/knowledge` through the existing SPA session, verifies Knowledge list requests keep the Bearer token, and asserts the visible supporting-only review boundary text.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `KnowledgeIterationPage is missing visible item ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Knowledge UI exposed the item review boundary fields and the strict-auth browser source contained the new assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:platform` passed sequentially, including `ok strict-auth browser Knowledge visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by `knowledgeClient` response guards, so Knowledge creation, review, archive, active-context reuse, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Knowledge item slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Case Library simulation-case review boundary visibility

Type: Case Library Agent simulation-case weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Agent simulation-case review-gate-only boundary in the visible Case Library simulation-case governance row. This is a frontend UI and smoke-contract slice only; it does not change SignalOps case schemas, backend simulation-case persistence, paper-order behavior, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Case Library Agent simulation-case governance model to derive `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` from the existing simulation-only review boundary.
- Extended the visible Agent simulation-case governance row to show those fields beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended `smoke:frontend` so the simulation-case static guard fails if those visible boundary fields or the strict-auth browser simulation-case assertion are removed.
- Extended the strict-auth `platform` browser scenario fixture to load a persisted Agent simulation case, open the `Agent 模拟操作案例` tab, and assert the visible review-gate boundary text under the existing strict Bearer-token session.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Case Library Agent simulation cases are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Case Library UI exposed the derived simulation-case review boundary fields and the strict-auth browser source contained the simulation-case assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:platform` passed sequentially, including `ok strict-auth browser Case Library visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. Agent simulation-case API responses still expose only the existing required `simulation_only=true` and `is_real_trade=false` record boundary; the displayed `review_gate_only` and `strong_conclusion_allowed=false` fields are UI governance derivations, not a backend schema change. The full default `validate:premerge` gate was not rerun after this small Case Library simulation-case slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Case Library error-ledger review boundary visibility

Type: Case Library error-ledger weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing error-ledger review-gate-only evidence boundary in the visible Case Library error governance row. This is a frontend UI and smoke-contract slice only; it does not change backend error-ledger persistence, case or patch review policy, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Case Library error-ledger governance row to show `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended `smoke:frontend` so the Case Library error-ledger static guard fails if those visible boundary fields or the strict-auth browser error-ledger assertion are removed.
- Extended the strict-auth `platform` browser scenario fixture to load an error-ledger row, open the `错误账本` tab, and assert the visible review-gate boundary text under the existing strict Bearer-token session.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Case Library error ledger is missing visible ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Case Library UI exposed the error-ledger review boundary fields and the strict-auth browser source contained the error-ledger assertion.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- Iteration: one concurrent `npm.cmd run smoke:strict-auth-browser:platform` attempt failed in the Dashboard scenario while `npm.cmd run build` was also rewriting `frontend/dist`; the failure happened before the Case Library scenario and was treated as invalid validation evidence.
- Green: a sequential `npm.cmd run smoke:strict-auth-browser:platform` rerun passed, including `ok strict-auth browser Case Library visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by the API client boundary guards, so error-ledger persistence, case review, patch approval, evaluation, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Case Library error-ledger slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Case Library review boundary visibility

Type: Case Library weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Case Library supporting-only and review-gate-only evidence boundaries in the visible case and knowledge-patch governance rows. This is a frontend UI and smoke-contract slice only; it does not change backend case persistence, patch approval policy, evaluation generation, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Case Library case governance row to show `evidence_usage=supporting_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended the Case Library knowledge-patch governance row to show `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` beside the same simulation boundary fields.
- Extended `smoke:frontend` so the Case Library static guard fails if those visible boundary fields or strict-auth browser assertions are removed.
- Added a strict-auth `platform` browser scenario that loads `/case-library` through the existing SPA session, verifies the Case Library list requests keep the Bearer token, and asserts the visible case and patch review boundary text.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Case Library cases are missing visible ID/evidence/blocker/next-action simulation-boundary guardrails` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Case Library UI exposed the review boundary fields and the strict-auth browser source contained the new assertions.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- Iteration: `npm.cmd run smoke:strict-auth-browser:platform` first failed because the new Case Library scenario used a full page reload and lost the tab-scoped strict-auth token, then failed on URL-waiting around History API navigation. The smoke was corrected to keep the existing SPA session and use the target DOM boundary as the completion proof.
- Green: `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Case Library visible review boundary`.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays fields already required by the API client boundary guards, so case review, patch approval, evaluation, and trading semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Case Library slice; the focused frontend, build, static smoke, and platform strict-auth gates passed.

## 2026-06-19 - Knowledge Versions review-gate boundary visibility

Type: Knowledge Versions weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Knowledge Versions review-gate-only evidence boundary in the visible published-version and post-publish regression governance rows. This is a frontend UI and smoke-contract slice only; it does not change backend knowledge-version persistence, regression generation, waiver policy, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Knowledge Versions published-version governance row to show `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended the post-publish regression governance row to show the same visible review-gate boundary fields from the regression report.
- Extended `smoke:frontend` so the Knowledge Versions static guard fails if those visible review-gate boundary fields or strict-auth browser assertions are removed.
- Extended the strict-auth `platform` browser scenario to assert the visible published-version and post-publish regression review-gate boundary text.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Knowledge Versions post-publish regression is missing active page/client/strict-auth browser linkage` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Knowledge Versions UI exposed the review-gate boundary fields.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run test:frontend` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Knowledge Versions visible review-gate boundary` and `ok strict-auth browser Knowledge Versions post-publish regression`.

Risk:
- Low frontend-only visibility change. The UI now displays fields already required by the API client and regression blocker logic, so runtime promotion, rollback, waiver, and regression semantics remain unchanged. The full default `validate:premerge` gate was not rerun after this small Knowledge Versions slice; the focused frontend, build, and platform strict-auth gates passed.

## 2026-06-19 - Evaluation Sandbox review-gate boundary visibility

Type: Evaluation Sandbox weak-evidence UI boundary / strict-auth browser smoke / static frontend smoke

Scope: expose the existing Evaluation Sandbox review-gate-only evidence boundary in the visible patch, evaluation-run, and strategy-experiment governance rows. This is a frontend UI and smoke-contract slice only; it does not change backend evaluation generation, Case/Knowledge persistence, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Evaluation Sandbox patch governance row to show `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended evaluation-run and strategy-experiment governance rows to carry and render their existing `evidence_usage` and `strong_conclusion_allowed` audit fields.
- Extended `smoke:frontend` so the Evaluation Sandbox static guard fails if those visible review-gate boundary fields are removed.
- Extended the strict-auth `platform` browser scenario to assert the visible patch, evaluation-run, and strategy-experiment review-gate boundary text.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `Evaluation Sandbox is missing active page/client/strict-auth browser evaluation linkage` after the static guard required visible `evidence_usage` and `strong_conclusion_allowed` fields and before the UI rendered them.
- Green: `npm.cmd run smoke:frontend` passed after the Evaluation Sandbox UI exposed the review-gate boundary fields.
- Red: `npm.cmd run smoke:frontend` failed with the same Evaluation Sandbox linkage error after the static guard required strict-auth browser visible-boundary assertions and before `scripts\smoke-strict-auth-browser.mjs` contained them.
- Green: `npm.cmd run smoke:frontend` passed after the strict-auth browser scenario asserted the visible review-gate boundary rows.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:platform` passed, including `ok strict-auth browser Evaluation Sandbox visible review-gate boundary` and `ok strict-auth browser Evaluation Sandbox patch evaluation and strategy experiment`.
- Full `npm.cmd run validate:premerge` passed: 9 steps in 693.2s.
- The full gate included backend regression: 599 passed, with existing FastAPI/Starlette deprecation warnings.
- Closed-loop participation smoke passed: 1 passed.
- Analysis worker smoke passed: 15 passed.
- Frontend typecheck, lint, build, and static smoke passed.
- Frontend responsive smoke passed: 47 routes / 188 checks across `1440x1000`, `1280x900`, `768x1024`, and `390x844`.
- Strict-auth browser matrix passed across platform, signalops, research-backtest, and portfolio-live-plugin.
- The platform strict-auth group included `ok strict-auth browser Evaluation Sandbox visible review-gate boundary` and `ok strict-auth browser Evaluation Sandbox patch evaluation and strategy experiment`.

Risk:
- Low frontend-only visibility change. The UI now displays fields already required by the API client and backend models, so runtime evaluation semantics remain unchanged. The full default premerge gate passed for this state, including the strict-auth browser matrix; the remaining long-term exit condition still requires continued consecutive full premerge passes without new high-risk regressions.

## 2026-06-19 - Research boundary full premerge validation

Type: validation trace / Research weak-evidence UI boundary / premerge gate audit

Scope: record the full current-state premerge validation after the Research workflow, artifact chain, verdict override, Backtest notice, and SignalOps notice boundary visibility slices. This is a validation-log-only update; it does not change runtime behavior, API schema, auth/session/cookie handling, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Recorded the full default `validate:premerge` evidence for the current Research weak-evidence visibility state.
- Confirmed the default gate still covers backend regression, closed-loop participation, analysis worker, frontend typecheck/lint/build/static smoke, frontend responsive smoke, and the strict-auth browser matrix.
- Captured the strict-auth matrix evidence for the newly visible Research Lab workflow, artifact chain, Backtest verdict-inputs, SignalOps Research evidence, and verdict override boundaries.

Validation:
- `npm.cmd run validate:premerge` passed: 9 steps in 718.5s.
- Backend regression passed: 599 passed, with existing FastAPI/Starlette deprecation warnings.
- Closed-loop participation smoke passed: 1 passed.
- Analysis worker smoke passed: 15 passed.
- Frontend typecheck, lint, build, and static smoke passed.
- Frontend responsive smoke passed: 47 routes / 188 checks across `1440x1000`, `1280x900`, `768x1024`, and `390x844`.
- Strict-auth browser matrix passed across platform, signalops, research-backtest, and portfolio-live-plugin.
- The research-backtest strict-auth group included `ok strict-auth browser Research Lab visible workflow boundary`, `ok strict-auth browser Research Lab visible artifact chain boundary`, `ok strict-auth browser Research Backtest visible verdict-inputs boundary`, `ok strict-auth browser Research Lab visible verdict override boundary`, and `ok strict-auth browser Research SignalOps selected deep link`.
- The signalops strict-auth group included `ok strict-auth browser SignalOps visible Research evidence boundary`.

Risk:
- Low validation-only documentation update. The remaining known risk is existing dependency deprecation warnings in backend tests; this validation did not attempt dependency cleanup. The gate proves the current default strict-auth and responsive contracts, but it is one current-state run rather than the consecutive multi-run exit condition for the long-term goal.

## 2026-06-19 - Research artifact chain boundary visibility

Type: Research artifact chain UI boundary / strict-auth browser smoke / weak-evidence visibility

Scope: expose the Research artifact materialization chain as review-gate-only in the visible Research loop governance row. This is a frontend UI and strict-auth browser coverage slice only; it does not change backend artifact generation, persistence, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended `buildArtifactChainGovernance` with local `evidenceUsage=review_gate_only` and `strongConclusionAllowed=false` boundary fields, and treated either field drifting from that boundary as a broken artifact-chain governance state.
- Extended the artifact chain simulation boundary row to show `evidence_usage=review_gate_only` and `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended `smoke:frontend` so the Research loop static guard fails if the artifact chain boundary text or strict-auth browser assertion is removed.
- Extended the strict-auth `research-backtest` browser scenario to assert the visible materialized artifact chain boundary after closed-loop artifact materialization.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchLoopsPage one-click closed-loop sample entry is missing UI or browser-smoke coverage` after adding the static guard and before the UI/browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Research artifact chain UI and strict-auth browser assertion were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Research Lab visible artifact chain boundary`.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-research-artifact-boundary` passed: 26 passed.
- `git diff --check` passed with LF/CRLF working-copy warnings only.
- Full `npm.cmd run validate:premerge` was not rerun for this small UI/smoke slice; the previous 2026-06-19 full premerge evidence remains recorded in the Research bridge docs strong-conclusion guard section.

Risk:
- Low frontend-only visibility and smoke-script change. The UI displays a conservative local artifact-chain governance boundary and the strict-auth browser scenario verifies it after real materialization. Remaining risk is limited to future artifact-chain semantics adding a backend-owned boundary field that should replace the local default.

## 2026-06-19 - Research verdict override boundary visibility

Type: Research verdict override UI boundary / strict-auth browser smoke / weak-evidence visibility

Scope: expose the existing verdict override strong-conclusion boundary in the Research loop verdict-inputs governance panel. This is a frontend UI and strict-auth browser coverage slice only; it does not change backend verdict-gate generation, feedback persistence semantics, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Returned `strongConclusionAllowed` from the existing `buildVerdictOverrideAudit` helper so the UI can display the same value it already uses to detect a broken override boundary.
- Extended the verdict override simulation boundary row to show `strong_conclusion_allowed=false` beside `simulation_only`, `is_real_trade`, `SIM_*`, and `generated_at`.
- Extended `smoke:frontend` so the Research loop static guard fails if the verdict override boundary text or strict-auth browser assertion is removed.
- Extended the strict-auth `research-backtest` browser scenario to seed a verdict override feedback record, refresh the current Research loop through the existing SPA session, and assert the visible override governance markers: `can_accept_feedback=false`, `evidence_usage=review_gate_only`, `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchLoopsPage one-click closed-loop sample entry is missing UI or browser-smoke coverage` after adding the static guard and before the UI/browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Research loop UI and strict-auth browser assertion were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- First `npm.cmd run smoke:strict-auth-browser:research-backtest` failed after the UI change because the new browser helper used `page.goto('/research-lab/research')`, which reloaded the tab and caused strict-auth Research loop requests to return 401. The failure happened before the override boundary assertion and confirmed the smoke had to preserve the SPA auth session.
- Final `npm.cmd run smoke:strict-auth-browser:research-backtest` passed after switching the helper to the existing in-app `刷新循环` path, including `ok strict-auth browser Research Lab visible verdict override boundary`.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-research-verdict-override-boundary` passed: 26 passed.
- Full `npm.cmd run validate:premerge` was not rerun for this small UI/smoke slice; the previous 2026-06-19 full premerge evidence remains recorded in the Research bridge docs strong-conclusion guard section.

Risk:
- Low frontend-only visibility and smoke-script change. The UI now displays an already-computed override boundary value, and the browser smoke writes an explicit strict-auth test feedback record before asserting the real ResearchLoops page. Remaining risk is limited to future copy/layout drift in the compact governance row.

## 2026-06-19 - Research loop workflow boundary visibility

Type: Research loop UI boundary / strict-auth browser smoke / weak-evidence visibility

Scope: expose the existing Research workflow governance boundary in the closure-health summary for one-click closed-loop samples. This is a frontend UI and smoke coverage slice only; it does not change backend workflow state generation, persistence, auth/session/cookie behavior, database migrations, order routing, or the simulation-only trading boundary.

Changes:
- Extended the Research loop closure-health boundary row so it displays `evidence_usage` and `strong_conclusion_allowed` beside `simulation_only`, `is_real_trade`, and `SIM_*`.
- Extended `smoke:frontend` so the static Research loop guard fails if that workflow boundary text or the strict-auth browser coverage is removed.
- Extended the strict-auth `research-backtest` browser scenario to assert the visible Research workflow boundary: `simulation_only=true`, `is_real_trade=false`, `evidence_usage=review_gate_only`, and `strong_conclusion_allowed=false`.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `ResearchLoopsPage one-click closed-loop sample entry is missing UI or browser-smoke coverage` after adding the static guard and before the UI/browser assertion existed.
- Green: `npm.cmd run smoke:frontend` passed after the Research loop UI and strict-auth browser assertion were added.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- `npm.cmd run typecheck` passed.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed, including `ok strict-auth browser Research Lab visible workflow boundary`.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-research-loop-workflow-boundary` passed: 26 passed.
- `git diff --check` passed with LF/CRLF working-copy warnings only.
- Full `npm.cmd run validate:premerge` was not rerun for this small UI/smoke slice; the previous 2026-06-19 full premerge evidence remains recorded in the Research bridge docs strong-conclusion guard section.

Risk:
- Low frontend-only visibility change. The UI displays existing `workflow_state` fields with conservative defaults and the browser smoke now asserts the visible text in the strict-auth research-backtest path. The remaining risk is presentation drift if future workflow-state semantics add more governance fields without updating this summary.

## 2026-06-19 - Research bridge docs strong-conclusion guard

Type: development guide, API contract, testing guide, planning docs, frontend type contract, and strict-auth browser UI boundary / Research bridge weak-evidence boundary

Scope: align the main development guide, canonical API contract, focused testing guide, project assessment, and improvement plan with the current Backtest and SignalOps Research evidence bridge response shape. This is documentation and static-smoke hardening only; it does not change runtime response generation, persistence, auth/session/cookie behavior, database migrations, SignalOps execution, order routing, or the simulation-only trading boundary.

Changes:
- Updated `docs/DEVELOPMENT_GUIDE.md` so the main closed-loop development rule says mock, fallback, weak-sample, and MFE/MAE-only evidence must stay `supporting_only` with `strong_conclusion_allowed=false`.
- Updated `docs/API_CONTRACT.md` so the Research bridge endpoint contract requires top-level `strong_conclusion_allowed=false` alongside `evidence_usage="supporting_only"`, `supporting_only=true`, `simulation_only=true`, and `is_real_trade=false`.
- Updated the SignalOps -> Research evidence bridge focused checks in `docs/TESTING_GUIDE.md` so the targeted backend commands explicitly prove `strong_conclusion_allowed=false`.
- Updated `docs/PROJECT_DEVELOPMENT_ASSESSMENT.md` and `docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md` so their Research bridge status notes also preserve `strong_conclusion_allowed=false`.
- Extended `smoke:frontend` so the static Research bridge guard fails if `docs/DEVELOPMENT_GUIDE.md`, `docs/API_CONTRACT.md`, the focused SignalOps bridge checks in `docs/TESTING_GUIDE.md`, `docs/PROJECT_DEVELOPMENT_ASSESSMENT.md`, or `docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md` drops the strong-conclusion boundary while the client still requires it.
- Refactored the Research bridge documentation marker checks into `Assert-ResearchBridgeDocBoundaryMarkers` and `$researchBridgeDocMarkerSources`, keeping document-drift failures source-specific instead of expanding the Research client high-fanout guard.
- Narrowed the frontend `ResearchBacktestVerdictInputsResponse` and `ResearchSignalOpsEvidenceResponse` root boundary fields to literal `supporting_only` / `true` / `false` types, matching the runtime guard and backend response contract.
- Extended `smoke:frontend` with `Assert-TypeScriptInterfaceBoundaryMarkers` so those bridge response interfaces cannot drift back to wide `string` / `boolean` boundary fields.
- Added browser-visible Backtest verdict-inputs boundary text so the success notice shows `evidence_usage=supporting_only`, `supporting_only=true`, `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false` after a Research bridge write.
- Extended the strict-auth `research-backtest` browser scenario to assert that visible Backtest notice boundary, not just the API payload.
- Added browser-visible SignalOps Research evidence boundary text so the selected-signal success state shows `evidence_usage=supporting_only`, `supporting_only=true`, `simulation_only=true`, `is_real_trade=false`, and `strong_conclusion_allowed=false` after attaching tick evidence to Research.
- Extended the strict-auth `signalops` browser scenario to assert that visible SignalOps Research evidence boundary, not just the API payload.

Validation:
- Red: `npm.cmd run smoke:frontend` failed with `researchClient high-fanout Research Lab calls are not guarded before entering render state` after the new API contract static guard was added and before `docs/API_CONTRACT.md` documented `strong_conclusion_allowed=false`.
- Green: `npm.cmd run smoke:frontend` passed after updating `docs/API_CONTRACT.md`.
- Red: `npm.cmd run smoke:frontend` failed with the same Research Lab static-guard error after extending the guard to the project assessment and improvement plan.
- Green: `npm.cmd run smoke:frontend` passed after both planning/status docs documented `strong_conclusion_allowed=false`.
- Red: `npm.cmd run smoke:frontend` failed with the same Research Lab static-guard error after adding an exact marker for the SignalOps bridge focused checks in `docs/TESTING_GUIDE.md`.
- Green: `npm.cmd run smoke:frontend` passed after the focused checks documented `strong_conclusion_allowed=false`.
- Red: `npm.cmd run smoke:frontend` failed with `DEVELOPMENT_GUIDE is missing the Research weak-evidence strong-conclusion boundary` after adding the Development Guide static guard.
- Green: `npm.cmd run smoke:frontend` passed after updating `docs/DEVELOPMENT_GUIDE.md` and stabilizing the guard on ASCII markers.
- Red: `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py::test_frontend_smoke_keeps_research_bridge_doc_markers_in_helper -q --basetemp=.tmp\pytest-research-bridge-doc-helper-red` failed because `scripts/smoke-frontend-routes.ps1` did not yet define `Assert-ResearchBridgeDocBoundaryMarkers`.
- Green: `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py::test_frontend_smoke_keeps_research_bridge_doc_markers_in_helper -q --basetemp=.tmp\pytest-research-bridge-doc-helper-green` passed after the helper refactor.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-research-doc-helper` passed: 25 passed.
- `npm.cmd run smoke:frontend` passed after the helper refactor.
- Red: `npm.cmd run smoke:frontend` failed with `ResearchBacktestVerdictInputsResponse is missing literal Research bridge boundary marker: evidence_usage: 'supporting_only'` after adding the literal type guard.
- Green: `npm.cmd run smoke:frontend` passed after narrowing both Research bridge response interfaces to literal root boundary fields.
- Red: `npm.cmd run smoke:frontend` failed with `BacktestPage is missing browser-visible sample-run hooks or strict-auth Backtest sample coverage` after adding the visible Backtest verdict-inputs boundary guard.
- Green: `npm.cmd run smoke:frontend` passed after the Backtest notice rendered the boundary fields and the strict-auth browser script asserted them.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed after adding the browser assertion.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- First `npm.cmd run smoke:strict-auth-browser:research-backtest` rerun failed because the wrapper serves existing `frontend/dist`, which had not yet been rebuilt and therefore did not include `backtest-verdict-inputs-boundary`.
- Final `npm.cmd run smoke:strict-auth-browser:research-backtest` passed after rebuilding, including `ok strict-auth browser Research Backtest visible verdict-inputs boundary`.
- `npm.cmd run typecheck` passed.
- `git diff --check` passed with LF/CRLF working-copy warnings only for the touched docs and smoke script.
- Red: `npm.cmd run smoke:frontend` failed with `SignalOps is missing the Research evidence bridge from selected tick/signal context` after adding the visible SignalOps Research evidence boundary guard.
- Green: `npm.cmd run smoke:frontend` passed after the SignalOps selected-signal panel rendered the boundary fields and the strict-auth browser script asserted them.
- `npm.cmd run typecheck` passed after the SignalOps UI change.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed after adding the SignalOps browser assertion.
- `npm.cmd run build` passed and refreshed `frontend/dist` for strict-auth preview.
- `npm.cmd run smoke:strict-auth-browser:signalops` passed, including `ok strict-auth browser SignalOps visible Research evidence boundary`.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-signalops-visible-boundary` passed: 25 passed.
- `git diff --check` passed with LF/CRLF working-copy warnings only for the touched files.
- Red: `$env:TIANYUAN_UV_CACHE_DIR='C:\tmp\super-uv-cache-research-bridge-ui-premerge-20260619'; npm.cmd run validate:premerge` failed at backend regression because the new Research bridge UI boundary premerge log guard intentionally required this section to mention the full-gate attempt first; backend regression reached 598 passed / 1 failed before `pre-merge gate failed at backend regression`. The default full gate remains 9 steps, including frontend responsive smoke and strict-auth browser matrix, and will be rerun after this evidence is recorded.
- Green: `$env:TIANYUAN_UV_CACHE_DIR='C:\tmp\super-uv-cache-research-bridge-ui-premerge-20260619'; npm.cmd run validate:premerge` passed after recording the RED attempt: backend regression 599 passed, closed-loop participation smoke 1 passed, analysis worker smoke 15 passed, frontend typecheck/lint/build/static smoke passed, frontend responsive smoke covered 47 routes / 188 checks, strict-auth browser matrix passed across platform, signalops, research-backtest, and portfolio-live-plugin, including `ok strict-auth browser SignalOps visible Research evidence boundary` and `ok strict-auth browser Research Backtest visible verdict-inputs boundary`; final marker was `ok pre-merge validation (9 steps, 645.8s)`.

Risk:
- Low documentation/static-smoke/frontend-type/UI evidence change. Exact-shape API clients were already covered by the prior additive response field; this slice only keeps canonical docs, current planning/status docs, frontend type declarations, and the Backtest/SignalOps success notices from lagging behind the implemented Research bridge boundary. The helper refactors change smoke-script organization only, and the UI additions display existing response fields without changing runtime product behavior.

## 2026-06-19 - Research bridge strong-conclusion boundary

Type: Research bridge contract / weak-evidence guard / frontend runtime validation

Scope: keep Backtest and SignalOps evidence bridge responses visibly supporting-only before Research verdict feedback can reuse them. This is an additive response-contract hardening slice; it does not change persistence, order routing, SignalOps execution, auth/session/cookie behavior, database migrations, or the simulation-only trading boundary.

Changes:
- Added top-level `strong_conclusion_allowed=false` to `ResearchBacktestVerdictInputsResponse` and `ResearchSignalOpsEvidenceResponse`.
- Extended `researchClient` runtime guards and frontend types so bridge responses must include `strong_conclusion_allowed=false` along with `evidence_usage="supporting_only"`, `supporting_only=true`, `simulation_only=true`, and `is_real_trade=false`.
- Extended `smoke:frontend`, strict-auth browser bridge assertions, and `docs/TESTING_GUIDE.md` so the Research bridge contract keeps documenting and guarding the strong-conclusion boundary.
- Aligned the strict-auth SignalOps Research evidence fixture with the backend response contract by keeping `strong_conclusion_allowed=false` on the top-level browser-smoke response.

Validation:
- Red: `npm.cmd run test:backend -- backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-research-bridge-strong-red` failed because both response models lacked `strong_conclusion_allowed`.
- Green: `npm.cmd run test:backend -- backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-research-bridge-strong-green` passed: 2 passed.
- Red: `npm.cmd run smoke:frontend` failed until `docs/TESTING_GUIDE.md` documented `strong_conclusion_allowed=false`.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed after adding strict-auth browser bridge assertions for `strong_conclusion_allowed=false`.
- `npm.cmd run smoke:frontend` passed after static guards covered `strong_conclusion_allowed=false` in the Research bridge client and Testing Guide.
- `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run test:frontend`, and `npm.cmd run build` passed.
- `npm.cmd run smoke:strict-auth-browser:research-backtest` passed after the strict-auth browser assertions checked the Research bridge strong-conclusion boundary.
- Red: `npm.cmd run validate:premerge` failed in the strict-auth browser matrix at the SignalOps scenario because the browser fixture response lacked top-level `strong_conclusion_allowed=false`.
- Green: `npm.cmd run smoke:strict-auth-browser:signalops` passed after aligning the SignalOps Research evidence fixture.
- `npm.cmd run validate:premerge` passed after the fixture alignment: 9 steps in 432.9s, backend regression `597 passed`, frontend responsive smoke `47 routes / 188 checks`, and strict-auth browser matrix across platform, signalops, research-backtest, and portfolio-live-plugin.

Risk:
- API clients that ignore unknown fields remain compatible; clients that validate exact response shapes may need to accept the new additive boolean.
- Backend tests still report the existing FastAPI/Starlette deprecation warnings; this slice did not address dependency-level warning cleanup.

## 2026-06-19 - Default premerge gate current-state validation

Type: validation trace / premerge gate audit / documentation guard

Scope: record the current working-tree validation after the local premerge gate was expanded to include frontend responsive smoke by default. Runtime product behavior, API schema, auth/session/cookie handling, database migrations, and real-trading boundaries were not changed in this slice.

Changes:
- Recorded the full default `validate:premerge` evidence now that the gate covers backend regression, closed-loop participation, analysis worker, frontend typecheck/lint/build/static smoke, frontend responsive smoke, and strict-auth browser matrix.
- Added a repo hygiene guard so the development log cannot silently drop the current default premerge evidence for 9 steps, backend pass count, responsive route coverage, strict-auth browser matrix, or the known LF/CRLF working-copy warning context.
- Extended `smoke:frontend` static guards so `docs/DEVELOPMENT_GUIDE.md`, the canonical development authority map, must describe the default premerge responsive smoke and strict-auth browser matrix contract.
- Updated `docs/DEVELOPMENT_GUIDE.md` to state that `validate:premerge` currently covers backend regression, closed-loop sample, analysis worker, typecheck, lint, build, static smoke, frontend responsive smoke, and strict-auth browser matrix by default.

Validation:
- `npm.cmd run validate:premerge` passed after the canonical-guide guard was added: 9 steps in 455s.
- Backend regression passed: 597 passed.
- Analysis worker smoke passed: 15 passed.
- Frontend responsive smoke passed: 47 routes / 188 checks, covering `1440x1000`, `1280x900`, `768x1024`, and `390x844`.
- Strict-auth browser matrix passed across platform, signalops, research-backtest, and portfolio-live-plugin.
- `git diff --check` passed with Git LF/CRLF working-copy warnings only.
- Red: `npm.cmd run smoke:frontend` failed with `DEVELOPMENT_GUIDE is missing the default premerge responsive smoke contract` after adding the canonical-guide static guard.
- Green: `npm.cmd run smoke:frontend` passed after updating `docs/DEVELOPMENT_GUIDE.md`.
- After adding the development-log guard, `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-premerge-log` passed: 24 passed.
- After adding the development-log guard, `npm.cmd run smoke:frontend` passed across all manifest routes and legacy redirects.
- After adding the development-log guard, `npm.cmd run typecheck` passed.

Risk:
- This slice is validation/documentation only; it does not change runtime behavior or the simulation-only trading boundary.
- The FastAPI/Starlette deprecation warnings in backend test output remain dependency-level noise to track separately.
- The full working tree still has unstaged validation and documentation changes that should be reviewed together before commit.

## 2026-06-13 - Canonical Agent mock and prior-output cleanup

Type: Agent DAG canonical semantics / frontend mock contract / validation reliability slice

Scope: continue the long-running research-loop hardening goal by removing another source of active/legacy Agent drift. This slice keeps `data_reliability_engine` and `guardrail_hub` as the active semantics while preserving old DVG/Risk/Trade Micro fields only as compatibility payloads.

Changes:
- Stopped `data_reliability_engine` prior-output mirroring from writing new `data_engine` / `data_engine_output` keys, and added a regression test for that boundary.
- Updated frontend and backend mock/seed scenarios so the active mock DAG uses `guardrail_hub` instead of `dvg_gate -> risk_firewall -> trade_micro`, adds `guardrailHub` canonical payload evidence, points mock kill-switch trigger nodes at `guardrail_hub`, and gives new pending runs a canonical Guardrail Hub owner before runtime execution.
- Updated Dashboard Agent ordering so canonical `guardrail_hub` sorts as the active guardrail node while legacy guardrail ids remain grouped in the same compatibility position.
- Added `smoke:frontend` weak-link guards to fail if frontend mock active DAG reintroduces legacy active nodes or if Dashboard loses canonical `guardrail_hub` ordering.
- Made Backtest SignalOps action labels explicitly simulation-scoped (`SIM_*` now renders as simulated buy/sell/hold/close wording) and added a static smoke guard so weak simulated evidence cannot appear as real trade language.
- Added a Backtest run governance strip showing run/job/scan id, Backtest evidence strength, blocker, next action, and the rendered simulation boundary before Research Lab / case / knowledge handoff; supporting-only backtests remain visible as non-strong evidence.
- Added a Case Library case governance strip showing case id, review evidence strength, blocker, next action, and the rendered simulation boundary before reviewed cases feed patches, Knowledge, or Evaluation; unreviewed and incomplete cases stay supporting-only / low evidence.
- Added a Case Library knowledge-patch governance strip showing patch id, evidence strength, blocker, next action, and the rendered simulation boundary before a candidate can be reviewed, plus a static smoke guard for that visibility contract.
- Added an Evaluation Sandbox patch governance strip with patch id, evidence strength, blocker, next action, and the rendered simulation boundary so evaluation/A-B evidence stays supporting-only until review, with static smoke coverage.
- Added a Knowledge Versions governance strip showing version id, regression-backed evidence strength, blocker, next action, and the rendered simulation boundary before a version is treated as an auditable promotion or rollback point.
- Added a Knowledge item governance strip showing item id, evidence strength, blocker, next action, and the rendered simulation boundary for every knowledge item, including collapsed active entries, plus a static smoke guard.
- Added a Portfolio snapshot governance strip showing snapshot id, evidence strength, blocker, next action, and the rendered simulation boundary before a snapshot is handed to New Task, plus a static smoke guard for that visibility contract.
- Added a Research Lab closure-health governance strip showing iteration id, evidence strength, blocker, next action, and the rendered simulation boundary from backend `workflow_state` / verdict inputs, plus a static smoke guard.
- Added a New Task analysis-run preflight governance strip showing the pending run context id, evidence strength, blocker, next action, and `simulation_only=true / is_real_trade=false / SIM_*` boundary before create/start.
- Added a SignalOps review-card governance strip showing queue/signal id, evidence strength, blocker, next action, and `simulation_only=true / is_real_trade=false / SIM_*` boundary before manual candidate review, plus a static smoke guard.
- Added an Agent DAG run governance strip showing run id, DAG evidence strength, blocker, next action, and the rendered simulation boundary before graph inspection, plus a static smoke guard that keeps mock/degraded evidence from rendering as strong.
- Added a Guardrail Hub governance strip showing canonical/legacy context id, evidence strength, blocker, next action, and the rendered simulation boundary before quant-core handoff; legacy-synthesized guardrails now display as supporting-only evidence.
- Added a Quant Core governance strip showing run/provenance id, quant evidence strength, blocker, next action, and the rendered simulation boundary before SignalOps/backtest handoff; missing canonical `quant_core.coreInterpretation` now displays as supporting-only evidence.
- Corrected the 2026-06-09 development log wording so the documented active route uses `data_reliability_engine -> guardrail_hub -> quant_core` instead of the old `data_engine` alias.
- Added `TIANYUAN_UV_CACHE_DIR` support to `scripts/test-backend.ps1` so targeted backend tests can use an explicit external uv cache when the repo-local `.uv-cache` is locked by OneDrive or scanners; documented the override in `docs/TESTING_GUIDE.md`.

Validation:
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\agent_executor.py backend\tests\test_agent_executor.py`: passed.
- `.\.venv\Scripts\python.exe -m py_compile backend\app\core\analysis_run_create.py backend\app\mock\scenarios.py backend\tests\test_analysis_lifecycle_core_services.py`: passed.
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_agent_executor.py backend\tests\test_agent_runtime.py -q`: passed, 102 passed / 98 warnings.
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_analysis_lifecycle_core_services.py -q`: passed, 13 passed / 42 warnings.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run test:frontend`: passed; this workspace maps it to frontend typecheck.
- `npm.cmd run build`: passed; existing Vite/PostCSS `from` warning remains.
- `npm.cmd run smoke:frontend`: passed across route manifest and legacy routes.
- `git diff --check`: passed; Git reported existing Windows LF/CRLF working-copy warnings.

Validation notes:
- `npm.cmd run test:backend -- backend\tests\test_agent_executor.py backend\tests\test_agent_runtime.py -q --basetemp=.tmp\pytest-agent-canonical` did not start because `uv` could not write `jsonpath-0.82.2-py3-none-any.whl` under `.uv-cache`; rerunning the same command outside the sandbox hit the same Windows access-denied error.
- Retrying the same npm backend wrapper with `TIANYUAN_UV_CACHE_DIR=C:\tmp\super-uv-cache` proved the external cache override got past the `.uv-cache` permission error and built `jsonpath`, but dependency download then failed on PyPI network/DNS/TLS errors before pytest could start.

Risk:
- The focused pytest itself passed through the existing `.venv`; the npm/uv wrapper path still needs a clean network/cache pass before claiming the wrapper gate is fully green.
- Legacy public fields remain intentionally present for old runs and frontend compatibility; this slice only stops treating them as active mock/prior-output owners, and the backend seed change is limited to pending canonical metadata rather than execution semantics.
- The Backtest label change is display/static-smoke only; it does not change execution semantics, order routing, or `simulation_only=true` / `is_real_trade=false` enforcement.
- The Backtest run governance strip is display/static-smoke only; run creation, parameter scans, SignalOps samples, experiment-package download, Research verdict input creation, and simulation execution semantics are unchanged.
- The Case Library case governance strip is display/static-smoke only; case creation, review saving, tag creation, deletion, patch approval, and Knowledge/Evaluation APIs keep their existing semantics.
- The Case Library patch governance strip is display/static-smoke only; patch approval, evaluation, version promotion, and rollback APIs keep their existing permission and validation semantics.
- The Evaluation Sandbox governance strip is display/static-smoke only; running evaluations, strategy experiments, patch approval, and knowledge promotion continue through the existing guarded APIs.
- The Knowledge Versions governance strip is display/static-smoke only; creating drafts, rerunning post-publish regression, rollback, approval records, and version APIs keep their existing semantics.
- The Knowledge item governance strip is display/static-smoke only; Knowledge creation, review, archive, active-context reuse, and backend response guards are unchanged.
- The Portfolio snapshot governance strip is display/static-smoke only; snapshot creation, import, delete, New Task handoff, and downstream simulation boundaries are unchanged beyond making the existing handoff boundary visible.
- The Research Lab closure-health governance strip is display/static-smoke only; workflow maturity and simulation boundaries remain backend-authored and no frontend rule promotes weak evidence into acceptance.
- The New Task analysis-run governance strip is display/static-smoke only; it does not change `createAnalysisRun`, `startAnalysisRun`, run hydration, or backend guardrail execution.
- The SignalOps review-card governance strip is display/static-smoke only; review decisions, candidate approval blocking, paper-order routing, and simulation execution semantics are unchanged.
- The Agent DAG run governance strip is display/static-smoke only; DAG nodes, edge construction, LLM invocation evidence, and backend run execution semantics are unchanged.
- The Guardrail Hub governance strip is display/static-smoke only; canonical guardrail execution, legacy fallback synthesis, risk/DVG/Trade Micro compatibility tabs, and quant-core handoff semantics are unchanged.
- The Quant Core governance strip is display/static-smoke only; quant calculations, path-risk filters, QIAM, scenario interpretation, Technical Kline case governance, and SignalOps/backtest handoff semantics are unchanged.

## 2026-06-09 - Guardrail Hub canonical integration

Type: agent DAG consolidation / guardrail rule-engine integration / frontend and contract compatibility

Scope: implement the approved `guardrail_hub` plan by consolidating DVG Gate, Risk Firewall / Kill Switch, and Trade Micro into one canonical active guardrail agent. The change updates backend execution, artifact normalization, retry aliasing, preflight blocking, public run shape, frontend routing, documentation, workflow config, and focused regression tests. It intentionally does not introduce a destructive database migration; existing DVG and Kill Switch persistence shapes remain the compatibility baseline.

Changes:
- Added `GuardrailHubAgent` as the canonical deterministic rule engine for DVG evidence gating, risk/firewall decisions, kill switch state, trade microstructure, execution reachability, status aggregation, `finalDecisionCap`, warnings, and audit metadata.
- Changed active run modes to route through `data_reliability_engine -> guardrail_hub -> quant_core`, with FAST at 5 active agents and STANDARD/DEEP at 8 active agents; legacy `data_engine`, `dvg_gate`, `dvg_evidence_gate`, `risk_firewall`, `trade_micro`, `atrade`, `hallucination_guardrail`, `flash_crash`, and `portfolio` now redirect or retry-map to canonical active nodes.
- Mirrored canonical output back into `run.dvg`, `run.risk`, `run.atrade`, `run.killSwitch`, `prior_outputs`, `agentModuleResults.guardrail_hub`, and legacy module result keys so QIAM, Execution, AntiConclusion, FinalWriter, SignalOps, history, compare, and compressed summaries can read both new and old runs.
- Added runtime hard-stop handling so HARD / COMPLIANCE guardrail triggers immediately skip later positive trading nodes and recompute nodes, agent results, DAG events, final context, and orchestrator plan before continuing to `final_writer`.
- Updated realtime market-data preflight blocking to write `guardrailHub` alongside the existing legacy fields instead of only mutating DVG and Kill Switch.
- Added `/guardrail-hub` as the unified frontend page and retained `/dvg-gate`, `/risk`, and `/trade-micro` as compatibility routes that open the relevant tab over the same canonical payload, with legacy-field fallback synthesis for older runs.
- Consolidated the main sidebar and TopBar route state so only `/guardrail-hub` appears as the active guardrail navigation entry; `/dvg-gate`, `/risk`, and `/trade-micro` remain covered through `routeManifest.legacyRoutes` and page-level tabs.
- Hardened the frontend smoke and responsive route collectors so `legacyRoutes` remain browser-covered without reintroducing legacy guardrail items into the primary sidebar.
- Updated `AnalysisRun.guardrailHub`, frontend types, API contract, agent registry, DVG rules, kill switch rules, SignalOps rules, development guide, and `19_WORKFLOW_CONFIG.yml` to describe `guardrail_hub` as the only active guardrail node.

Validation:
- `.\.venv\Scripts\python.exe -m py_compile backend\app\modules\guardrail_hub.py backend\app\core\agent_framework.py backend\app\core\agent_executor.py backend\app\api\routes_analysis.py backend\app\models\analysis.py`: passed.
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_guardrail_hub.py backend\tests\test_agent_runtime.py -q`: passed, 65 passed.
- `.\.venv\Scripts\python.exe -m pytest backend\tests\test_guardrail_hub.py backend\tests\test_agent_executor.py backend\tests\test_dvg_gate.py backend\tests\test_risk_agent.py backend\tests\test_kill_switch.py -q`: passed, 75 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run test:frontend`: passed.
- `npm.cmd run build`: passed; the existing Vite/PostCSS `from` warning remains.
- `node --check scripts\smoke-frontend-responsive.mjs`: passed.
- `node --check scripts\chaos-frontend-pressure.mjs`: passed.
- `npm.cmd run smoke:frontend`: passed, including `/guardrail-hub`, `/dvg-gate`, `/risk`, and `/trade-micro`.
- `npm.cmd run smoke:frontend:responsive`: passed after the TopBar mobile overflow fix, `1440x1000`, `1280x900`, `768x1024`, `390x844`; 48 routes; 192 checks.

Validation notes:
- `npm.cmd run test` maps to the full backend test command in this workspace and did not complete within the 120s command window; pytest then emitted `OSError: [Errno 22] Invalid argument` while flushing terminal output. Focused guardrail/backend/frontend checks above passed.
- The first responsive browser smoke runs exposed a pre-existing mobile TopBar overflow around the compact header toggle; the final run passed after constraining the title area and moving header padding into the inner shell container.

Risk:
- Full backend regression was not completed in this slice because the aggregate `npm.cmd run test` invocation timed out; the next premerge pass should rerun the broader backend suite outside the short command window.
- No database migration was added by design. Unified query/storage needs for DVG and Kill Switch should be handled as a separate migration proposal with compatibility and rollback coverage.
- The workspace already contained many unrelated dirty files; this slice did not revert or normalize unrelated changes.

## 2026-06-07 - Development guide final current-state validation

Type: completion audit / full validation

Scope: re-validate the current working tree against `docs/DEVELOPMENT_GUIDE.md`, `docs/FRONTEND_REDESIGN_GUIDE.md`, and `docs/TESTING_GUIDE.md` after the frontend redesign implementation, responsive smoke automation, and chaos acceptance tooling were present. No product behavior, API schema, database migration, auth/session/cookie logic, or deployment configuration was changed in this validation slice.

Changes:
- No runtime code changes in this slice; this entry records the current-state verification required by the development guide completion audit.
- Stopped two matching local project backend dev-server processes before `chaos:isolated` because the chaos guard correctly refused to run while a process might write `storage\tianyuan_quant.db`.

Validation:
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:frontend` passed across all manifest routes and legacy redirects.
- `npm.cmd run smoke:frontend:responsive` passed: `1440x1000`, `1280x900`, `768x1024`, `390x844`; 47 routes; 188 checks.
- `npm.cmd run test:backend` passed: 516 tests.
- `npm.cmd run chaos:isolated` passed: frontend build, 47 routes / 188 concurrent built-route requests, 69 destructive backend boundary tests, full strict-auth browser matrix, and accepted unchanged real `storage\tianyuan_quant.db` content.

Risk:
- `smoke:frontend:responsive` and `chaos:isolated` require real browser/backend processes and may need unsandboxed execution in this desktop environment.
- Vite still emits the existing PostCSS `from` warning during build; this validation did not introduce or resolve it.
- The strict-auth browser matrix used its existing direct API fallback for one Backend Status attempt diagnostics wait timeout and retried one Research Lab SPA navigation; both fallback paths passed and remain explicit in the command output.

## 2026-06-07 - Executable frontend redesign responsive acceptance

Type: frontend redesign acceptance automation / responsive hardening

Scope: convert the frontend redesign guide additions into executable checks and close the mobile overflow gaps found by the new matrix. Runtime business behavior, API schemas, auth/session/cookie handling, database migrations, and backend deployment topology are unchanged.

Changes:
- Added `npm.cmd run smoke:frontend:responsive` through `scripts/smoke-frontend-responsive.mjs`, covering every `routeManifest` route and legacy redirect at `1440x1000`, `1280x900`, `768x1024`, and `390x844`.
- Extended `scripts/smoke-frontend-routes.ps1` so the standard frontend smoke fails if the responsive command, fixed viewport matrix, Figma chart semantics, or PR Definition of Done rules disappear from the docs/tooling contract.
- Updated `docs/DEVELOPMENT_GUIDE.md`, `docs/FRONTEND_REDESIGN_GUIDE.md`, and `docs/TESTING_GUIDE.md` to point to the responsive smoke command as the executable acceptance path.
- Hardened the material page header and Research Lab shared page header wrapping so long command/status tags do not create unintended mobile horizontal overflow.

Validation:
- `node --check scripts\smoke-frontend-responsive.mjs`
- `git diff --check -- scripts\smoke-frontend-responsive.mjs scripts\smoke-frontend-routes.ps1 package.json docs\FRONTEND_REDESIGN_GUIDE.md docs\TESTING_GUIDE.md docs\DEVELOPMENT_GUIDE.md docs\DEVELOPMENT_LOG.md`
- `npm.cmd run typecheck`
- `npm.cmd run lint`
- `npm.cmd run build`
- `npm.cmd run smoke:frontend`
- `npm.cmd run smoke:frontend:responsive`

Risk:
- No backend/API/schema/auth code changed, so backend suites were not required for this slice.
- The responsive smoke uses a real browser process and therefore may require unsandboxed execution in this desktop environment.
- Vite build still emits the existing PostCSS `from` warning; this task did not introduce or resolve that warning.

## 2026-06-07 - Frontend redesign guide acceptance detail expansion

Type: documentation contract hardening / frontend redesign acceptance guide

Scope: expand the frontend redesign development guidance after the all-page mockup and Figma UI work. This is documentation-only and keeps the existing React/Vite/Tailwind/Recharts/ReactFlow frontend, FastAPI/SQLite backend boundary, Supabase non-authority stance, and simulation-only trading policy unchanged.

Changes:
- Extended `docs/FRONTEND_REDESIGN_GUIDE.md` with Figma handoff rules, fixed responsive viewport acceptance, accessibility and interaction requirements, performance/dependency budgets, security/privacy handling, release/rollback expectations, runtime observability, and a PR Definition of Done.
- Updated `docs/DEVELOPMENT_GUIDE.md` so the main guide points to the expanded frontend redesign authority and carries the high-level responsive, Figma, accessibility, dependency, release, and rollback rules without duplicating the detailed checklist.
- Updated `docs/TESTING_GUIDE.md` with a visual/responsive acceptance section tied to the fixed `1440x1000`, `1280x900`, `768x1024`, and `390x844` viewport matrix.

Validation:
- `rg -n "Figma 交接规范|响应式与截图验收矩阵|可访问性与交互标准|性能与依赖预算|安全与隐私|发布、灰度与回滚|运行观测|PR Definition of Done|1440x1000|390x844|KLineCurve|VolumeBar" docs\FRONTEND_REDESIGN_GUIDE.md`: confirmed all added frontend redesign sections and chart semantics.
- `rg -n "响应式/Figma|1440x1000|Rectangle|可访问|feature flag|PR DoD|FRONTEND_REDESIGN_GUIDE" docs\DEVELOPMENT_GUIDE.md`: confirmed the main guide references the new rules.
- `rg -n "前端重构视觉与响应式验收|1440x1000|390x844|smoke:frontend|secret|viewport" docs\TESTING_GUIDE.md`: confirmed the testing guide visual/responsive entrypoint.
- `git diff -- docs\FRONTEND_REDESIGN_GUIDE.md docs\DEVELOPMENT_GUIDE.md docs\TESTING_GUIDE.md`: reviewed the documentation diff; existing LF/CRLF warnings remain.

Risk:
- Documentation-only change. Runtime API behavior, frontend implementation, database schema, auth/session/cookie behavior, deployment scripts, Supabase boundary, and SignalOps `simulation_only=true` / `is_real_trade=false` policy are unchanged. No typecheck/lint/build was run because no code changed.

## 2026-06-06 - Completed all-page mockup data-presentation refactor

Type: frontend full-refactor completion / Material data presentation / static and chaos guard hardening

Scope: complete the approved mockup data-presentation standard across every retained frontend page surface. The implementation keeps the existing Vite + React + TypeScript + Tailwind + Recharts/ReactFlow stack and the existing FastAPI + SQLite API boundary. No Supabase migration, database schema change, public API expansion, or real trading path was introduced.

Changes:
- Completed shared Material-style data presentation on the remaining page surfaces, including Dashboard, Global Market, Data Engine, Trade Micro, Backtest, Research Lab shell, DVG, Execution, Final Writer, Anti Conclusion, Risk, Permission, Market, Scenario, Technical Kline, Quant Engine, and retained legacy-compatible pages.
- Converted page tables into the `TableShell` / `institution-table` system and reused `MetricTile`, `SourceFreshnessPanel`, `FactorBarStack`, and related Material components so KPI, table, provenance, freshness, factor, matrix, sparkline, status, and risk summaries read consistently.
- Extended `smoke:frontend` from shell/key-page checks to every `*Page.tsx` / `*Console.tsx`, requiring shared Material data-presentation evidence, institutional table classes, and blocking legacy dark cockpit, gradient shell, wide-sidebar, and old table utility regressions.
- Hardened `chaos:isolated`: it now refuses to start when a project backend process may write `storage\tianyuan_quant.db`, and verifies the real DB with a content SHA-256 fingerprint instead of metadata-only checks.
- Stabilized the strict-auth browser matrix under isolated SQLite lock pressure by retrying Backend Status filtered attempt and queue UI checks through the page controls while still requiring seeded rows to be present in API responses and rendered in the DOM.

Validation:
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:frontend` passed for all manifest routes, Research Lab subroutes, legacy redirects, and the new page-level Material/table guards.
- `node --check scripts\smoke-strict-auth-browser.mjs` passed.
- PowerShell parser check for `scripts\chaos-validation.ps1` passed.
- `npm.cmd run smoke:strict-auth-browser:platform` passed after the browser smoke retry hardening.
- `npm.cmd run validate:premerge` passed: 516 backend tests, closed-loop participation smoke, analysis-worker smoke, frontend typecheck/lint/build/static smoke, and the full strict-auth browser matrix.
- `npm.cmd run chaos:isolated` passed: frontend build, 47 routes / 188 concurrent built-route requests at concurrency 12, 69 destructive backend boundary tests, strict-auth browser matrix, and unchanged real `storage\tianyuan_quant.db` content fingerprint.

Validation notes:
- The first chaos run correctly refused final acceptance because an existing local dev backend on port 8000 was still running and the real DB changed during the isolated window. After stopping the dev server, the script was hardened to fail before starting if a similar project backend process is present.
- Vite still emits the existing PostCSS `from` option warning during build. Backend Status queue checks may still use their direct API fallback under SQLite lock pressure, but the smoke now retries through page controls and still requires visible DOM evidence.

Risk:
- Runtime API behavior, Pydantic contracts, frontend API clients, SQLite schema, Supabase boundary, and SignalOps `simulation_only=true` / `is_real_trade=false` policy are unchanged. The main residual risk is visual density across very small screens; static, build, browser, and chaos gates now cover regression boundaries, but final visual polish still depends on screenshot review when a specific viewport is disputed.

## 2026-06-06 - Institutional quantitative UI refactor acceptance hardening

Type: frontend full-refactor acceptance / data-presentation guardrails / isolated chaos validation

Scope: finalize the approved current mockup baseline for the quantitative system frontend. The work keeps the existing React/Vite/Tailwind/Recharts/ReactFlow stack and the existing FastAPI + SQLite API/storage boundary. Supabase is not introduced as an authority store. The accepted visual baseline is the light institutional finance interface: 68px icon rail, command bar, secondary nav, compact tables, white surfaces, light gray containers, blue primary actions, teal data accents, and small-radius controls.

Changes:
- Added static frontend smoke guards for the institutional shell, design tokens, shared data-presentation components, and key Quant Core / Backend Status / Portfolio / SignalOps / Research Lab usage.
- Added `scripts/chaos-frontend-pressure.mjs` for concurrent route pressure across every manifest route and legacy redirect in the built frontend.
- Added `scripts/chaos-validation.ps1` and `npm.cmd run chaos:isolated` to run frontend build, route pressure, backend destructive boundary tests, and strict-auth browser matrix in isolated temp paths.
- Updated the development and testing guides with the accepted refactor baseline, backend/Supabase boundary, and chaos validation entrypoint.

Validation:
- `npm.cmd run typecheck` passed.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed.
- `npm.cmd run smoke:frontend` passed, including the added institutional shell, token, and data-presentation static guards plus all manifest route checks.
- `npm.cmd run chaos:isolated` passed: frontend build, 188 concurrent built-route requests across 47 routes at concurrency 12, 69 focused destructive backend boundary tests, and the full strict-auth browser matrix. The command completed with the real `storage\tianyuan_quant.db` unchanged.
- `npm.cmd run validate:premerge` passed: 516 backend regression tests, closed-loop participation smoke, analysis-worker smoke, frontend typecheck/lint/build/static smoke, and strict-auth browser matrix.
- Validation notes: Vite still emits the existing PostCSS `from` option warning during build, and the strict-auth Backend Status queue check used its direct API fallback after a browser response wait timeout. Both paths passed and are not introduced by this refactor.

Risk:
- The new chaos command is intentionally heavier than normal smoke and may take significantly longer because it includes strict-auth browser matrix by default. It must not be run against production or a live local server. Runtime API behavior, database schema, Supabase integration, real trading boundaries, and SignalOps `simulation_only=true` / `is_real_trade=false` policy are unchanged.

## 2026-06-04 - Archived completed code-review development guide

Type: completed-guide deletion / documentation trace preservation

Scope: delete the completed `docs/CODE_REVIEW_FIX_GUIDE_2026-05-21.md`专项修复指南 after its R1-R13, T1-T3, and D1-D3 items were already verified closed. The goal is to keep only current development authority in `DEVELOPMENT_GUIDE.md` while preserving the completion trail in this log and generated historical review logs.

Changes:
- Deleted `docs/CODE_REVIEW_FIX_GUIDE_2026-05-21.md`.
- Added the compressed completion conclusion to `docs/DEVELOPMENT_GUIDE.md`: R1-R13, T1-T3, and D1-D3 have no remaining current development items.
- Updated `docs/QUANT_SYSTEM_IMPROVEMENT_PLAN.md` so current review-fix work no longer points readers at the deleted专项指南.
- Updated repo hygiene so the deleted guide must stay removed, while the total development guide and this log retain the work trace.

Validation:
- `rg -n "CODE_REVIEW_FIX_GUIDE_2026-05-21" docs\DEVELOPMENT_GUIDE.md docs\QUANT_SYSTEM_IMPROVEMENT_PLAN.md docs\PROJECT_DEVELOPMENT_ASSESSMENT.md docs\TESTING_GUIDE.md docs\NEXT_DEVELOPMENT_PLAN.md docs\API_CONTRACT.md -S`: only the deletion note in `DEVELOPMENT_GUIDE.md` remains.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py::test_retired_full_run_checklist_and_legacy_testing_tail_stay_removed backend\tests\test_repo_hygiene.py::test_encoding_review_guidance_is_guarded_by_strict_utf8_scan -q --basetemp=.tmp\pytest-completed-guide-deletion-hygiene`: passed, 2 passed.

Risk:
- Documentation-only deletion. Runtime behavior, API contracts, auth, storage, workers, plugin execution, and SignalOps simulation/live-trading boundaries are unchanged. Exact historical wording remains recoverable from git history and generated historical review logs; current working guidance lives in `DEVELOPMENT_GUIDE.md`.

## 2026-06-04 - Aligned assessment docs with current validation authority

Type: documentation baseline hygiene / review-goal audit support

Scope: continue the review-goal audit by removing stale current-state claims from the remaining assessment and improvement-plan documents. `CODE_REVIEW_FIX_GUIDE_2026-05-21.md` already says R1-R13, T1-T3, and D1-D3 have no remaining current items; the follow-up risk was that `PROJECT_DEVELOPMENT_ASSESSMENT.md` and `QUANT_SYSTEM_IMPROVEMENT_PLAN.md` still contained old validation counts, a historical full-backend failure note, and an outdated `13 Agent DAG` statement.

Changes:
- Updated `PROJECT_DEVELOPMENT_ASSESSMENT.md` to point current validation at `validate:phase1-3`, `validate:premerge`, and `validate:module-participation`.
- Updated `QUANT_SYSTEM_IMPROVEMENT_PLAN.md` to replace old local DB snapshot/count-based acceptance with the current temporary-DB smoke and root validation gates.
- Replaced the old P0-P4 execution tail with current execution order, acceptance commands, and current target-state language.
- Corrected the Agent DAG count to the current 10 active Agent registry.
- Added repo hygiene coverage so old validation counts, the old historical full-backend failure note, stale next-stage target wording, and `13 Agent DAG` cannot be reintroduced silently.

Validation:
- `rg -n "13 Agent DAG|最新基线为 `64 passed|`63 passed, 4 warnings`|461 passed, 2 failed|下一阶段完成后，系统应达到|Backtest、Research、Case、Knowledge、Evaluation 不再是空表" docs\QUANT_SYSTEM_IMPROVEMENT_PLAN.md docs\PROJECT_DEVELOPMENT_ASSESSMENT.md -S`: no matches.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py::test_current_assessment_docs_do_not_restore_stale_validation_baselines -q --basetemp=.tmp\pytest-current-assessment-doc-baseline-hygiene`: passed, 1 passed.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-repo-hygiene-current-doc-baseline`: passed, 22 passed.
- `npm.cmd run validate:module-participation`: passed after the doc/hygiene update, 5 steps in 122.2s. SignalOps passed 2 tests, MFE/MAE Quant Core passed 4 tests, closed-loop persistence passed 1 test, analysis worker passed 15 tests plus CLI smoke, and portfolio/backtest/research/evaluation/plugin/data-health modules passed 192 tests.

Risk:
- Documentation-only plus hygiene-test change. No runtime behavior, API contract, auth, storage mutation, worker behavior, plugin execution, or SignalOps simulation/live-trading boundary changed.

## 2026-06-04 - Compressed development guide and closed validation cleanup gaps

Type: development guide compression / validation stability / SQLite mirror hardening

Scope: optimize the current development guide so completed work is represented as current baseline, contract, entrypoint, and risk posture instead of repeated historical implementation detail. During validation, strict-auth smoke also exposed two cleanup gaps: browser smoke wrappers could leave spawned backend child processes alive, and concurrent SQLite mirror column initialization could raise duplicate-column errors and slow `/api/analysis/runs` enough to trip browser timeouts.

Changes:
- Reworked `docs/DEVELOPMENT_GUIDE.md` around document authority, compression rules, current system baseline, current development phases, module ownership, and verification commands.
- Kept completed historical development compressed in `docs/DEVELOPMENT_LOG.md`; this guide now points to the log for Scope/Changes/Validation/Risk detail instead of duplicating old checklists.
- Updated Research closure and strict-auth browser smoke wrappers to stop spawned process trees, not only the launcher process.
- Made analysis job SQLite mirror column initialization idempotent when concurrent connections race to add the same migration column.
- Added focused backend hygiene and SQLite regression tests for the process-tree cleanup and duplicate-column behavior.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-dev-guide-doc-compression`: passed, 19 passed.
- `npm.cmd run validate:phase1-3`: passed, including module participation, frontend checks, static smoke, and Research closure browser smoke.
- `npm.cmd run test:backend -- backend\tests\test_analysis_job_sqlite.py -q --basetemp=.tmp\pytest-analysis-job-sqlite-after-duplicate-column-fix`: passed, 16 passed.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed after the SQLite duplicate-column fix; no temporary `uvicorn` child process remained.
- `npm.cmd run validate:premerge`: passed, 8 steps in 637s, including full strict-auth browser matrix.

Risk:
- Low documentation plus validation-stability change. Runtime behavior changed only for SQLite mirror migration idempotency under concurrent initialization; unrelated SQLite operational errors still raise. API contracts, auth, production data, order routing, plugin execution, and SignalOps `simulation_only=true` / `is_real_trade=false` boundaries are unchanged.

## 2026-06-04 - Stabilized New Task handoff and Research closure browser cleanup

Type: Phase 1-3 acceptance / browser handoff / smoke process cleanup

Scope: `validate:phase1-3` reached the Research closure browser smoke but the New Task -> Live Run handoff could fail when the initial run-detail hydration returned a transient 404 in worker mode. A later successful browser smoke still left spawned backend child processes alive because the smoke script stopped only the `uv` launcher, not the spawned `python start_uvicorn.py` process.

Changes:
- Updated `NewTaskPage` so successful `startAnalysisRun()` immediately navigates to `/live-run?run_id=...`; initial `getAnalysisRun()` hydration now runs in the background and no longer blocks the handoff.
- Updated `LiveRunConsole` so a deep-linked `run_id` from the URL takes precedence over stale store state while the detail request hydrates.
- Added a worker-mode HTTP regression covering portfolio-backed create -> start -> detail, proving the queued run remains visible and keeps the simulation-only queue event.
- Updated frontend static smoke guards for the non-blocking handoff and deep-linked Live Run id contract.
- Updated `smoke-research-closure-live.ps1` to stop spawned process trees in cleanup, and added repo hygiene coverage so the browser smoke cannot leave `uv` child backends behind again.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py::test_worker_mode_http_create_start_detail_preserves_created_run -q --basetemp=.tmp\pytest-worker-http-create-start-detail-fixed`: passed, 1 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed.
- `npm.cmd run build`: passed.
- `npm.cmd run smoke:research-closure:browser`: passed; verified New Task-created run reached Live Run as `QUEUED`, direct Audit/Quant Core/DAG/Debate/Final hydration, Research closure IDs, temp portfolio counts, and clean process exit.
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py::test_worker_mode_http_create_start_detail_preserves_created_run backend\tests\test_repo_hygiene.py::test_research_closure_browser_smoke_cleans_spawned_process_trees -q --basetemp=.tmp\pytest-handoff-process-tree-focused`: passed, 2 passed.
- `git diff --check -- frontend\src\components\task\NewTaskPage.tsx frontend\src\components\live\LiveRunConsole.tsx scripts\smoke-frontend-routes.ps1 scripts\smoke-research-closure-live.ps1 backend\tests\test_analysis_workflow.py backend\tests\test_repo_hygiene.py`: passed with LF/CRLF working-copy warnings only.
- `npm.cmd run validate:phase1-3`: passed; module participation included SignalOps 2 passed, MFE/MAE 4 passed, closed-loop 1 passed, analysis worker 15 passed plus CLI smoke, and portfolio/backtest/research/evaluation/plugin/data-health modules 192 passed.

Risk:
- Low targeted UI and smoke cleanup change. API contracts, auth, database schema, production data, real trading boundaries, and SignalOps `simulation_only=true` / `is_real_trade=false` behavior are unchanged. Live Run now displays the URL `run_id` while detail hydration catches up, so early fields can briefly show empty/default values, but the stream and refresh target the intended run instead of stale store state.

## 2026-06-04 - Stabilized backend pytest temp handling for pre-merge worker smoke

Type: validation stability / Windows temp isolation / pre-merge gate

Scope: `npm.cmd run validate:premerge` failed at `smoke:analysis-worker` after backend regression and closed-loop participation had already passed. The failure was not a worker behavior regression; `uv` could not update a generated `uv-trampoline-*.exe` under repo `.tmp\pytest-temp-*` inside the OneDrive workspace.

Changes:
- Updated `scripts\test-backend.ps1` so pytest cache and basetemp stay under repo `.tmp`, while `TEMP` / `TMP` point to `%LOCALAPPDATA%\Temp\tianyuan-quant-agent-ui` or the system temp fallback.
- Added repo hygiene coverage so the backend pytest wrapper keeps `uv` trampoline executables out of repo temp while preserving repo-local pytest basetemp.
- Updated the testing guide to describe the split between traceable pytest artifacts and system-temp `uv`/Python trampoline files.

Validation:
- Initial `npm.cmd run validate:premerge`: failed at analysis worker smoke with `Failed to update Windows PE resources` for `.tmp\pytest-temp-...\uv-trampoline-*.exe`; backend regression passed with 498 tests and closed-loop participation passed with 1 test before the failure.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py::test_backend_pytest_wrapper_keeps_uv_trampolines_out_of_repo_temp -q --basetemp=.tmp\pytest-uv-temp-hygiene`: passed, 1 passed.
- PowerShell parse check for `scripts\test-backend.ps1` and `scripts\smoke-analysis-worker.ps1`: passed.
- `npm.cmd run smoke:analysis-worker`: passed, 15 worker/queue tests plus CLI `worker:analysis -Once`.
- `npm.cmd run validate:premerge`: passed.

Risk:
- Low validation-wrapper change. Runtime behavior, API contracts, auth, production data, order routing, worker semantics, and SignalOps `simulation_only=true` / `is_real_trade=false` boundaries are unchanged. The only behavior change is where temporary `uv` trampoline executables are created during backend test runs.

## 2026-06-04 - Added MFE/MAE and observability to default backend regression

Type: default regression coverage / module participation / stability gate

Scope: close the gap between the new module participation gate and the default backend regression used by pre-merge. MFE/MAE Quant Core and observability/Backend Status metrics were covered by focused module validation, but not by the default `npm.cmd run test:backend` suite.

Changes:
- Added `backend\tests\test_mfe_mae_quant_core_chain.py` to the default backend regression suite.
- Added `backend\tests\test_observability_routes.py` to the default backend regression suite.
- Updated repo hygiene so the default backend suite must retain analysis lifecycle core services, MFE/MAE Quant Core, observability, and the existing high-risk module tests.
- Updated the testing guide's default backend test list to match the script.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-default-backend-mfe-observability-hygiene`: passed, 18 passed.
- `npm.cmd run test:backend`: passed, 498 passed.
- `git diff --check -- scripts\test-backend.ps1 backend\tests\test_repo_hygiene.py docs\TESTING_GUIDE.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low validation-script/documentation change. Runtime behavior, API contracts, auth, production data, order routing, and SignalOps simulation-only/no-real-trade boundaries are unchanged. The default backend suite is heavier, but it now better matches the module participation acceptance surface.

## 2026-06-04 - Added module participation validation gate

Type: module participation gate / plugin artifact stability / validation hardening

Scope: give the "every module can participate" requirement a direct root command instead of relying on scattered default tests and smoke scripts. The new gate aggregates the core module surfaces that feed the current simulation-only research workflow.

Changes:
- Added `scripts/module-participation-validation.ps1` and `npm.cmd run validate:module-participation`.
- The gate validates SignalOps auto-paper participation, MFE/MAE Quant Core participation, isolated closed-loop persistence, analysis worker participation, and focused Portfolio, Backtest, Research, Evaluation, Plugin, Data Health, and observability backend modules.
- Updated `validate:phase1-3` so broad Phase 1-3 acceptance calls `validate:module-participation` before frontend checks and browser closure smoke.
- Shortened per-run pytest basetemp ids in module and worker smoke scripts to avoid stale fixed temp directories and Windows path-length failures.
- Fixed Plugin package artifact uploads to use short temporary filenames before atomic replace. This prevents long Windows temp paths from failing before artifact storage, external scan, or cleanup tests can prove the module works.
- Added repo hygiene and static frontend guards for the new module participation gate and the short plugin artifact temp filename contract.

Validation:
- Initial `npm.cmd run validate:module-participation` exposed a fixed `.tmp\pytest-signalops-auto-paper-chain` cleanup permission failure; the gate now uses unique short basetemp paths.
- A second `validate:module-participation` exposed Plugin artifact upload `FileNotFoundError` on long temporary paths; the runtime temp filename was shortened.
- `npm.cmd run test:backend -- backend\tests\test_plugin_store.py::test_plugin_artifact_upload_stores_server_hash_and_updates_manifest backend\tests\test_plugin_store.py::test_plugin_artifact_upload_ingests_required_external_scan_verdict backend\tests\test_plugin_store.py::test_plugin_artifact_upload_records_zip_scan_warning backend\tests\test_plugin_store.py::test_plugin_artifact_cleanup_dry_run_keeps_expired_file backend\tests\test_plugin_store.py::test_plugin_artifact_cleanup_deletes_expired_file_and_audits -q --basetemp=.tmp\pytest-plugin-artifact-short-temp`: passed, 5 passed.
- `npm.cmd run validate:module-participation`: passed; final run included SignalOps 2 passed, MFE/MAE Quant Core 4 passed, closed-loop 1 passed, worker 15 passed plus CLI smoke, and module suite 192 passed.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\phase1-3-validation.ps1 -SkipBuild -SkipBrowserSmoke`: passed; verified the phase gate calls module participation before frontend typecheck, lint, and static smoke.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-module-participation-hygiene-final`: passed, 18 passed.
- `python -m json.tool package.json > $null`: passed.
- `git diff --check -- backend\app\core\plugin_store.py scripts\module-participation-validation.ps1 scripts\smoke-analysis-worker.ps1 scripts\phase1-3-validation.ps1 scripts\smoke-frontend-routes.ps1 backend\tests\test_repo_hygiene.py package.json docs\DEVELOPMENT_GUIDE.md docs\TESTING_GUIDE.md docs\NEXT_DEVELOPMENT_PLAN.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low targeted runtime fix plus validation wiring. Plugin artifact uploads still store review-only packages, do not extract or execute code, and remain governed by checksum, local metadata scan, optional external scan, retention, and admin controls. The new module gate uses isolated pytest/`.tmp` paths and does not change API contracts, auth, production data, order routing, or SignalOps `simulation_only=true` / `is_real_trade=false` boundaries.

## 2026-06-04 - Added Phase 1-3 validation gate

Type: stage acceptance gate / browser closure smoke / documentation

Scope: make the Phase 1-3 acceptance path executable as one root command instead of a manually assembled checklist. The gate covers baseline audit, isolated closed-loop participation, local SQLite worker stability, frontend checks, static route smoke, and the temporary-DB Research closure browser smoke.

Changes:
- Added `scripts/phase1-3-validation.ps1` and `npm.cmd run validate:phase1-3`.
- The phase gate prints `git status --short`, runs `audit:baseline`, `smoke:closed-loop-participation`, `smoke:analysis-worker`, `typecheck`, `lint`, `build`, `smoke:frontend`, and `smoke:research-closure:browser` by default.
- Added `-SkipBuild` and `-SkipBrowserSmoke` only for focused local iteration.
- Updated the development guide, testing guide, and Phase 1-3 plan to point broad stage acceptance at `validate:phase1-3`.
- Added repo hygiene and static frontend smoke guards so the phase gate cannot silently drop the browser closure or worker acceptance pieces.

Validation:
- `npm.cmd run validate:phase1-3`: passed.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-phase1-3-validation-hygiene`: passed, 16 passed.
- `python -m json.tool package.json > $null`: passed.
- `git diff --check -- scripts\phase1-3-validation.ps1 scripts\smoke-frontend-routes.ps1 backend\tests\test_repo_hygiene.py package.json docs\DEVELOPMENT_GUIDE.md docs\TESTING_GUIDE.md docs\NEXT_DEVELOPMENT_PLAN.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low validation/documentation change. The new gate does not change runtime behavior, API contracts, auth, production data, or SignalOps simulation-only boundaries. It is intentionally heavier than pre-merge and uses existing isolated smoke paths; Research closure browser smoke writes to `.tmp` temporary SQLite and cleans its own spawned processes.

## 2026-06-04 - Added analysis worker smoke to pre-merge gate

Type: Phase 3 validation gate / worker stability / documentation

Scope: make the local SQLite analysis worker acceptance path explicit and default-gated. Phase 3 requires worker mode queueing, claim, heartbeat, cancel, stale/reconciliation, and API/job attempt visibility while keeping the normal execution path in-process by default.

Changes:
- Added `scripts/smoke-analysis-worker.ps1` and `npm.cmd run smoke:analysis-worker`.
- The smoke runs focused worker tests for worker-mode queueing, worker execution, heartbeat updates, running cancel propagation, late-completion cancellation safety, concurrency claim limits, owner-guarded heartbeat/terminal writes, stale reconciliation, and job attempt history.
- The smoke also launches `worker:analysis -- -Once` with `.tmp\analysis-worker-cli-smoke\analysis-worker.db` and `.tmp\analysis-worker-cli-smoke\analysis_jobs.json`, proving the CLI path without reading or writing the local runtime job mirror.
- Added `smoke:analysis-worker` to the default pre-merge validation gate with `-SkipAnalysisWorkerSmoke` available only for narrow local iteration.
- Updated testing/development/Phase 1-3 plan docs and repo/static smoke guards so the worker smoke cannot silently disappear.

Validation:
- `npm.cmd run smoke:analysis-worker`: passed, 15 focused worker tests passed and the isolated worker CLI exited cleanly with no claimed job.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-analysis-worker-smoke-hygiene`: passed, 15 passed.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pre-merge-validation.ps1 -SkipBackend -SkipStrictAuthMatrix -SkipBuild`: passed; verified closed-loop participation smoke, analysis worker smoke, frontend typecheck, lint, and static frontend smoke.
- `python -m json.tool package.json > $null`: passed.

Risk:
- Low validation/documentation change. Default runtime execution remains in-process unless `ANALYSIS_EXECUTION_MODE=worker` is set. The worker smoke uses pytest temporary directories plus `.tmp\analysis-worker-cli-smoke` and does not mutate `storage\tianyuan_quant.db` or weaken SignalOps simulation-only/no-real-trade boundaries.

## 2026-06-04 - Expanded default backend module participation regression

Type: validation gate / module participation / review follow-up

Scope: continue the review-guide hardening work by making the default `npm.cmd run test:backend` suite cover more high-risk module participation surfaces, instead of leaving SignalOps routes, Backtest, Research artifact/verdict, Portfolio store, Plugin runtime/store, and analysis job persistence/reconciliation as opt-in checks.

Changes:
- Added Portfolio store, SignalOps routes, Backtest engine/sample/store, Research artifact/verdict stores, Plugin store/runtime, and analysis job SQLite/reconciliation tests to `scripts/test-backend.ps1`'s default test list.
- Added repo hygiene coverage so the high-risk default backend suite cannot silently drop these module participation tests.
- Updated the testing guide's default backend suite list to match the script.
- Added a follow-up note to the code review fix guide so the old T1 default-suite finding points to the current 472-test default gate.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_signalops_routes.py backend\tests\test_backtest_engine.py backend\tests\test_backtest_signalops_sample.py backend\tests\test_backtest_store.py backend\tests\test_research_artifact_store.py backend\tests\test_research_verdict_store.py backend\tests\test_portfolio_store.py backend\tests\test_plugin_runtime.py backend\tests\test_plugin_store.py backend\tests\test_analysis_job_sqlite.py backend\tests\test_analysis_job_reconciliation.py -q --basetemp=.tmp\pytest-module-participation-candidates`: passed, 141 passed.
- `npm.cmd run test:backend`: passed, 472 passed.

Risk:
- Low validation-script/documentation change. No runtime code, API contracts, auth behavior, production data, or SignalOps simulation boundaries changed. The tradeoff is a longer default backend regression, but it now better matches the review requirement that every high-risk module can participate in the validated workflow.

## 2026-06-04 - Wired closed-loop participation into pre-merge gate

Type: validation gate / stability smoke / documentation

Scope: make the compressed development guide operational by ensuring the isolated closed-loop participation smoke is part of the default local pre-merge gate, not just a manual follow-up command.

Changes:
- Added `smoke:closed-loop-participation` to `scripts/pre-merge-validation.ps1` as a default step after the backend regression gate.
- Added `-SkipClosedLoopParticipation` for narrow local iteration while keeping the broad acceptance path strict by default.
- Extended static frontend smoke and repo hygiene guards so the default pre-merge gate cannot silently drop the closed-loop participation smoke.
- Updated the development and testing guides to describe `validate:premerge` as the default gate and the standalone closed-loop smoke as a focused diagnostic command.

Validation:
- `npm.cmd run smoke:closed-loop-participation`: passed.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-premerge-closed-loop-gate`: passed, 13 passed.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\pre-merge-validation.ps1 -SkipBackend -SkipStrictAuthMatrix -SkipBuild`: passed; verified the new closed-loop participation smoke step, frontend typecheck, lint, and static frontend smoke.

Risk:
- Low validation/documentation change. Runtime code, API contracts, auth behavior, production data, and SignalOps `simulation_only=true` / `is_real_trade=false` boundaries are unchanged. The new default step uses pytest's isolated database.

## 2026-06-04 - Added isolated closed-loop participation smoke

Type: stability smoke / persistence coverage / documentation

Scope: prove the full local closed-loop participation path in an isolated pytest database after `audit:baseline` started reporting missing current-run evidence such as `knowledge_patches=0`. The goal is to verify code capability without inserting synthetic rows into `storage/tianyuan_quant.db`.

Changes:
- Added `npm.cmd run smoke:closed-loop-participation`.
- Extended the P2 closed-loop route test so it checks actual table persistence for Analysis, Agent result, Portfolio, SignalOps signal, paper order, Backtest, Research loop/iteration/evidence, Case, Knowledge patch/version, Evaluation, and analysis job rows.
- Added a SignalOps `SIM_BUY` paper-order step to the same isolated participation smoke while preserving `simulation_only=true` and `is_real_trade=false`.
- Documented that current-run `closure_gaps` should be investigated with this isolated smoke before anyone writes synthetic rows into the live local database.

Validation:
- `npm.cmd run smoke:closed-loop-participation`: passed.
- `npm.cmd run test:backend -- backend\tests\test_closed_loop_sample.py -q --basetemp=.tmp\pytest-closed-loop-sample-file`: passed, 3 passed.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-closed-loop-participation-hygiene`: passed.
- `python -m json.tool package.json > $null`: passed.
- `git diff --check -- backend\tests\test_closed_loop_sample.py backend\tests\test_repo_hygiene.py package.json docs\DEVELOPMENT_GUIDE.md docs\TESTING_GUIDE.md docs\DEVELOPMENT_LOG.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low test/documentation change. The smoke uses pytest's isolated database and does not mutate the current runtime database. The added paper order is explicitly `SIM_BUY`, `simulation_only=true`, `is_real_trade=false`, and does not create broker connectivity or real order authority.

## 2026-06-04 - Tightened baseline closed-loop participation audit

Type: stability audit / documentation / repo hygiene

Scope: close a review-plan diagnostic gap in `audit:baseline`. The script counted `knowledge_patches`, `agent_results`, `paper_orders`, `research_evidence_links`, and `analysis_jobs`, but did not include all of them in `closure_gaps`, so a module could be absent from the local closed-loop evidence while the baseline still looked complete.

Changes:
- Added `agent_results`, `paper_orders`, `research_evidence_links`, `knowledge_patches`, and `analysis_jobs` to the baseline closed-loop required table list.
- Added `closure_required_tables` to the baseline JSON report so reviewers can see the exact participation gate.
- Updated the testing/storage docs and repo hygiene guard to keep the required participation list from drifting silently.

Validation:
- `npm.cmd run audit:baseline`: passed; the command now emits `closure_required_tables` and truthfully flags the current local `knowledge_patches` table as a closed-loop data gap instead of hiding it.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-baseline-participation`: passed.
- `git diff --check -- scripts\audit-development-baseline.ps1 backend\tests\test_repo_hygiene.py docs\TESTING_GUIDE.md docs\STORAGE_DESIGN.md docs\DEVELOPMENT_LOG.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low diagnostic-only change. It does not write runtime data, mutate the current SQLite database, alter API contracts, change strict auth, or weaken SignalOps `simulation_only=true` / `is_real_trade=false` boundaries. A zero-count required table now appears as a visible baseline gap by design.

## 2026-06-04 - Retired stale audit replay guide

Type: documentation cleanup / repo hygiene

Scope: remove an isolated replay guide that still described the pre-consolidation 15 Agent audit view and direct table-level replay SQL. Current audit review uses the active API, Agent registry, browser pages, strict-auth smoke, and development log evidence instead of this stale standalone document.

Changes:
- Deleted `docs/AUDIT_REPLAY.md`.
- Updated `docs/DEVELOPMENT_GUIDE.md` so the authority map lists the replay guide with other retired development documents.
- Extended repo hygiene coverage so the retired replay guide cannot be recreated silently.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-retire-audit-replay`: passed.
- `git diff --check -- docs\AUDIT_REPLAY.md docs\DEVELOPMENT_GUIDE.md docs\DEVELOPMENT_LOG.md backend\tests\test_repo_hygiene.py`: passed with LF/CRLF working-copy warnings only.
- `rg -n "AUDIT_REPLAY" . --glob '!docs/MODULE_INTERACTION_REVIEW_LOG.md' --glob '!frontend/dist/**' --glob '!node_modules/**' --glob '!backend/app/storage/**'`: active references are limited to the development guide/log/test retirement guard.

Risk:
- Low documentation-only cleanup. Runtime code, API contracts, strict auth, Agent execution, SignalOps `simulation_only=true`, and `is_real_trade=false` behavior remain unchanged.

## 2026-06-04 - Retired stale full-run checklist

Type: documentation cleanup / repo hygiene

Scope: remove a stale verification path that conflicted with the current development guide. `docs/FULL_RUN_CHECKLIST.md` and the legacy tail of `docs/TESTING_GUIDE.md` still referenced direct `pytest tests/ -v`, `/analyze`, 15 Agent rows, and old table-level checks instead of the current root `npm.cmd` scripts, 10 Agent registry, Phase 1-3 closure checks, and strict-auth browser smoke.

Changes:
- Deleted `docs/FULL_RUN_CHECKLIST.md`.
- Replaced the legacy manual checklist tail in `docs/TESTING_GUIDE.md` with a short retired-checklist note and current command entry points.
- Updated `docs/DEVELOPMENT_GUIDE.md` to state that both old checklist/backlog docs are retired.
- Added repo hygiene coverage so the stale checklist, direct `pytest tests/ -v`, `/analyze` checklist text, and `15 个 Agent` checklist wording cannot be reintroduced silently.

Validation:
- `npm.cmd run worker:analysis -- -Once -WorkerId codex-nojob-smoke -DatabaseFile .tmp\worker-cli-smoke.db -JobStorageFile .tmp\worker-cli-smoke\analysis_jobs.json`: passed; the isolated worker CLI returned `claimed=False` without reading the local runtime job mirror.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-retire-full-run-checklist-rerun`: passed, 10 passed.
- `git diff --check -- docs\FULL_RUN_CHECKLIST.md docs\TESTING_GUIDE.md docs\DEVELOPMENT_GUIDE.md docs\DEVELOPMENT_LOG.md backend\tests\test_repo_hygiene.py`: passed with LF/CRLF working-copy warnings only.
- `rg -n "pytest tests/ -v|15 个 Agent|/analyze 成功后写入|FULL_RUN_CHECKLIST.md" docs\TESTING_GUIDE.md`: no hits.

Risk:
- Low documentation-only cleanup. Runtime code, strict auth, worker mode, Agent registry, simulation-only SignalOps boundaries, `simulation_only=true`, and `is_real_trade=false` behavior remain unchanged.

## 2026-06-04 - Knowledge Versions rollback admin role-boundary visibility

Type: frontend role-boundary consistency / static smoke / docs

Scope: close a high-risk UI consistency gap in Knowledge Versions. Draft creation and regression reruns already exposed `researcher+` evidence, but rollback is an admin-only operation and needs its own browser-visible role and disabled-reason hooks.

Changes:
- Added `knowledge-version-rollback-role` and `knowledge-version-rollback-disabled-reason` to `/research-lab/versions`.
- Added stable `knowledge-version-rollback-*` hooks to rollback buttons.
- Routed blocked rollback attempts through the shared admin disabled reason.
- Added static `smoke:frontend` guards for the rollback role hook, disabled reason, button hook, and admin short-circuit.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed, including `/research-lab/versions` and Knowledge Versions static rollback/admin-role guards.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-knowledge-version-rollback-role-docs`: passed, 9 passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed on rerun. An earlier platform smoke invocation exited 1 without frontend/backend error output; backend logs showed SQLite mirror lock fallback warnings only, and the standalone rerun passed.

Risk:
- Low frontend-only consistency change. Backend strict auth, Knowledge rollback behavior, regression governance, audited waiver metadata, `simulation_only=true`, and `is_real_trade=false` behavior remain unchanged.

## 2026-06-04 - Plugin Registry lifecycle admin role-boundary visibility

Type: frontend role-boundary consistency / static smoke / docs

Scope: close a high-risk UI consistency gap in Plugin Registry. Runtime validation and sandbox checks already exposed `operator+` role evidence, but lifecycle and artifact actions also need explicit admin role evidence and handler-level short-circuits.

Changes:
- Added `plugin-lifecycle-action-role` and `plugin-lifecycle-action-disabled-reason` to `/plugins`.
- Added a shared admin disabled reason to toggle, archive, upgrade, artifact upload, artifact checksum, and artifact cleanup controls.
- Added handler-level `canTogglePlugins` short-circuits before toggle, archive, upgrade, artifact upload, and cleanup actions.
- Added static `smoke:frontend` guards for the lifecycle role hook, disabled reason, and admin short-circuit.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed, including `/plugins` and Plugin Registry static lifecycle/admin-role guards.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-plugin-lifecycle-role-docs`: passed, 9 passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed.

Risk:
- Low frontend-only consistency change. Backend strict auth, plugin audit/lifecycle/artifact APIs, sandbox policy, artifact governance, read-only/no-code defaults, `simulation_only=true`, and `is_real_trade=false` behavior remain unchanged.

## 2026-06-04 - Config Versions approved restore role-boundary visibility

Type: frontend role-boundary consistency / static smoke / docs

Scope: close another review-document high-risk UI consistency gap. Config Versions approved restore already required admin role and backend strict auth, but the page did not show the same browser-visible role and disabled-reason evidence used by other high-risk surfaces.

Changes:
- Added `config-approved-restore-role` and `config-approved-restore-disabled-reason` to `/config-versions`.
- Added the admin disabled reason as the approved restore opener title for non-admin roles.
- Kept the governed restore modal submit button disabled if the current role is not admin, covering role changes after a modal is open.
- Added static `smoke:frontend` guards for the role hook, disabled reason, title wiring, and admin-only restore contract.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed, including `/config-versions` and the Config Versions static role/restore guards.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-config-versions-role-docs`: passed, 9 passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed.

Risk:
- Low frontend-only consistency change. Backend strict auth and `/api/config/external-restore` approval/secret-safe checks remain authoritative. No config restore executor behavior, secret handling, plugin policy, SignalOps automation, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-04 - Development guide current-state compression follow-up

Type: documentation cleanup / guide compression

Scope: optimize `docs/DEVELOPMENT_GUIDE.md` after recent completed work so the guide stays a current engineering contract instead of a second development-history ledger. This is documentation-only and does not change runtime behavior.

Changes:
- Updated the guide date to 2026-06-04 and clarified that completed work is stored in `DEVELOPMENT_LOG.md`, while the guide keeps only current facts, boundaries, entries, and check matrices.
- Renamed the architecture section to a current system snapshot and compressed completed startup/dashboard details into stable contracts.
- Clarified that `NEXT_DEVELOPMENT_PLAN.md` phases should not reopen already verified log items as backlog.
- Compressed the Research Lab/Backtest section around current evidence and role-boundary rules instead of repeating completed implementation detail.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-development-guide-current-compression`: passed, 9 passed.
- `git diff --check -- docs\DEVELOPMENT_GUIDE.md docs\DEVELOPMENT_LOG.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low documentation-only compression. No code, API, auth, plugin policy, SignalOps automation, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-04 - Research Lab secondary closed-loop write-role consistency

Type: frontend role-boundary consistency / static smoke / docs

Scope: close a remaining review-document UI consistency gap: the main Research Lab write actions already used the shared `researcher+` guard, but the P2 closed-loop guide's secondary controls should also show the same disabled reason and avoid letting viewer-role sessions toggle write options. This is frontend UX consistency only and does not change backend Research APIs, strict auth, evidence semantics, or simulation/live-trading boundaries.

Changes:
- Passed the shared Research Lab write disabled reason into `ClosedLoopWizardPanel`.
- Added `research-closed-loop-secondary-disabled-reason` so the secondary guide area shows the same viewer/researcher boundary as the main Research Lab toolbar.
- Disabled the secondary closed-loop option checkboxes while writes are blocked/busy and added title text to secondary create/materialize actions.
- Added `research-materialize-current-artifacts` plus static `smoke:frontend` guards for the secondary disabled-reason and title wiring.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed, including `/research-lab/research` and the Research Lab workflow static guard.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-research-secondary-role-docs`: passed, 9 passed.
- `git diff --check -- frontend\src\components\research\ResearchLoopsPage.tsx scripts\smoke-frontend-routes.ps1 docs\DEVELOPMENT_LOG.md docs\TESTING_GUIDE.md docs\PROJECT_DEVELOPMENT_ASSESSMENT.md docs\QUANT_SYSTEM_IMPROVEMENT_PLAN.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low frontend-only consistency change. Handler-level `ensureResearchLabWrite()` already blocked unauthorized writes; this pass makes the secondary controls visibly consistent and easier to smoke-guard. No backend schema, Research artifact generation, SignalOps, Backtest, order routing, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-04 - Dashboard decision workbench, fast-ready startup, and SignalOps history compression

Type: dashboard read model / startup responsiveness / SignalOps history hygiene / frontend contract / docs

Scope: continue the review-document stabilization work by making the Dashboard decision surface explicit, keeping backend readiness responsive when market-data status is slow, and compressing auto-generated SignalOps/sample history out of user-facing selectors. This preserves the local research/simulation boundary and does not add broker execution or real-trade authority.

Changes:
- Added a read-only `analysis_dashboard_summary_v1` projection to analysis detail responses, including decision state, evidence score, source counts, agent counts, blockers, warnings, next-review guidance, and `tradeBoundary.simulationOnly=true` / `isRealTrade=false`.
- Added a Dashboard decision workbench that consumes the backend summary with a frontend fallback, renders stable `dashboard-decision-workbench`, `dashboard-trade-boundary`, and `dashboard-evidence-spine` hooks, and keeps QIAM and Bottom Research evidence visible without hover-only dependence.
- Kept `/analysis/runs` on the summary-index fast path and limited stale-run reconciliation for detail reads to the requested run, avoiding full-history recovery during normal Dashboard hydration.
- Changed optional startup warmers so local warmers run concurrently and market-data status finishes in a deferred optional task; failures/timeouts degrade `market_data_status` without revoking the READY phase.
- Added a shared `visibleRunHistory()` helper so `P2_CLOSED_LOOP_SAMPLE` rows stay hidden from normal history selectors while preserving the active/deep-linked run id in Dashboard, Live Run, and Data Compression flows.
- Split SignalOps lifecycle signals from auto-paper generated signals, added a compact `自动模拟记录` section, recovered configured symbol pools from retained `signal_ids`, and triggers a first simulated tick after adding a new symbol when the operator role permits.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py backend\tests\test_main_lifespan.py backend\tests\test_auto_paper_trading.py -q --basetemp=.tmp\pytest-dashboard-startup-signalops-rerun`: passed, 107 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed, including Dashboard workbench, run-history filtering, backend health/store, and `/signalops` static guards.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.

Risk:
- Moderate surface-area, bounded behavior change. Analysis detail now returns an additive `dashboardSummary`; existing clients should ignore unknown fields, and the backend does not persist the projection into run storage. Startup READY can appear before deferred market-data status finishes, so operators must read degraded components for market-data diagnostics. SignalOps history compression hides generated sample rows from normal selectors but preserves active/deep-linked ids and keeps auto-paper records visible in their own section. No order routing, live broker path, plugin authority, backend strict auth, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-03 - Development guide completed-content compression

Type: documentation cleanup / current guide compression

Scope: optimize `docs/DEVELOPMENT_GUIDE.md` so already-completed architecture, page, route, Agent, and MFE/MAE development details are summarized as current facts instead of repeated as long implementation history. Keep current engineering boundaries, startup/testing entries, module rules, and modification matrix intact.

Changes:
- Updated the guide date to 2026-06-03 and clarified that completed development details should be read from `DEVELOPMENT_LOG.md`.
- Added `npm.cmd run validate:premerge` to the common checks list.
- Compressed the backend/frontend/Agent architecture section into current-state bullets with legacy redirect and readiness constraints.
- Merged the product-chain and follow-up-order sections into a shorter evidence-first workflow summary.
- Compressed MFE/MAE Path Research details into supporting-only guardrails while preserving QIAM, market-profile, and no-trade-action boundaries.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-development-guide-compression`: passed, 9 passed.
- `git diff --check -- docs\DEVELOPMENT_GUIDE.md docs\DEVELOPMENT_LOG.md`: passed with LF/CRLF working-copy warnings only.

Risk:
- Low documentation-only compression. Detailed completed-development history is intentionally not duplicated in the guide; it remains available in `docs/DEVELOPMENT_LOG.md` and git history. No code, API, runtime behavior, auth, plugin policy, SignalOps automation, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-03 - Ready redaction and Plugin sandbox operator authority

Type: backend readiness secrecy / Plugin Registry actor authority / frontend contract / docs

Scope: close two review-document stability gaps without changing product behavior: `/api/ready` should not expose local database or storage filesystem paths, and Plugin sandbox/preview execution should not trust a client-supplied actor/operator value. This preserves plugin sandbox policy, backend strict auth, read-only plugin execution boundaries, and simulation/live-trading policy.

Changes:
- Removed local `databasePath` and per-storage `path` fields from `/api/ready` dependency checks.
- Replaced readiness dependency exception text with bounded generic messages plus `errorType`, so local filesystem details are not returned to browser/API callers.
- Changed `run_plugin_sandbox()` and `execute_plugin_preview()` to derive audit actor identity from `current_operator()` instead of request payload fields.
- Removed the optional frontend `actor` payload from `runPluginSandbox()` and the Plugin Registry dry-run caller.
- Added backend regressions proving ready output omits local paths and Plugin sandbox/preview audit actors ignore forged client actor/operator values.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_observability_routes.py -q --basetemp=.tmp\pytest-ready-redaction-current`: passed, 18 passed.
- `npm.cmd run test:backend -- backend\tests\test_plugin_runtime.py -q --basetemp=.tmp\pytest-plugin-actor-current`: passed, 13 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/plugins`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.

Risk:
- Low scoped hardening. Operators lose exact local ready-response paths in the API, but those paths remain discoverable from deployment config and local logs. Plugin sandbox audit attribution is now stricter; any caller that previously relied on spoofing actor text must use the authenticated/current operator context instead. No plugin code-execution permission, order routing, SignalOps automation, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-03 - Remove obsolete open development backlog document

Type: documentation cleanup / stale plan removal

Scope: delete the obsolete `docs/OPEN_DEVELOPMENT_BACKLOG.md` file and update active developer-facing docs so current planning no longer links to the removed backlog. Preserve current planning authority in `DEVELOPMENT_GUIDE.md`, `PROJECT_DEVELOPMENT_ASSESSMENT.md`, `QUANT_SYSTEM_IMPROVEMENT_PLAN.md`, `TESTING_GUIDE.md`, and this log.

Changes:
- Deleted `docs/OPEN_DEVELOPMENT_BACKLOG.md`, which had already marked all N1-N6 items `Verified Done` and was repeatedly documented as not a current plan source.
- Removed active links/references that told developers to consult the old backlog as an archive.
- Updated encoding and testing guidance to point closure evidence at `DEVELOPMENT_LOG.md` instead of the deleted file.

Validation:
- `rg -n "OPEN_DEVELOPMENT_BACKLOG" README.md docs backend frontend scripts --glob '!docs/DEVELOPMENT_LOG.md' --glob '!docs/MODULE_INTERACTION_REVIEW_LOG.md'`: passed; active docs only state that the file was removed and no longer link to it.
- `npm.cmd run test:backend -- backend\tests\test_repo_hygiene.py -q --basetemp=.tmp\pytest-delete-outdated-docs`: passed, 9 passed.

Risk:
- Low documentation cleanup. Historical references inside `DEVELOPMENT_LOG.md` and generated review logs remain as immutable evidence, but active developer-facing docs no longer route users to the deleted backlog.

## 2026-06-03 - Runtime store replace retry and deep-link hydration recovery

Type: backend persistence stability / frontend deep-link recovery / strict-auth browser validation

Scope: harden local Agent Runtime JSON persistence and browser deep-link run hydration after review-followup validation exposed transient Windows replace locks and stale DAG run recovery. Preserve backend strict auth, Agent Runtime governance, simulation-only boundaries, and existing run/debate/DAG data contracts.

Changes:
- Added unique temp filenames plus bounded `PermissionError` retry around Agent Runtime state replacement.
- Added bounded `PermissionError` retry and temp cleanup around runtime secret vault replacement.
- Added focused backend regressions for transient replace failures and temp-file cleanup.
- Changed `useCurrentRunHydration()` from permanent attempted-key suppression to in-flight-only suppression, so a missed/failed deep-link `run_id` load can retry instead of leaving the page on a stale run.
- Stabilized strict-auth browser navigation/fallback coverage for SignalOps Research evidence, DAG/debate linked-run recovery, portfolio/live/final flows, and plugin registry prerequisite navigation without reloading tab-scoped auth state.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q --basetemp=.tmp\pytest-agent-runtime-save-retry`: passed, 57 passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed.
- `npm.cmd run smoke:strict-auth-browser:signalops`: passed.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: passed, including Agent DAG failure/degraded fixture, state matrix fixture, restored DAG evidence, and Agent Debate evidence.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including multi-broker Portfolio import, New Task portfolio context, Live Run stream token, Final Writer chain, Audit Log, terminal stream fixture, Plugin usage/artifact/cleanup/archive coverage.
- `git diff --check`: passed with only Git line-ending conversion warnings.
- `npm.cmd run validate:premerge`: passed.

Risk:
- Low scoped stability hardening. The replace retry only handles transient local file locks and still fails after the bounded retry window; it does not change persisted schema or secret redaction. The hydration change allows retry after missed deep-link loads while still suppressing duplicate in-flight requests. No order routing, SignalOps action boundary, `simulation_only=true`, or `is_real_trade=false` behavior changed.

## 2026-06-03 - Backend Status export handoff role evidence

Type: frontend Backend Status RBAC visibility / static frontend smoke / docs

Scope: add browser-visible admin role evidence to Backend Status production-alert dispatch/handoff and ops-log handoff controls. Preserve sanitized GET export/query reads, backend strict auth, handoff bundle contracts, deployment sidecar custody, and production-health/read-only diagnostics.

Changes:
- Added stable role and disabled-reason hooks for production-alert admin actions and ops-log handoff.
- Added disabled-reason titles to production-alert dispatch/handoff and ops-log handoff buttons.
- Extended `smoke:frontend` markers so Backend Status keeps admin handoff/dispatch evidence without blocking sanitized export reads.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/backend`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against the built `/backend` page: passed; viewer role rendered blocked production-alert dispatch/handoff and ops-log handoff evidence, disabled the admin-only dispatch/handoff buttons with matching titles, and kept sanitized alert export, ops export, and ops query controls enabled.

Risk:
- Low additive frontend role evidence. Admin users keep the existing dispatch/handoff behavior; non-admin sessions get clearer blocked-state evidence before backend admin-only handoff or dispatch requests. Sanitized export/query reads, backend strict auth, alert/ops bundle schemas, sidecar custody reporting, and production diagnostics remain unchanged.

## 2026-06-03 - SignalOps visible role evidence

Type: frontend SignalOps RBAC visibility / static frontend smoke / docs

Scope: align the high-risk `/signalops` automation surface with visible role evidence for lifecycle writes, manual controls, runtime config writes, and signed review-event export verification/handoff. Preserve existing researcher/operator/admin thresholds, backend strict auth, signed export/handoff behavior, simulation-only status, and disabled live-trading boundaries.

Changes:
- Added stable role and disabled-reason hooks to the SignalOps review-event export panel and operator policy panel.
- Kept lifecycle writes behind `researcher+`, manual controls plus review-event verify/handoff behind `operator+`, and runtime config changes behind `admin`.
- Extended `smoke:frontend` markers so SignalOps role thresholds, handler-level short-circuits, disabled controls, and review-event export operator binding cannot regress silently.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/signalops`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against the built `/signalops` page: passed; viewer role rendered `role: viewer; review export: blocked`, disabled signed export verify/handoff, rendered lifecycle/manual/config blocked role evidence and disabled reasons in the boundary window, and kept forced tick/daily review disabled.

Risk:
- Low additive frontend role evidence. Valid researcher/operator/admin actions keep their existing role thresholds; viewer sessions get clearer blocked-state evidence before browser requests. Backend auth, review gates, export signatures, handoff custody contract, automation mode, order routing, and real-trade disabled boundary remain unchanged.

## 2026-06-03 - Settings data-source role guards

Type: frontend Settings RBAC visibility / static frontend smoke / docs

Scope: align the `/settings` data-source and market-data adapter controls with visible role evidence. Data-source token edits, source enable toggles, data-source config save, and adapter config save require `admin`; explicit data-source tests, adapter health checks, and live-check adapter refresh require `operator+`. Preserve Settings read paths, adapter partial-load handling, Agent Runtime behavior, backend auth, data-source route semantics, and no-direct-trade boundaries.

Changes:
- Added `useOperatorContext()` and role evidence hooks for Settings config writes and active data checks.
- Added handler-level short-circuits before `putDataSourcesConfig()`, `testDataSourceConnection()`, `postAdapterHealth()`, live-check adapter refresh, and `putMarketDataAdapterConfig()`.
- Disabled token input, source test/toggle controls, data-source config save, adapter refresh/check, adapter config inputs, and adapter config save for insufficient roles with stable test ids.
- Extended `smoke:frontend` markers so Settings data-source and adapter actions keep visible role-aware guards alongside the existing partial-load adapter coverage.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5198/settings`: passed; viewer role rendered config/check blocked states, disabled token/save/source test/source toggle/adapter refresh/adapter check/adapter config input/save controls, and sent no non-GET API calls during page load.
- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q --basetemp=.tmp\pytest-settings-role-guards`: passed, 55 passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/settings`.

Risk:
- Low additive frontend role guard. Valid admin config edits and operator/admin active checks remain available by role; viewer/researcher sessions stop before data-source config, adapter config, and live-check requests. Backend strict auth, token redaction, config snapshot/restore behavior, adapter execution, market-data routing, and no-direct-trade boundaries remain unchanged.

## 2026-06-03 - Agent Runtime visible admin role evidence

Type: frontend Agent Runtime RBAC visibility / static frontend smoke / docs

Scope: align the `/settings` Agent Runtime panel with visible admin-only evidence for runtime writes, profile saves, validation/live tests, market-data profile changes, and routing changes. Preserve existing admin-only behavior; no backend auth, runtime payload, model routing, market-data routing, or no-direct-trade boundary changes.

Changes:
- Added stable `agent-runtime-write-role` and `agent-runtime-write-disabled-reason` hooks to the mounted Agent Runtime section.
- Added stable test ids to LLM profile save/apply/validate/test, market-data profile save/test, runtime routing save, and apply-default-to-all controls.
- Extended `smoke:frontend` markers so Agent Runtime write controls keep visible admin role evidence, handler-level `guardRuntimeWrite()` short-circuits, and disabled write controls.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q --basetemp=.tmp\pytest-agent-runtime-role-evidence`: passed, 55 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/settings`.
- Playwright DOM verification against `http://127.0.0.1:5197/settings`: passed; viewer role rendered `role: viewer; runtime writes: blocked`, the disabled reason, disabled profile save/apply/validate/test controls, disabled market-data save/test controls, disabled runtime-route save/apply controls, readable LLM and market Base URL security evidence, and no non-GET API calls during page load.

Risk:
- Low additive frontend role evidence. Valid admin Agent Runtime writes remain available; non-admin sessions remain blocked before profile, runtime routing, validation, or live-test requests. Backend strict auth, runtime config validation, egress policy, Agent routing, market-data status, and no-direct-trade boundaries remain unchanged.

## 2026-06-03 - Technical Kline visible role evidence

Type: frontend Technical Kline RBAC visibility / static frontend smoke / docs

Scope: align the actual `/quant-core` Technical Kline case-governance card and the legacy `TechnicalKlinePage` source guard with visible role evidence for case recording and governance writes. Preserve admin-only governance save/rollback and researcher+ case sedimentation; no backend policy, order routing, or simulation/live-trading boundary changes.

Changes:
- Added stable role and disabled-reason hooks to the active `TechnicalKlineCaseGovernanceCard` rendered by `/quant-core`, while keeping case-impact, representative-case, parameter-review, and long-window regression evidence readable.
- Added visible role/disabled hooks and stable write button test ids to the legacy `TechnicalKlinePage` source guard for governance save/rollback and current-case recording.
- Extended `smoke:frontend` markers so both the active `/quant-core` card and legacy page source keep role checks, handler-level short-circuits, and disabled write controls.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_technical_kline_agent.py -q --basetemp=.tmp\pytest-technical-kline-role-evidence`: passed, 14 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/quant-core`.
- Playwright DOM verification against `http://127.0.0.1:5196/quant-core?run_id=RUN_TK_ROLE_001`: passed; viewer role rendered `case record: blocked`, the disabled reason, disabled record-case control with matching title, and still-rendered case-impact, representative-case, parameter-version, and long-window regression evidence.

Risk:
- Low additive frontend role evidence. Valid researcher/operator/admin Technical Kline case recording remains available by role; viewer sessions stop before case recording requests. Governance save/rollback remains admin-only in the legacy page source. Backend strict auth, Technical Kline governance policy, Case Library linkage, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Plugin Registry operator runtime-check guard

Type: frontend Plugin Registry RBAC / static frontend smoke / docs

Scope: align `/plugins` manifest validation and runtime sandbox-run actions with the shared operator browser boundary. Plugin lifecycle toggles, archive, package upload, artifact cleanup, and upgrade remain admin-only. This is a frontend operator-role UX guard only; it does not change backend strict auth, plugin validation semantics, sandbox policy, artifact storage, audit persistence, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'operator')` before `validatePlugin()` or `runPluginSandbox()` can be triggered from the Plugin Registry page.
- Disabled `plugin-validate-action` and per-agent `plugin-sandbox-run-*` controls for non-`operator+` roles, surfaced stable `plugin-runtime-action-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept lifecycle, archive, upgrade, artifact upload, and cleanup controls behind the existing `admin` boundary while extending `smoke:frontend` markers so runtime-check actions cannot regress to role-unaware browser requests.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_plugin_store.py backend\tests\test_plugin_runtime.py -q --basetemp=.tmp\pytest-plugin-runtime-role-guard`: passed, 31 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/plugins`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:4177/plugins`: passed; viewer role rendered `runtime checks: blocked`, the disabled reason, disabled validate/sandbox-run controls with matching titles, and still rendered plugin resource summary, usage summary/history, package artifact state, and audit evidence.

Risk:
- Low additive frontend role guard. Valid operator/admin plugin validation and sandbox-run checks remain available by role; viewer/researcher sessions stop before runtime validation or sandbox-run requests. Backend plugin validation, sandbox policy, artifact governance, audit persistence, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Knowledge Versions researcher write guard

Type: frontend Knowledge Versions RBAC / static frontend smoke / docs

Scope: align `/research-lab/versions` manual draft snapshot creation and post-publish regression reruns with the shared researcher browser write boundary. Rollback remains admin-only. This is a frontend operator-role UX guard only; it does not change backend strict auth, regression semantics, rollback execution, promotion policy, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` before `createKnowledgeVersion()` or `rerunKnowledgeVersionRegression()` can be triggered from the Knowledge Versions page.
- Disabled `knowledge-version-create-draft` and per-version `knowledge-version-rerun-regression-*` controls for non-`researcher+` roles, surfaced stable `knowledge-version-write-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept `rollbackKnowledgeVersion()` behind the existing `admin` boundary while extending `smoke:frontend` markers so Knowledge version write actions cannot regress to role-unaware browser requests.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_evaluation.py -q --basetemp=.tmp\pytest-knowledge-versions-role-guard`: passed, 22 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/research-lab/versions`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:4177/research-lab/versions`: passed; viewer role rendered `write versions: blocked`, `rollback: blocked`, the disabled reason, disabled create/rerun controls with matching titles, and still rendered post-publish regression summary, impact, quality, and policy evidence.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin Knowledge version create/rerun actions remain available by role; viewer sessions stop before draft snapshot creation or post-publish regression reruns. Rollback remains admin-only. Backend regression calculation, promotion governance, rollback semantics, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Evaluation Sandbox researcher run guard

Type: frontend Evaluation Sandbox RBAC / static frontend smoke / docs

Scope: align `/research-lab/evaluation` forced patch evaluation and strategy A/B experiment actions with the shared researcher browser write boundary. This is a frontend operator-role UX guard only; it does not change backend strict auth, evaluation scoring, strategy experiment reports, promotion gates, audited waiver policy, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` before `runPatchEvaluation()` or `runPatchStrategyExperiment()` can be triggered from the Evaluation Sandbox page.
- Disabled per-patch `evaluation-sandbox-run-*` and `evaluation-sandbox-experiment-*` controls for non-`researcher+` roles, surfaced stable `evaluation-sandbox-write-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept patch/evaluation reads, summary metrics, historical evaluation rendering, and experiment report rendering available while extending `smoke:frontend` markers so Evaluation Sandbox actions cannot regress to role-unaware browser runs.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_evaluation.py -q --basetemp=.tmp\pytest-evaluation-sandbox-role-guard`: passed, 22 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/research-lab/evaluation`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:4177/research-lab/evaluation`: passed; viewer role rendered `run sandbox: blocked`, the disabled reason, disabled run/experiment controls with matching titles, and still rendered historical evaluation and experiment report evidence.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin Evaluation Sandbox runs remain available by role; viewer sessions stop before forced patch evaluation or strategy experiment requests. Backend evaluation semantics, promotion governance, audited regression waivers, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Case Library write role guard

Type: frontend Case Library RBAC / static frontend smoke / docs

Scope: align `/case-library` case creation, case review saves, review tagging, and patch review/evaluation/promotion actions with the shared researcher browser write boundary while keeping delete controls admin-only. This is a frontend operator-role UX guard only; it does not change backend strict auth, evaluation gates, audited waiver policy, Knowledge version promotion semantics, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` before `createCase()`, `updateCaseReview()`, `createReviewTag()`, `reviewKnowledgePatch()`, forced patch evaluation, and `approvePatchWithEvaluation()` can be triggered from the Case Library page.
- Disabled `case-library-create-case`, per-case tag/save controls, and per-patch review/evaluation controls for non-`researcher+` roles, surfaced stable `case-library-write-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept existing case/error/patch delete behavior behind the admin guard and extended `smoke:frontend` markers so Case Library writes cannot regress to role-unaware browser actions.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_case_library.py backend\tests\test_evaluation.py -q --basetemp=.tmp\pytest-case-library-write-role-guard`: passed, 38 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/case-library`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:4177/case-library`: passed; viewer role rendered `write: blocked`, the disabled reason, and disabled create/tag/save/evaluation/approve/reject controls with matching titles.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin Case Library writes remain available by role; viewer sessions stop before case, review, tag, patch evaluation, or promotion requests. Backend auth, promotion governance, audited regression waivers, deletion admin checks, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Data Health operator check guard

Type: frontend Data Health RBAC / static frontend smoke / docs

Scope: align `/data-health` explicit adapter and symbol health checks with the shared operator browser control boundary. This is a frontend operator-role UX guard only; it does not change backend strict auth, Data Health snapshot reads, adapter check execution, symbol coverage checks, `DataAdapterEventDB` persistence, external-monitor sidecar ownership, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'operator')` before `checkDataHealthAdapters()` and `checkSymbolHealth()` can be triggered from the Data Health page.
- Disabled `data-health-adapter-check` and `data-health-symbol-check` for non-`operator+` roles, surfaced stable `data-health-check-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept snapshot, freshness, event trail, external-monitor, and matrix reads available, then extended `smoke:frontend` markers so active Data Health checks cannot regress to role-unaware browser actions.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_data_health_routes.py -q --basetemp=.tmp\pytest-data-health-operator-guard`: passed, 10 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/data-health`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5195/data-health`: passed; viewer role rendered `run checks: blocked`, the disabled reason, and disabled adapter/symbol check buttons with matching titles.

Risk:
- Low additive frontend role guard. Valid operator/admin Data Health checks remain available by role; viewer/researcher sessions stop before active adapter or symbol check requests. Backend auth, local event persistence, external-monitor diagnostics, source selection, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Portfolio snapshot write role guard

Type: frontend Portfolio RBAC / static frontend smoke / docs

Scope: align `/portfolio` snapshot creation and file-import writes with the shared researcher browser write boundary while keeping snapshot delete admin-only. This is a frontend operator-role UX guard only; it does not change backend strict auth, broker-template parsing, malformed-file diagnostics, New Task risk preflight, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` before sample snapshot creation, manual snapshot creation, and file-import snapshot writes can call `createManualPortfolioSnapshot()` or `importPortfolioSnapshot()`.
- Disabled `portfolio-create-sample`, `portfolio-create-manual`, and `portfolio-import-submit` for non-`researcher+` roles, surfaced stable `portfolio-write-role` and disabled-reason hooks, and added handler-level short-circuits.
- Kept existing snapshot delete behavior behind the admin guard and extended `smoke:frontend` markers so Portfolio writes cannot regress to role-unaware snapshot creation/import.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py -q --basetemp=.tmp\pytest-portfolio-write-role-guard`: passed, 17 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/portfolio`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5194/portfolio`: passed; viewer role rendered `write snapshots: blocked`, the disabled reason, and disabled sample/manual/import write buttons with matching titles.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin snapshot writes remain available by role, viewer sessions stop before snapshot creation/import requests, and delete remains admin-only. Backend auth, import diagnostics, broker-template metadata, New Task portfolio risk context, and simulation-only boundaries remain unchanged.

## 2026-06-03 - New Task run creation role guard

Type: frontend New Task RBAC / static frontend smoke / docs

Scope: align `/new-task` analysis run creation and start handoff with the shared researcher write boundary. This is a frontend operator-role UX guard only; it does not change backend strict auth, analysis lifecycle services, worker queue semantics, portfolio risk preflight, Live Run stream auth, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` before `createAnalysisRun()` and `startAnalysisRun()` can be triggered from the New Task submit path.
- Disabled `new-task-submit` for non-`researcher+` roles, surfaced stable `new-task-run-role` and disabled-reason hooks, and added a handler-level short-circuit.
- Extended `smoke:frontend` markers so the New Task submit path cannot regress to role-unaware run creation while keeping portfolio/LLM/readiness reads available.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py::test_create_analysis_run_infers_and_accepts_quant_engine_mode backend\tests\test_analysis_workflow.py::test_create_analysis_run_attaches_portfolio_snapshot_with_normalized_symbol_and_audit backend\tests\test_analysis_workflow.py::test_started_run_persists_final_background_state -q --basetemp=.tmp\pytest-new-task-role-guard`: passed, 3 passed after rerunning outside the sandbox because the first sandboxed attempt hit a `.tmp` uv trampoline write permission error.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/new-task`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5193/new-task`: passed; viewer role rendered `create run: blocked`, the disabled reason, and a disabled `new-task-submit` button title.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin run creation remains available by role; viewer sessions stop before analysis run creation/start requests. Backend auth, analysis lifecycle state, worker scheduling, portfolio context propagation, Live Run handoff, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Knowledge iteration write role guard

Type: frontend Knowledge RBAC / static frontend smoke / docs

Scope: align `/knowledge` generation, manual creation, review, and archive actions with the shared Knowledge/Research role boundaries. This is a frontend operator-role UX guard only; it does not change backend Knowledge creation, approval, rejection, archive, active-context semantics, response guards, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` for run-derived Knowledge generation, manual Knowledge item creation, and pending-item approve/reject review actions.
- Added `roleAllows(operator.role, 'admin')` for archive/delete actions that remove active Knowledge items from the default list.
- Surfaced stable `knowledge-write-*` and `knowledge-archive-*` hooks, added handler-level short-circuits, and extended `smoke:frontend` markers for these Knowledge write boundaries.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_knowledge_store.py -q --basetemp=.tmp\pytest-knowledge-role-guard`: passed, 3 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/knowledge`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5192/knowledge` with mocked Knowledge API payloads: passed; viewer role rendered `write: blocked`, `archive: blocked`, both disabled reasons, and disabled generate/create/approve/reject/archive controls.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin Knowledge writes remain available by role, while viewer sessions stop before creation/review calls and non-admin sessions stop before archive calls. Backend Knowledge policy, response validation, active context generation, and simulation-only boundaries remain unchanged.

## 2026-06-03 - Data Compression researcher write guard

Type: frontend Data Compression RBAC / static frontend smoke / docs

Scope: align `/data-compression` compression write-back with the shared Research Lab write boundary. This is a frontend operator-role UX guard only; it does not change backend strict auth, compression summaries, retention policies, Knowledge distillation grouping, data quality scoring, SignalOps, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` to the Data Compression write-back path before `compressRun()` can be called from the browser.
- Disabled the `写回摘要` action for non-`researcher+` roles and surfaced stable `data-compression-write-role` / disabled-reason hooks.
- Added a handler-level short-circuit plus `smoke:frontend` markers so the write-back entry cannot regress to button-state-only eligibility.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_data_pipeline.py -q --basetemp=.tmp\pytest-data-compression-role-guard`: passed, 3 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/data-compression`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- Playwright DOM verification against `http://127.0.0.1:5191/data-compression`: passed; viewer role rendered `role: viewer; write: blocked`, the disabled reason, and a disabled `写回摘要` button title. The in-app Browser plugin was attempted first but failed at Windows sandbox setup, so this used the local Playwright fallback.

Risk:
- Low additive frontend role guard. Valid researcher/operator/admin write-backs are unchanged; viewer-role browser sessions now stop before the compression write API call. Backend auth, evidence-retention semantics, Knowledge distillation, and simulation-only boundaries remain the enforcement layer.

## 2026-06-03 - Backtest research write role guard

Type: frontend Backtest RBAC / static frontend smoke / docs

Scope: align `/research-lab/backtest` research writes and local job controls with the shared operator-role boundaries. This is a frontend operator-role UX guard only; it does not change backend strict auth, Backtest simulation models, parameter-scan scheduling, Research evidence semantics, SignalOps, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'researcher')` for Backtest run creation, parameter scans, async scan job creation, SignalOps sample generation, SignalOps random validation starts, and Backtest -> Research verdict-input evidence creation.
- Added `roleAllows(operator.role, 'operator')` for local Backtest job cancel controls and kept artifact handoff/delete controls behind `admin`.
- Surfaced stable `backtest-*-role` and disabled-reason hooks, added handler-level short-circuits, and extended `smoke:frontend` markers for these Backtest role boundaries.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_backtest_signalops_sample.py backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run -q --basetemp=.tmp\pytest-backtest-role-guard`: passed, 40 passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts`, `/backtest`, and `/research-lab/backtest`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: passed through Backtest sample run, parameter scan, async job, handoff, handoff custody, Research verdict inputs, SignalOps deep link, Agent DAG, and Agent Debate markers.
- `git diff --check -- frontend/src/components/backtest/BacktestPage.tsx scripts/smoke-frontend-routes.ps1 docs/DEVELOPMENT_LOG.md docs/TESTING_GUIDE.md docs/PROJECT_DEVELOPMENT_ASSESSMENT.md docs/MODULE_INTERACTION_REVIEW_LOG.md`: passed with LF/CRLF warnings only.

Risk:
- Low additive frontend role guard. Backend auth and simulation-only Backtest/Research/SignalOps contracts remain the enforcement layer; this closes browser UX paths where research writes and local job controls were enabled by form or job status alone.

## 2026-06-03 - Live Run operator control guard

Type: frontend Live Run RBAC / static frontend smoke / docs

Scope: align `/live` cancel/retry run controls with the existing operator-level runtime control boundary. This is a frontend operator-role UX guard only; it does not change backend strict auth, analysis job lifecycle rules, retry semantics, queue storage, stream auth, SignalOps, order routing, or simulation/live-trading boundaries.

Changes:
- Added `roleAllows(operator.role, 'operator')` to `LiveRunConsole` and split status eligibility from role eligibility for cancel/retry actions.
- Disabled `Cancel Run` and retry controls for non-operator roles, surfaced the current role and disabled reason, and added handler-level short-circuits.
- Added stable `live-run-control-*` and action-button hooks, then extended `smoke:frontend` markers so Live Run controls cannot regress to status-only browser actions.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py::test_cancel_running_worker_run_keeps_request_for_worker backend\tests\test_analysis_workflow.py::test_cancel_created_run_marks_job_and_audit backend\tests\test_analysis_workflow.py::test_retry_failed_run_resets_failed_suffix_and_preserves_prior_nodes backend\tests\test_analysis_workflow.py::test_retry_failed_run_resumes_after_non_executable_plugin_observation -q --basetemp=.tmp\pytest-live-run-control-guard`: passed, 4 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/live-run`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.
- `git diff --check -- frontend/src/components/live/LiveRunConsole.tsx scripts/smoke-frontend-routes.ps1 docs/DEVELOPMENT_LOG.md docs/TESTING_GUIDE.md docs/PROJECT_DEVELOPMENT_ASSESSMENT.md docs/MODULE_INTERACTION_REVIEW_LOG.md`: passed with LF/CRLF warnings only.

Risk:
- Low additive frontend role guard. Backend auth and job lifecycle checks remain the enforcement layer; this closes an inconsistent browser UX path where run cancel/retry controls could be enabled by status alone.

## 2026-06-03 - Backend Tuning admin write guard

Type: frontend Backend Tuning RBAC / static frontend smoke / docs

Scope: align `/tuning` configuration writes with the existing admin-only config surfaces. This is a frontend operator-role UX guard only; it does not change backend auth, config schemas, policy validation, runtime config semantics, Agent Runtime restore, SignalOps, order routing, or simulation/live-trading boundaries.

Changes:
- Added `useOperatorContext()` and `roleAllows(operator.role, 'admin')` to `BackendTuningPage`.
- Disabled `Apply Safe Runtime Config` and `Submit Review Draft` for non-admin roles, surfaced the current role and disabled reason, and added handler-level short-circuits.
- Added stable `backend-tuning-*` hooks and extended `smoke:frontend` markers so `/tuning` config writes cannot regress to ungated browser actions.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_config_routes.py::test_safe_runtime_patch_validates_applies_and_versions backend\tests\test_config_routes.py::test_review_draft_apply_and_rollback_restore_snapshot backend\tests\test_config_routes.py::test_config_versions_filter_by_actor_and_include_secret_safe_policy -q --basetemp=.tmp\pytest-backend-tuning-admin-guard`: passed, 3 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/tuning`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend role guard. Backend auth and policy checks remain the enforcement layer; this closes an inconsistent browser UX path where `/config-versions` and Agent Runtime writes were guarded but `/tuning` writes were not.

## 2026-06-03 - Research trace import role guard

Type: frontend Research Lab trace import RBAC / static frontend smoke / docs

Scope: align `/research-lab/traces` import writes with the existing Research Lab workflow write boundary. This is a frontend operator-role UX guard only; it does not change backend auth, trace import payloads, trace budget enforcement, Research storage, Backtest, SignalOps, knowledge promotion, order routing, or simulation/live-trading boundaries.

Changes:
- Added `useOperatorContext()` and `roleAllows(operator.role, 'researcher')` to `ResearchTracesPage`.
- Disabled the trace import action for `viewer`, surfaced the current role and disabled reason, and added a handler-level short-circuit to prevent bypassing the disabled button.
- Added stable `research-trace-import-*` hooks and extended `smoke:frontend` markers so the role boundary and JSON object guard cannot regress silently.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_research_store.py::test_rd_agent_trace_preview_and_import_are_review_only backend\tests\test_research_store.py::test_rd_agent_trace_import_route_returns_400_for_budget_overflow -q --basetemp=.tmp\pytest-research-trace-import-role-guard`: passed, 2 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/research-lab/traces`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend role guard. Backend strict auth remains the enforcement layer; this prevents inconsistent browser UX where Research Lab workflow writes are gated but trace import writes are not.

## 2026-06-03 - Research trace import JSON object guard

Type: frontend Research Lab trace import / static frontend smoke / docs

Scope: harden `/research-lab/traces` before a pasted RD-Agent trace is posted to `/research/traces/import`. This is frontend input validation only; it does not change backend trace budget enforcement, Research storage, Backtest, SignalOps, knowledge promotion, order routing, or simulation/live-trading boundaries.

Changes:
- Added `parseTraceJsonObject()` so pasted trace JSON is parsed as `unknown` and must be a non-array top-level object before import.
- Normalized a blank source field back to `rd-agent` before posting the import request.
- Extended `smoke:frontend` markers so Research Trace import cannot regress to a direct `JSON.parse(traceText) as Record<string, unknown>` cast.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_research_store.py::test_rd_agent_trace_preview_and_import_are_review_only backend\tests\test_research_store.py::test_rd_agent_trace_import_route_returns_400_for_budget_overflow -q --basetemp=.tmp\pytest-research-trace-import-input-guard`: passed, 2 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/research-lab/traces`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid RD-Agent trace objects are unchanged; arrays, nulls, and scalar JSON now fail as controlled import-form errors before the API call. Backend budget and review-only import policy remain the enforcement layer.

## 2026-06-03 - Global Market row-level response guards

Type: frontend Global Market API client / static frontend smoke / docs

Scope: harden `/global-market` before it stores and renders `/market-data/global?range=4m` payloads. This is frontend response validation only; it does not change backend market fetching, provider arbitration, fallback normalization, cache policy, order routing, or simulation/live-trading boundaries.

Changes:
- Added row-level guards for index K-line rows and latest quote objects, requiring finite OHLC values before chart and moving-average calculations.
- Added row-level guards for fund-flow rows and sector-rank rows so malformed numeric fields cannot enter chart bars, rankings, or percent/money formatters.
- Added source-chain, conflict, arbitration, data-quality, and temperature field checks while preserving the existing guarded normalization fallback for missing optional containers.
- Extended `smoke:frontend` markers so Global Market row/source/conflict/arbitration checks cannot regress to object-only validation.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_global_market_service.py -q --basetemp=.tmp\pytest-global-market-row-contract`: passed, 27 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/global-market`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid Global Market payloads are unchanged; malformed rows now fail as controlled client contract errors before page state mutation. This does not alter upstream provider behavior, fallback selection, SignalOps inputs, order routing, or real-trade boundaries.

## 2026-06-03 - Agent Runtime base URL security evidence

Type: backend Agent Runtime public profile contract / frontend Agent Runtime evidence panel / static frontend smoke / docs

Scope: expose the existing server LLM and Market Data egress-policy decision on public runtime profiles so Agent Runtime can show whether each `base_url` is blocked, trusted by official host, trusted by allowlist, local, missing, or custom. This is visibility and contract hardening only; it does not relax strict-mode allowlists, add a client-side bypass, change secret storage, alter runtime writes, route orders, or change simulation/live-trading boundaries.

Changes:
- Added `RuntimeBaseUrlSecurity` to public LLM and Market Data profile models with status, allow/blocked flag, strict-mode flag, policy code, host, reason, configured allowlist hosts, and optional approval metadata.
- Mapped the existing `validate_llm_egress()` and `validate_market_data_egress()` decisions into `base_url_security` when runtime profiles are returned.
- Extended `agentRuntimeClient` type/guard coverage for `base_url_security.code`, `host`, and `reason`.
- Added an Agent Runtime page evidence block showing server egress status and configured allowlist hosts for selected LLM and Market Data profiles.
- Extended `smoke:frontend` markers so the response guard and page evidence block cannot be removed silently.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py::test_runtime_profiles_expose_base_url_security -q --basetemp=.tmp\pytest-runtime-base-url-security`: passed, 1 passed.
- `npm.cmd run test:backend -- backend\tests\test_agent_runtime.py -q --basetemp=.tmp\pytest-agent-runtime-base-url-security-full`: passed, 55 passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and all route checks.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed; two leftover port-88 strict-auth uvicorn processes were found by exact current-repo match and stopped, then the match returned empty.

Risk:
- Low additive contract/UI evidence change. Valid runtime profile responses now include extra public policy metadata; existing strict-mode decisions are unchanged and key material remains redacted. The UI is diagnostic only and cannot approve custom egress. Future work remains for broader production operations items such as external queues and centralized vendor-grade logging.

## 2026-06-03 - Live Run SSE stream message guard

Type: frontend Live Run stream client / static frontend smoke / strict-auth browser smoke / docs

Scope: guard the non-REST EventSource message boundary before Live Run consumes `/analysis/runs/{runId}/stream` events. This is frontend stream-message validation only; it does not change backend stream generation, EventSource auth, retry timing, run execution, final writer, plugin execution, order routing, or simulation/live-trading boundaries.

Changes:
- Added `assertStreamMessage()` to validate parsed SSE payloads before `connectRunStream()` calls Live Run handlers.
- Required `event_type` to be a non-empty string and validated optional string fields (`run_id`, `node_id`, `message`, `audit_id`, `timestamp`) when present while leaving `payload` unmodified.
- Changed EventSource parsing from direct `JSON.parse(event.data) as StreamMessage` trust to `JSON.parse(event.data) as unknown` followed by the stream guard.
- Extended `smoke:frontend` markers so stream parsing cannot regress to an unguarded cast while preserving query-token EventSource support.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/live-run`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed with the Portfolio/New Task/Live Run/EventSource/Final Writer/Plugin chain.

Risk:
- Low additive frontend validation. Valid stream messages are unchanged; malformed SSE payloads are discarded before Live Run state mutation. This does not alter retry behavior, terminal event handling, backend run state, report generation, plugin execution, auth policy, order routing, or real-trade boundaries.

## 2026-06-03 - Ops alert/log request unknown boundary

Type: frontend Backend Status ops alert/log API client / strict-auth browser smoke / static frontend smoke / docs

Scope: tighten Backend Status production-alert and ops-log response exits so status, query, export, handoff, and dispatch payloads are consumed only after runtime assertions. This is frontend boundary validation and smoke determinism only; it does not change backend observability generation, alert dispatch policy, log retention, handoff custody, auth policy, order routing, or simulation/live-trading boundaries.

Changes:
- Added runtime guards for production alert events/status/export/handoff/dispatch and ops log events/status/query/export/handoff payloads.
- Changed production alert and ops log client helpers from typed `request<T>()` to `request<unknown>()` before guard wiring.
- Kept empty production-alert `last_event_at` compatible with the backend's valid no-alert state and made legacy alert event `external_delivery` optional while still validating it when present.
- Isolated `PRODUCTION_ALERT_OUTBOX_FILE` in `smoke:strict-auth-browser` so the platform smoke reads a per-run temporary outbox instead of default local storage.
- Extended `smoke:frontend` weak-link checks so alert/log status, export, handoff, dispatch, and query exits cannot regress to compile-time-only generic trust.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1` and `scripts\smoke-strict-auth-browser.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_observability_routes.py -q --basetemp=.tmp\pytest-ops-alert-log-client-guards`: passed with `17 passed`.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/backend`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed after the alert outbox isolation and empty `last_event_at` compatibility fix.

Risk:
- Low additive frontend validation. Valid backend alert/log responses are unchanged; malformed payloads now fail before Backend Status page state consumes them. The production alert no-event state remains renderable as export-ready, and strict-auth smoke no longer depends on default local alert storage. This does not change observability event generation, alert delivery, log export custody, auth, order routing, or real-trade boundaries.

## 2026-06-03 - Analysis lifecycle/job/node/report request unknown boundary

Type: frontend analysis API client / Backend Status job queue / New Task / Live Run / Final Writer / static frontend smoke / strict-auth browser smoke / docs

Scope: tighten the remaining analysis lifecycle, job queue, node, debate, final-report, and delete response exits so New Task, Live Run, Backend Status, Final Writer, HistorySelector, Agent DAG/Debate helpers, and report list consumers receive those payloads only after runtime assertions. This is frontend boundary validation and smoke diagnostics only; it does not change backend analysis scheduling, worker mode, report generation, audit storage, plugin execution, order routing, or simulation/live-trading policy.

Changes:
- Added runtime guards for create/start/retry/cancel analysis responses, analysis jobs, analysis job summaries, agent nodes, debate artifacts, token usage summaries, final report assets/lists, and delete acknowledgements.
- Changed analysis lifecycle/job/node/report/debate/delete calls from typed `request<T>()` to `request<unknown>()` before guard wiring.
- Updated `smoke:frontend` weak-link checks so the analysis job queue, lifecycle, node, debate, report, and delete exits cannot silently regress to compile-time-only generic trust.
- Improved `smoke:strict-auth-browser:portfolio-live-plugin` failure diagnostics for Live Run exact-route rendering by reporting the current rendered run id, toast text, and page summary on the second timeout.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_analysis_workflow.py backend\tests\test_analysis_job_sqlite.py backend\tests\test_final_writer.py backend\tests\test_final_report_store.py -q --basetemp=.tmp\pytest-analysis-client-lifecycle-guards`: passed with `71 passed`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts`, `/backend`, `/new-task`, `/live-run`, `/final`, `/dag`, and `/debate` routes.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: first retry exposed a Live Run exact-route timeout while old strict-auth uvicorn processes were still holding SQLite/storage locks; after cleaning those stale `start_uvicorn.py` processes, rerun passed with portfolio import, New Task portfolio preflight, live-run stream token, live-run task panels, final report chain, Audit Log, terminal stream, and Plugin Registry markers.

Risk:
- Low additive frontend validation. Valid backend analysis lifecycle, job, node, debate, report, and delete responses are unchanged; malformed payloads now fail before page or store state consumes them. The only smoke-script behavior change is extra timeout diagnostics. This does not change analysis execution, worker scheduling, report generation, audit persistence, plugin behavior, order routing, or real-trade boundaries.

## 2026-06-03 - Backend health/startup/metrics request unknown boundary

Type: frontend Backend Status / Dashboard health API client / backend store wiring / static frontend smoke / docs

Scope: tighten the shared health/readiness/metrics response boundary so TopBar, HistorySelector, Backend Status, and Dashboard consume `/health`, `/startup/status`, and `/metrics.productionHealth` only after runtime assertions. This is frontend boundary validation only; it does not change backend health generation, startup warmup, production-health aggregation, auth, alerting, order routing, or simulation/live-trading policy.

Changes:
- Added runtime guards for `BackendHealth`, `StartupStatus`, startup component rows, `BackendMetrics`, production-health windows, metrics, alerts, and trend payloads.
- Changed `getBackendHealth()`, `getStartupStatus()`, and `getBackendMetrics()` from typed `request<T>()` calls to `request<unknown>()` before guard wiring.
- Kept `useBackendStore`'s existing 3-second startup-status probe but routed it through the shared guarded `getStartupStatus({ timeoutMs: 3000 })` helper instead of direct `request<StartupStatus>()`.
- Extended `smoke:frontend` static checks so health/startup/metrics calls and backend-store wiring cannot silently regress to compile-time-only generic trust.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run test:backend -- backend\tests\test_observability_routes.py -q --basetemp=.tmp\pytest-backend-health-metrics-client-guards`: passed with `17 passed`.
- `npm.cmd run smoke:frontend`: passed before and after `build` with `ok frontend weak-link contracts`, `/backend`, and Dashboard routes.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed after extending the production-health metric guard for `staleJobs.runIds` / `windowCount` compatibility.

Risk:
- Low additive frontend validation. Valid backend health/startup/metrics responses are unchanged; malformed readiness or production-health payloads now fail before global store, Backend Status, or Dashboard state consume them. This does not change startup warmup, production-health calculation, alert dispatch, order routing, or real-trade boundaries.

## 2026-06-03 - SignalOps lifecycle/paper request unknown boundary

Type: frontend SignalOps API client / static frontend smoke / SignalOps lifecycle regression / docs

Scope: finish the non-auto-paper `signalopsClient` response-boundary gap so `/signalops` and Case Library consumers receive signal lifecycle, selected-signal detail, paper portfolio/order/position, and simulation-case payloads only after runtime assertions. This is frontend boundary validation only; it does not change backend SignalOps lifecycle gates, paper-order execution rules, auto-paper automation, Research evidence bridge, order routing, or simulation/live-trading policy.

Changes:
- Added runtime guards for SignalOps signal rows, transition rows, review rows, selected-signal detail, paper portfolios, paper positions, paper orders, and agent simulation cases.
- Changed non-auto-paper SignalOps endpoint calls from `request<Signal...>()` / `request<Paper...>()` to `request<unknown>()` before their guards run.
- Required paper portfolio, paper order, and simulation-case responses to keep `simulation_only=true` and `is_real_trade=false` before page state can use them.
- Extended `smoke:frontend` static checks so the SignalOps lifecycle/paper endpoint calls stay on `request<unknown>()` with guard `.then(...)` wiring.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/signalops`.
- `npm.cmd run test:backend -- backend\tests\test_signalops_routes.py backend\tests\test_signalops_lifecycle_store.py -q --basetemp=.tmp\pytest-signalops-lifecycle-client-guards`: passed with `12 passed`.
- `npm.cmd run smoke:signalops-auto-paper-chain`: passed with `2 passed`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:signalops`: passed with config/status boundary, boundary window, forced tick, daily review, manual command, candidate baseline review, review approval/rejection, review-decision export handoff custody, review decisions, and Research evidence markers.

Risk:
- Low additive frontend validation. Valid backend SignalOps lifecycle and paper responses are unchanged; malformed signal rows, paper portfolio/order/case payloads, or real-trade-looking paper responses now fail before `/signalops` or Case Library state consumes them. This does not enable live trading, change lifecycle gates, change paper-order fill rules, alter auto-paper decisions, route real orders, or change simulation/live-trading boundaries.

## 2026-06-03 - Backtest summary/delete request unknown boundary

Type: frontend Backtest API client / static frontend smoke / Backtest focused regression / strict-auth research-backtest browser smoke / docs

Scope: finish the remaining `backtestClient` response-boundary gap so `/research-lab/backtest` consumes summary counters and delete acknowledgements only after runtime assertions. This is frontend boundary validation only; it does not change backend Backtest execution, retained history, delete authorization, Research verdict-input linkage, SignalOps, order routing, or simulation/live-trading policy.

Changes:
- Added runtime guards for `getBacktestSummary()` and `deleteBacktestRun()`: summary responses must keep finite `total_runs`, `completed_runs`, and `pending_runs` counters; delete responses must include a string `deleted` id.
- Changed the summary and delete calls from `request<BacktestSummary>()` / `request<{ deleted: string }>()` to `request<unknown>()` before their guards run.
- Extended `smoke:frontend` static checks and Backtest guard documentation so the summary/delete exits cannot silently regress to compile-time-only type trust.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_backtest_signalops_sample.py -q --basetemp=.tmp\pytest-backtest-summary-delete-guards`: passed with `39 passed` after rerunning outside the sandbox because the sandboxed uv trampoline hit Windows PE resource write denial.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts`, `/backtest`, and `/research-lab/backtest`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: first run passed all Backtest, Research verdict, and SignalOps deep-link markers, then timed out on the later Agent DAG page wait; rerun passed fully with Backtest experiment package, sample run, parameter-scan validation protocol, async job, handoff, handoff custody, Research closed-loop sample, Research Backtest verdict inputs, Research SignalOps selected deep link, Agent DAG, and Agent Debate markers.

Risk:
- Low additive frontend validation. Valid backend Backtest summary/delete responses are unchanged; malformed counters or delete acknowledgements now fail before page state refresh. This does not change Backtest execution, retained history, delete permissions, Research evidence, order routing, or real-trade boundaries.

## 2026-06-03 - Backtest request unknown boundary

Type: frontend Backtest API client / static frontend smoke / Backtest focused regression / strict-auth research-backtest browser smoke / docs

Scope: tighten the existing `backtestClient` response guards so `/research-lab/backtest` consumes created runs, parameter scans, retained scan history, async jobs, handoff manifests, SignalOps sample/experiment responses, random-validation jobs, selected runs, trades, signals, and experiment packages only after runtime assertions. This is frontend boundary validation only; it does not change backend Backtest execution, parameter-scan persistence, handoff storage, Research verdict-input linkage, SignalOps, order routing, or simulation/live-trading policy.

Changes:
- Changed guarded Backtest endpoint calls from `request<Backtest...>()` to `request<unknown>()` before the existing `assertBacktest...` / SignalOps Backtest guards run.
- Kept the established simulation-boundary validation unchanged: parameter scans and experiment packages must keep `simulation_only=true` / `is_real_trade=false`, async jobs and handoffs must keep `simulationOnly=true` / `isRealTrade=false`, and append-only handoff manifests remain required.
- Extended `smoke:frontend` static checks so guarded Backtest endpoint calls stay on `request<unknown>()` and cannot silently regress to compile-time-only type trust.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run test:backend -- backend\tests\test_backtest_store.py backend\tests\test_backtest_signalops_sample.py -q --basetemp=.tmp\pytest-backtest-request-unknown`: passed with `39 passed`.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts`, `/backtest`, and `/research-lab/backtest`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: passed with Backtest experiment package, sample run, parameter-scan validation protocol, async job, handoff, handoff custody, Research closed-loop sample, Research Backtest verdict inputs, Research SignalOps selected deep link, Agent DAG, and Agent Debate markers.

Risk:
- Low additive frontend validation. Valid backend Backtest responses are unchanged; malformed or real-trade-looking payloads now enter the same runtime guards from an `unknown` request boundary. This does not change Backtest execution, retained history, async job recovery, handoff custody, Research verdict evidence, order routing, or real-trade boundaries.

## 2026-06-03 - SignalOps auto-paper request unknown boundary

Type: frontend SignalOps auto-paper API client / static frontend smoke / SignalOps smoke / strict-auth SignalOps browser smoke / docs

Scope: tighten the existing `signalopsClient` auto-paper response guards so `/signalops` consumes compact config/status, config updates, forced ticks, daily reviews, manual commands, review decisions, review-decision event exports, verification, and handoff payloads only after runtime boundary assertions. This is frontend boundary validation only; it does not change backend SignalOps automation, deterministic module evidence, review queue persistence, event export/handoff storage, order routing, or simulation/live-trading policy.

Changes:
- Changed guarded SignalOps auto-paper and review-decision event endpoint calls from `request<AutoPaper...>()` to `request<unknown>()` before the existing `assertAutoPaper...` / event-export guards run.
- Changed the auto-paper guard entrypoints to accept `unknown`, assert object shape first, and then return the established response types.
- Kept the existing simulation/live-disabled validation unchanged: automation must remain simulation-first, live module must remain disabled, order router must remain `DISABLED`, and real-trade-looking payloads remain rejected.
- Extended `smoke:frontend` static checks so SignalOps auto-paper endpoint calls stay on `request<unknown>()` and cannot silently regress to compile-time-only type trust.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:signalops-auto-paper-chain`: passed with `2 passed`.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/signalops`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:signalops`: passed, including config/status boundary, boundary window, forced tick, daily review, manual command, candidate baseline review, review approval/rejection, export handoff custody, review decisions, and Research evidence markers.

Risk:
- Low additive frontend validation. Valid backend SignalOps auto-paper responses are unchanged; malformed or real-trade-looking payloads now enter the same runtime guards from an `unknown` request boundary. This does not enable live trading, change deterministic module evidence, alter review decisions, write orders outside the `SIM_*` namespace, or change real-trade boundaries.

## 2026-06-03 - Technical Kline request unknown boundary

Type: frontend Technical Kline API client / static frontend smoke / focused backend route tests / docs

Scope: tighten the existing `technicalKlineClient` response guards so `/technical-kline` and `/quant-core` consume analysis, signal-backtest, prompt, governance read/write/rollback, and case-record payloads only after runtime assertions. This is frontend boundary validation only; it does not change backend Technical Kline analysis, saved governance, Case Library sedimentation, SignalOps, order routing, or simulation/live-trading policy.

Changes:
- Changed Technical Kline guarded endpoint calls from `request<Technical...>()` to `request<unknown>()` before the existing `assertTechnical...` guards run.
- Kept the established no-trade and review-only validation unchanged: prompt/governance/backtest payloads still require `NO_DIRECT_TRADE_ACTION`, and review payloads still require `REVIEW_ONLY_NO_TRADE_ACTION` where applicable.
- Extended `smoke:frontend` static checks so Technical Kline endpoint calls stay on `request<unknown>()` and cannot silently regress to compile-time-only type trust.

Validation:
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run test:backend -- backend\tests\test_technical_kline_agent.py -q --basetemp=.tmp\pytest-technical-kline-request-unknown`: passed with `14 passed`.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts`, `/technical-kline`, and `/quant-core`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.

Risk:
- Low additive frontend validation. Valid backend Technical Kline responses are unchanged; malformed or trade-action-looking payloads now enter the same runtime guards from an `unknown` request boundary. This does not change governance persistence, reviewed-case sedimentation, SignalOps decisions, order routing, or real-trade boundaries.

## 2026-06-03 - Data Health request unknown boundary

Type: frontend Data Health API client / static frontend smoke / focused backend route tests / docs

Scope: tighten the existing `dataHealthClient` response guards so `/data-health` consumes snapshot, summary, adapter list/check, matrix, symbol-check, history, and event payloads only after runtime assertions. This is frontend boundary validation only; it does not change backend Data Health routes, adapter checks, event persistence, external-monitor sidecar ownership, order routing, or simulation/live-trading policy.

Changes:
- Changed Data Health client calls from `request<DataHealth...>()` to `request<unknown>()` before the existing `assertDataHealth...` guards run.
- Kept the existing summary, adapter, matrix, config, history, event, external-monitor, and symbol-check validation behavior unchanged for valid responses.
- Extended `smoke:frontend` static checks so the Data Health endpoint calls stay on `request<unknown>()` and cannot silently regress to compile-time-only type trust.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run test:backend -- backend\tests\test_data_health_routes.py -q --basetemp=.tmp\pytest-data-health-request-unknown`: passed with `10 passed`.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/data-health`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend Data Health responses are unchanged; malformed payloads now enter the same runtime guards from an `unknown` boundary rather than a pre-trusted generic type. This does not trigger adapter checks, mutate `DataAdapterEventDB`, change external-monitor deployment ownership, route orders, or change real-trade boundaries.

## 2026-06-03 - Global Market frontend response boundary

Type: frontend Global Market API client / static frontend smoke / docs

Scope: harden `globalMarketClient` before `/global-market` consumes `/market-data/global?range=4m` overview payloads for index cards, fund-flow context, sector ranking, market temperature, source chains, and arbitration/conflict display. This is frontend boundary validation only; it does not change backend global-market fetching, provider arbitration, fallback normalization, order routing, or simulation/live-trading policy.

Changes:
- Added `globalMarketClient` response guards for the overview root object, top-level metadata fields, index arrays, fund-flow/sector/temperature containers, nested row/source/conflict arrays, and temperature reason strings.
- Wired `getGlobalMarketOverview()` through `request<unknown>(...)` and `assertGlobalMarketOverviewPayload()` before the existing normalization path stores data in page state.
- Extended `smoke:frontend` static checks so Global Market guard names, container validation, string-array validation, endpoint path, and guarded normalization wiring cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/global-market`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend Global Market responses still flow through the existing normalizer unchanged; malformed root/container payloads now fail as controlled client contract errors before the Global Market page stores them. This does not change source selection, market-data fallback policy, arbitration semantics, order routing, or real-trade boundaries.

## 2026-06-03 - Audit Log frontend response guards

Type: frontend Audit Log API client / static frontend smoke / docs

Scope: harden `auditClient` before `/audit` consumes `/analysis/runs/{runId}/audit` payloads for filtering, event-type lists, status badges, hash display, and JSON export. This is frontend boundary validation only; it does not change backend audit generation, audit event semantics, run snapshot fallback, auth, export behavior, order routing, or simulation/live-trading policy.

Changes:
- Added `auditClient` response guards for audit event arrays and required event fields: timestamp, run id, node, event type, message, status before/after, input/output hashes, and audit id.
- Wired `getAuditLog()` through `request<unknown>(...).then(assertAuditLogEvents)` before `/audit` page state receives payloads.
- Extended `smoke:frontend` static checks so Audit Log guard names, required event-field validation, `.then(...)` wiring, and `/analysis/runs/${runId}/audit` endpoint path cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/audit`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend Audit Log responses are unchanged; malformed audit payloads now fail as controlled client contract errors before the Audit Log page stores them, while the page can still fall back to the current run snapshot. This does not change audit creation, auth, exported JSON shape for valid events, order routing, or real-trade boundaries.

## 2026-06-03 - K-line frontend response guards

Type: frontend K-line market-data API client / static frontend smoke / docs

Scope: harden `klineClient` before Dashboard K-line cards and `/market` route consumers accept `/market-data/kline` payloads. This is frontend boundary validation only; it does not change backend K-line fetching, cache policy, market-data adapter execution, SignalOps K-line quality gates, order routing, or simulation/live-trading policy.

Changes:
- Added `klineClient` response guards for K-line period/range/status/dataMode enums, source metadata, fetched timestamp, record counts, optional last trade date, K-line row arrays, required OHLC fields, and optional numeric volume/amount/change fields.
- Wired `getKline()` through `request<unknown>(...).then(assertKlineResponse)` before K-line chart state receives payloads.
- Extended `smoke:frontend` static checks so K-line guard names, row validation, enum checks, `.then(...)` wiring, and `/market-data/kline` endpoint path cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/market`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend K-line responses are unchanged; malformed K-line payloads now fail as controlled client contract errors before chart state stores them. This does not change K-line source selection, cache behavior, SignalOps K-line blocking logic, order routing, or real-trade boundaries.

## 2026-06-03 - Data Compression frontend response guards

Type: frontend Data Pipeline API client / static frontend smoke / docs

Scope: harden `dataPipelineClient` before `/data-compression` consumes compression overview, run quality, run compression summaries, compression write-back results, and Knowledge distillation groups. This is frontend boundary validation only; it does not change backend compression persistence, retention policy, token-budget estimation, run history, Knowledge distillation semantics, order routing, or simulation/live-trading policy.

Changes:
- Added `dataPipelineClient` response guards for compression overview counters/retention actions, data quality scores, data fingerprints, run compression summaries, optional persisted artifact metadata, and Knowledge distillation groups.
- Wired `getDataPipelineOverview()`, `getRunQuality()`, `getRunCompressionSummary()`, `compressRun()`, and `getKnowledgeDistillationGroups()` through `request<unknown>(...).then(assert...)` before `/data-compression` page state receives payloads.
- Extended `smoke:frontend` static checks so Data Compression guard names, array/category validation, `.then(...)` wiring, and high-risk endpoint paths cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/data-compression`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend Data Pipeline responses are unchanged; malformed overview/quality/summary/distillation payloads now fail as controlled client contract errors before the Data Compression page stores them. This does not rewrite compression artifacts differently, change retention decisions, alter Knowledge distillation policy, route orders, or change real-trade boundaries.

## 2026-06-03 - Knowledge frontend response guards

Type: frontend Knowledge API client / static frontend smoke / docs

Scope: harden `knowledgeClient` before `/knowledge` consumes Knowledge summary, item lists, manual-created items, reviewed items, and run-generated items. This is frontend boundary validation only; it does not change backend Knowledge creation, approval, rejection, archive, run-derived generation, active-context semantics, order routing, or simulation/live-trading policy.

Changes:
- Added `knowledgeClient` response guards for Knowledge summary counters/category counts and Knowledge item identity, status, source refs, evidence, guardrail notes, tags, confidence, timestamps, and review metadata.
- Wired `getKnowledgeSummary()`, `getKnowledgeItems()`, `createKnowledgeItem()`, `reviewKnowledgeItem()`, and `generateKnowledgeFromRun()` through `request<unknown>(...).then(assert...)` before `/knowledge` page state receives payloads.
- Extended `smoke:frontend` static checks so Knowledge guard names, array/category validation, `.then(...)` wiring, and high-risk endpoint paths cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed before and after `build`, including `ok frontend weak-link contracts` and `/knowledge`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.

Risk:
- Low additive frontend validation. Valid backend Knowledge responses are unchanged; malformed summary/item payloads now fail as controlled client contract errors before the Knowledge page stores them. This does not auto-approve Knowledge, bypass review/archive controls, alter active-context policy, route orders, or change real-trade boundaries.

## 2026-06-03 - Settings data-source frontend response guards

Type: frontend Settings data-source config client / static frontend smoke / strict-auth platform browser smoke / docs

Scope: harden the Settings data-source client contract before `/settings` consumes `/agents/data-sources` reads/writes and `/agents/data-sources/{key}/test` results. This is frontend boundary validation only; it does not change backend data-source persistence, Tushare token storage, Agent Runtime audit snapshots, market-data adapter execution, external restore policy, order routing, or simulation/live-trading policy.

Changes:
- Added `configClient` response guards for public data-source config rows, public token-set/mask metadata, and data-source connectivity test results including per-API result rows.
- Wired `getDataSourcesConfig()`, `putDataSourcesConfig()`, and `testDataSourceConnection()` through `request<unknown>(...).then(assert...)` before Settings state receives payloads.
- Extended `smoke:frontend` static checks so Settings data-source guard names, `.then(...)` wiring, and data-source endpoint paths cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed after the build with `ok frontend weak-link contracts` and `/settings`.
- `npm.cmd run smoke:strict-auth-browser:platform`: sequential rerun passed with exit code 0.

Validation notes:
- One browser smoke attempt was started in parallel with `npm.cmd run build` and exited non-zero without useful output while `frontend/dist` was being rewritten. The sequential platform rerun passed, so validation evidence is the sequential run, not the concurrent attempt.

Risk:
- Low additive frontend validation. Valid backend public data-source config and test responses are unchanged; malformed config/test payloads now fail as controlled client contract errors before Settings stores them. This does not expose token material, change Tushare token persistence, relax admin/operator policies, force live data checks by default, route orders, or change real-trade boundaries.

## 2026-06-03 - Case Library frontend response guards and research-backtest smoke stabilization

Type: frontend Case Library API client / static frontend smoke / strict-auth platform and research-backtest browser smoke / docs

Scope: harden `caseLibraryClient` before Case Library, Evaluation Sandbox, Knowledge Versions, Dashboard knowledge regression, and promotion/rollback/delete actions consume case, review-tag, error-ledger, knowledge-patch, evaluation, strategy-experiment, knowledge-version, version-diff, rollback, and delete responses. This is frontend boundary validation plus strict-auth smoke stability hardening only; it does not change backend evaluation scoring, knowledge promotion policy, regression waiver semantics, rollback execution, case persistence, order routing, or simulation/live-trading policy.

Changes:
- Added `caseLibraryClient` response guards for Case Library summaries/items, review tags, error ledger rows, knowledge patches, evaluation runs, strategy experiment reports, knowledge versions, post-publish regression metadata, version diffs, rollback results, and delete responses.
- Wired all Case Library client calls through `request<unknown>(...).then(assert...)` before page consumers receive payloads.
- Extended `smoke:frontend` static checks so Case/Evaluation/Knowledge Version guard names, high-risk endpoint wiring, and `.then(...)` assertions cannot be removed silently.
- Stabilized strict-auth research-backtest smoke by retrying the Backtest selected-run route render when the linked run panel misses its first render window, and by using the existing Bearer API fallback for Agent DAG linked-run response waits.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/case-library`, `/research-lab/evaluation`, `/research-lab/versions`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0, covering Knowledge Versions post-publish regression and Evaluation Sandbox patch evaluation/strategy experiment under strict auth.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: final run passed, covering Backtest experiment package, parameter-scan validation/async handoff/custody, Research closed-loop sample, Research Backtest verdict inputs, Research SignalOps selected deep link, Agent DAG evidence/viewport/node fixtures, and Agent Debate evidence.

Validation notes:
- Two earlier research-backtest runs exposed existing browser timing weak points before/around Agent DAG: one timed out waiting for `backtest-selected-run`, and one timed out waiting for a restored DAG run response after failure/state-matrix fixtures. The smoke now keeps the same visible assertions while adding bounded route/API fallbacks for those timing paths. A final rerun exited 0.

Risk:
- Low additive frontend validation and smoke hardening. Valid backend Case Library/Evaluation/Knowledge Version responses are unchanged; malformed case/tag/error/patch/evaluation/experiment/version/diff/rollback/delete payloads now fail as controlled client contract errors before page state consumes them. This does not auto-approve knowledge patches, bypass regression gates or waivers, perform unattended rollback, route orders, or change real-trade boundaries.

## 2026-06-03 - Agent Runtime frontend response guards

Type: frontend Agent Runtime API client / static frontend smoke / strict-auth browser smoke / docs

Scope: harden `agentRuntimeClient` before Agent Runtime, New Task, Backend Status, Data Engine, and Settings consume runtime config, LLM profile/test results, market-data profile/test results, adapter health/config rows, and market-data status matrix responses. This is frontend boundary validation only; it does not change backend Agent Runtime persistence, secret-vault handling, admin write policy, external restore governance, market-data adapter execution, order routing, or simulation/live-trading policy.

Changes:
- Added `agentRuntimeClient` response guards for Agent Runtime config, LLM profiles, market-data profiles, agent deployments, LLM validation/test results, market-data test results, adapter health rows, adapter config rows, and market-data status matrix.
- Wired Agent Runtime, profile update/test, adapter config/health, and status calls through `request<unknown>(...).then(assert...)` before page consumers receive payloads.
- Added a frontend no-direct-trade guard for runtime agent deployment payloads when `allow_trade_action` or `final_decision_cap` appears in the response.
- Extended `smoke:frontend` static checks so Agent Runtime guard names, `.then(...)` wiring, adapter/status endpoints, and no-direct-trade guard strings cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and Agent Runtime client guard markers.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0, covering Backend Status/Data Health/Settings adapter consumption under strict auth.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including New Task default runtime read, portfolio import, Live Run, Final Writer, Audit Log, Plugin usage history, artifact upload hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- The portfolio-live-plugin run still printed the existing bounded fallbacks for New Task start response wait and Live Run route navigation, then confirmed the same chain through Bearer-auth/API and visible checks.

Risk:
- Low additive frontend validation. Valid backend Agent Runtime responses are unchanged; malformed runtime/profile/test/adapter/status payloads now fail as controlled client contract errors before Agent Runtime, New Task, Backend Status, Data Engine, or Settings state consumes them. This does not expose secrets, relax admin-only Agent Runtime writes, enable external restores, make live market-data calls by default, route orders, or change real-trade boundaries.

## 2026-06-03 - Plugin frontend response guards and strict-auth panel diagnostics

Type: frontend Plugin API client / static frontend smoke / strict-auth plugin browser smoke / docs

Scope: harden the Plugin Registry client contract before `/plugins` consumes registry list, runtime plan, usage stats/history, audit, validate, sandbox, artifact upload, artifact cleanup, enable/disable/upgrade/archive responses. This is frontend boundary validation and smoke stability hardening only; it does not change backend plugin persistence, artifact storage, sandbox execution policy, package scan semantics, archive/upgrade lifecycle, order routing, or simulation/live-trading policy.

Changes:
- Added `pluginClient` response guards for plugin registry rows, runtime plan/nested agent policy, usage stats/history buckets, artifact upload/cleanup results, audit rows, validation results, and sandbox run results.
- Wired all Plugin Registry client calls through `request<unknown>(...).then(assert...)` before page consumers receive payloads.
- Extended `smoke:frontend` static checks so Plugin client guard names and `.then(...)` wiring cannot be removed silently.
- Added strict-auth Plugin page diagnostics for missing summary panels and increased Plugin summary panel waits to 30 seconds while preserving the same visible assertions.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/plugins`.
- `npm.cmd run lint`: passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: final run passed, including malformed import diagnostics, five broker imports, New Task risk preflight, Live Run stream query token/task panels, Final Writer, Audit Log, terminal stream event, Plugin usage history, artifact upload hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- One earlier target browser run exposed a transient Plugin summary-panel wait timeout; a direct backend Plugin response sample matched the new guard contract. The strict-auth smoke now reports page render diagnostics on this failure path and gives the Plugin summary panels 30 seconds to render. A final rerun exited 0.

Risk:
- Low additive frontend validation and smoke hardening. Valid backend Plugin responses are unchanged; malformed plugin/runtime/usage/artifact/audit/validate/sandbox payloads now fail as controlled client contract errors before `/plugins` page state consumes them. This does not enable plugin code execution, import executable artifacts, bypass sandbox policy, route orders, or change real-trade boundaries.

## 2026-06-03 - Portfolio frontend response guards

Type: frontend Portfolio API client / static frontend smoke / strict-auth portfolio browser smoke / docs

Scope: harden the Portfolio frontend contract before `/portfolio`, New Task portfolio context, strict-auth portfolio import, and downstream run creation consume snapshot lists, snapshot details, manual snapshot results, import responses, failed-import job metadata, and delete responses. This is frontend boundary validation only; it does not change backend import parsing, broker templates, malformed-file diagnostics, portfolio persistence, New Task analysis creation, order routing, or simulation/live-trading policy.

Changes:
- Added `portfolioClient` response guards for holding positions, validation issues, snapshot summaries, full snapshots, import responses, import jobs, and delete results.
- Wired `listPortfolioSnapshots()`, `getPortfolioSnapshot()`, `createManualPortfolioSnapshot()`, `importPortfolioSnapshot()`, `getPortfolioImportJob()`, and `deletePortfolioSnapshot()` through explicit assertions before page/store consumers receive the payload.
- Extended `smoke:frontend` static checks so Portfolio import keeps shared `request()`, `FormData`, client response guards, `.then(...)` wiring, malformed-file UI hooks, and strict-auth browser import markers.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/portfolio`.
- `npm.cmd run lint`: passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including malformed import diagnostics, five broker imports, New Task portfolio risk preflight, Live Run stream query token, Final Writer, Audit Log, terminal stream event, Plugin usage history, artifact upload hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- The final strict-auth browser run printed existing bounded fallbacks for the New Task start response wait and Live Run route navigation, then confirmed the same run through Bearer-auth/API and continued to successful visible checks.

Risk:
- Low additive frontend validation. Valid backend Portfolio responses are unchanged; malformed snapshot, import, job, or delete payloads now fail as controlled client contract errors before `/portfolio` or downstream New Task/Live Run state consumes them. This does not connect broker accounts, create snapshots from invalid files, bypass risk gates, route orders, or change real-trade boundaries.

## 2026-06-03 - Config Versions and shared configClient frontend response guards

Type: frontend config API client / Backend Tuning and Settings shared config client / Config Versions / static frontend smoke / strict-auth platform smoke / docs

Scope: harden the shared `configClient` contract before Backend Tuning, Settings, and `/config-versions` accept current profile, schema, policy-check, draft, runtime patch, rollback, version history, rollback policy, approval gate, vault refs, effective scope, or approved restore responses into page/store state. This is frontend boundary validation only; it does not change backend restore execution, Agent Runtime vault handling, RBAC, order routing, or simulation/live-trading policy.

Changes:
- Added shared `configClient` response guards for current config profile, schema items, policy checks, draft creation, draft apply, runtime patch, and rollback responses.
- Added `configClient` response guards for config version history rows, rollback policy, approval gate, `required_secret_refs`, `effective_scope`, and approved external restore responses.
- Wired `getCurrentConfig()`, `getConfigSchema()`, `validateConfigChange()`, `createConfigDraft()`, `applyConfigDraft()`, `patchRuntimeConfig()`, `rollbackConfig()`, `getConfigVersions()`, and `restoreExternalConfig()` through response assertions before their consumers render or store the payload.
- Extended `smoke:frontend` static checks so shared config guard names, `.then(...)` wiring, effective-scope string-array guard, and vault-ref array guard cannot be removed silently.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and `/config-versions`.
- `npm.cmd run lint`: passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0, including the Config Versions approved-restore browser path.

Risk:
- Low additive frontend validation. Valid backend config responses are unchanged; malformed current-profile, schema, policy, draft, runtime patch, rollback, version-history, rollback-policy, approval-gate, vault-ref, scope, or restore-result payloads now fail as controlled client contract errors before Backend Tuning, Settings, or `/config-versions` consume them. This does not enable non-Agent Runtime external restore, unattended rollback, secret snapshot restore, or real trading.

## 2026-06-03 - Technical Kline frontend governance guards and platform smoke stabilization

Type: frontend Technical Kline API client / Backend Status production-health refresh / strict-auth browser smoke / docs

Scope: harden the Technical Kline frontend contract before `/technical-kline` and `/quant-core` accept analysis, prompt, governance, saved case-impact, signal-backtest, and case-record responses; stabilize the strict-auth platform browser scenario so Backend Status, Data Health, Settings, and Technical Kline Case Library fixtures match the current guarded frontend contracts.

Changes:
- Added `technicalKlineClient` response guards for prompt governance, analysis config, case classification, saved governance, case-impact policy, representative case set, parameter-version review, long-window regression, analysis payloads, prompt/governance reads and writes, signal backtest, and case-record responses.
- Enforced the Technical Kline frontend no-trade boundary: governance/prompt/backtest policy must remain `NO_DIRECT_TRADE_ACTION`, while case-impact review gates must remain `REVIEW_ONLY_NO_TRADE_ACTION` and non-blocking.
- Wired Technical Kline reads/writes through the guards before `TechnicalKlineSummaryCard`, `TechnicalKlinePage`, `TechnicalKlineCaseGovernanceCard`, and canonical `/quant-core` page state can consume them.
- Extended `smoke:frontend` static markers for the Technical Kline guard names, `.then(...)` wiring, and review/no-trade boundary constants.
- Made Backend Status apply-token flow refresh production health immediately, and stabilized strict-auth platform smoke with a Bearer-checked `/api/metrics` fixture plus current Data Health and Technical Kline fixture contracts.

Validation:
- `npm.cmd run typecheck`: passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-strict-auth-browser.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed with `ok frontend weak-link contracts` and all expected routes.
- `npm.cmd run test:backend -- backend\tests\test_technical_kline_agent.py -q --basetemp=.tmp\pytest-technical-kline-client-guards`: passed with `14 passed`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-strict-auth-browser.ps1 -Scenario platform`: passed through Backend Status, Dashboard, Data Health, Settings, Technical Kline Case Library, and Config Versions markers.

Risk:
- Low additive frontend validation and smoke stability hardening. Valid backend Technical Kline responses are unchanged; malformed or trade-action-looking payloads now fail as controlled client contract errors before page state updates. Backend Status token-apply refresh is read-only and does not change auth storage, production metrics generation, SignalOps, Backtest, order routing, or simulation/live-trading boundaries.

## 2026-06-03 - Data Health frontend response guards and Research smoke navigation

Type: frontend Data Health API client / strict-auth browser smoke stability / static frontend smoke / docs

Scope: harden the Data Health frontend contract before `/data-health` accepts snapshot, summary, adapter, matrix, history, event, external-monitor, and symbol-check responses, and stabilize the strict-auth Research -> Backtest -> SignalOps browser scenario when returning from `/research-lab/backtest` to `/research-lab/research`.

Changes:
- Added `dataHealthClient` response guards for summary counters, adapter health rows, capability matrix entries, config snapshots, freshness history, adapter events, external-monitor sidecar status, and symbol health result rows.
- Wired every Data Health client read/write response through the guards before page state receives arrays consumed by `.map()`, `.slice()`, `Object.entries()`, freshness/fallback cards, event trails, or external-monitor tiles.
- Added `navigateToResearchLoopsPage()` in the strict-auth browser smoke so Research subroute navigation first uses the visible module link and then falls back to same-origin route load if React Router does not transition from `/research-lab/backtest`.
- Tightened the Research -> SignalOps deep-link assertion to wait on the stable `current-iteration-id` hook for the selected loop instead of a global text search.
- Extended `smoke:frontend` static checks so Data Health response guards and Research navigation smoke hardening remain present.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run test:backend -- backend\tests\test_data_health_routes.py -q --basetemp=.tmp\pytest-data-health-client-guards`: passed with `10 passed`.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: passed after the navigation hardening, including Backtest parameter scan/job/handoff, Research verdict inputs, Research SignalOps selected deep link, Agent DAG, and Agent Debate markers. One earlier concurrent build/smoke attempt failed because `build` rewrote `frontend/dist` while the preview server was reading `index.html`; rerunning sequentially removed that artifact race.

Risk:
- Low additive client-side validation and smoke-only navigation hardening. Valid backend Data Health responses are unchanged. Malformed Data Health payloads now fail as controlled client contract errors before `/data-health` renders them. The browser smoke change does not alter production routing or Research/Backtest/SignalOps APIs.

## 2026-06-03 - Backtest frontend simulation-boundary response guards

Type: frontend Backtest API client / static frontend smoke / strict-auth browser smoke / docs

Scope: harden the Backtest frontend contract before BacktestPage and Research bridge flows accept parameter-scan, async job, handoff, experiment package, SignalOps experiment, random validation, run, signal, and retained scan-history responses. This is client-side validation only; it does not change backend schemas, Backtest execution, Research evidence attachment, SignalOps automation, order routing, or any real-trade policy.

Changes:
- Added Backtest API client guards for snake-case and camel-case simulation boundaries, run parameters, signal metadata, parameter-scan responses, retained scan-history rows, async parameter-scan jobs, append-only handoff manifests, experiment packages, SignalOps experiment responses, and random validation jobs.
- Wired the guards into high-risk Backtest client calls before page state receives responses from run creation/list/detail, trades/signals, parameter scan, async job create/read/cancel/handoff, experiment package download, SignalOps sample/experiment, and random validation job APIs.
- Extended `smoke:frontend` static checks so the Backtest boundary guard names and `.then(...)` wiring must remain present.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed.
- Focused backend Backtest/SignalOps checks passed with `5 passed`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:research-backtest`: passed, including experiment package download, parameter-scan validation protocol, async job, handoff, handoff custody, and Research Backtest verdict-inputs markers.

Risk:
- Low additive client-side validation. Valid backend Pydantic responses already expose these simulation/live-boundary fields or compatible defaults. Malformed or real-trade-looking payloads now fail as controlled client contract errors before `/research-lab/backtest` renders them as active results.

## 2026-06-03 - SignalOps auto-paper frontend boundary guards

Type: frontend SignalOps API client / strict-auth browser fixture / static frontend smoke / docs

Scope: harden the SignalOps auto-paper frontend contract so config/status reads, forced ticks, daily review, manual commands, review decisions, and review-decision event export flows cannot enter page state if the response violates the simulation-only / live-disabled boundary. This is client-side validation only; it does not change backend schemas, order routing, auto-paper execution, review-decision persistence, handoff storage, or any real-trade policy.

Changes:
- Added SignalOps API client guards for `automation_mode`, `automation_modules.active_module`, `real_trade_enabled`, `live_ready`, `live_module.enabled`, `live_module.execution_enabled`, `live_module.order_router`, `simulation_only`, and `is_real_trade`.
- Guarded high-risk write responses from tick, daily review, manual command, and review decision before `SignalOpsPage` stores or renders them.
- Guarded append-only review-decision event export, verification, and handoff responses at the client boundary.
- Aligned the strict-auth SignalOps browser fixture with backend-equivalent auto-paper defaults (`trading_date`, array defaults, `warnings`, and live-module `simulation_only=true`) so the new client guards execute in browser smoke.
- Extended `smoke:frontend` static checks so these guards and their `.then(...)` wiring must remain present.

Validation:
- `npm.cmd run typecheck`: passed after tightening the typed response guard casts.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- Focused backend auto-paper route checks passed with `3 passed`.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/signalops`.
- `npm.cmd run smoke:signalops-auto-paper-chain`: passed with `2 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run smoke:strict-auth-browser:signalops`: first exposed an incomplete daily-review fixture, then passed after aligning the fixture with backend response defaults.

Risk:
- Low additive client-side validation. Valid backend responses already expose the simulation/live-disabled boundary through existing tests. Malformed payloads now fail as controlled client contract errors instead of allowing `/signalops` to render or act on real-trade-looking data.

## 2026-06-03 - Research evidence bridge supporting-only boundary contract

Type: backend Research Lab API contract / frontend Research Lab API client / browser smoke fixture / static frontend smoke / docs

Scope: make the Research -> Backtest and Research -> SignalOps evidence bridge boundary explicit at the response root. The bridge responses still only attach supporting evidence and refresh verdict inputs; they do not accept verdicts, promote knowledge, place orders, or create real-trade authority.

Changes:
- Added root-level `evidence_usage="supporting_only"`, `supporting_only=true`, `simulation_only=true`, and `is_real_trade=false` to `ResearchBacktestVerdictInputsResponse` and `ResearchSignalOpsEvidenceResponse`.
- Tightened `researchClient` with `assertSupportingOnlyResearchBridgeBoundary()` so both bridge responses must expose the top-level boundary before entering frontend state.
- Updated frontend response types for both bridge responses.
- Extended focused backend route tests, strict-auth browser boundary assertions/fixture data, static frontend smoke guards, API contract docs, Testing Guide, and module review log.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_research_store.py::test_backtest_route_creates_research_verdict_inputs_from_run backend\tests\test_research_store.py::test_signalops_route_creates_research_tick_evidence -q --basetemp=.tmp\pytest-research-bridge-boundary`: passed with `2 passed`.
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive API response contract. Existing response fields remain unchanged; clients now get explicit bridge-boundary evidence at the root, and malformed/missing boundary fields fail as controlled client contract errors. This does not change Research storage, verdict scoring, feedback acceptance, knowledge promotion, Backtest execution, SignalOps automation, order routing, or simulation/live-trading boundaries.

## 2026-06-03 - Research draft and iteration module-list contract guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab response-contract recommendation by validating module/evidence string arrays that flow from Research iteration and hypothesis-draft responses into module chips, edit-form joins, draft cards, and apply/confirm actions. This is frontend contract validation only; it does not change backend schemas, Research storage, hypothesis generation, Backtest, SignalOps, order routing, or any simulation/live trading boundary.

Changes:
- Tightened `assertResearchIteration()` to validate `target_modules[]` as strings before `ResearchLoopsPage` calls `.join()` or renders module chips.
- Tightened `assertResearchActionSelection()` to validate `evidence[]` as strings, matching the backend `ResearchActionSelection` contract.
- Tightened `assertResearchHypothesisDraft()` to validate draft `target_modules[]` plus supported `targetModules[]` / `modules[]` aliases as string arrays before render/apply state.
- Extended `smoke:frontend` weak-link checks so these module/evidence list guards must stay wired in `researchClient`.
- Updated Testing Guide and module review log with the tightened draft/iteration list contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Valid backend responses already define these fields as string lists; malformed module/evidence arrays now fail as controlled client contract errors instead of causing render-time module-chip, edit-form join, or draft apply failures.

## 2026-06-03 - Research string-list response contract guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab response-contract recommendation by validating string-list payloads that feed badges, warning rows, toast text, and joined strings. This is frontend contract validation only; it does not change backend schemas, Research storage, Backtest, SignalOps, order routing, or any simulation/live trading boundary.

Changes:
- Tightened `assertResearchLoop()` to validate loop `tags[]` as strings.
- Tightened sample-loop, P2 closed-loop, verdict-input, artifact-materialization, and trace-import response guards for `missing_reasons[]`, `warnings[]`, `blocking_reasons[]`, `quality_warnings[]`, `provenance_chain[]`, and preview `tags[]`.
- Extended `smoke:frontend` weak-link checks so these string-list guards must stay wired in `researchClient`.
- Updated Testing Guide and module review log with the string-list response contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Valid backend responses already expose these list fields through the current contracts or defaults; malformed payloads now fail as controlled client contract errors instead of causing render-time `.join()`, `.map()`, badge, warning, or toast failures.

## 2026-06-03 - Research workflow-step evidence contract guard

Type: frontend Research Lab API client / frontend type contract / static frontend smoke / docs

Scope: continue the Research Lab closed-loop visibility recommendation by making workflow-step evidence metadata a validated frontend contract before the P2 closed-loop wizard renders source, timestamp, strength, missing items, and next-action rows. This is frontend contract validation only; it does not change backend workflow-state generation, maturity scoring, feedback acceptance, Research storage, Backtest, SignalOps, order routing, or any simulation/live trading boundary.

Changes:
- Made `ResearchWorkflowStep.source`, `source_timestamp`, `evidence_strength`, `missing_items`, `next_action`, and `next_action_label` required frontend fields to match the backend Pydantic contract.
- Added `assertStringArray()` and tightened `assertResearchWorkflowStep()` so every workflow step validates evidence metadata and string-only missing-item lists before entering render state.
- Tightened `assertResearchWorkflowState()` to validate `maturity_reasons[]` and `blocking_reasons[]` as string arrays before rendering maturity and blocking chips.
- Extended `smoke:frontend` weak-link checks so workflow-step evidence fields cannot regress to optional-only typing or shallow array checks.
- Updated Testing Guide and module review log with the workflow-step evidence contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Valid backend workflow-state responses already include these fields through `ResearchWorkflowStep` defaults; malformed partial payloads now fail as controlled client contract errors instead of silently hiding workflow evidence metadata.

## 2026-06-03 - Research iteration evidence and feedback item response guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab high-fanout response-guard recommendation by validating persisted `ResearchIteration.evidence_links[]` and `ResearchIteration.feedback_events[]` items before loop/detail, trace, Backtest-evidence, SignalOps-evidence, or feedback responses enter `ResearchLoopsPage` render state. This is frontend contract validation only; it does not change Research storage, feedback persistence, Backtest, SignalOps, run creation, order routing, or any simulation/live trading boundary.

Changes:
- Added `assertResearchEvidenceLink()` for each persisted iteration evidence link, requiring source type/id, label, quality, and created timestamp.
- Added `assertResearchFeedbackEvent()` for each persisted feedback event, requiring event id, action, verdict, note, reviewer, and created timestamp.
- Wired both guards into `assertResearchIteration()` after metrics validation and before the iteration reaches page state.
- Extended `smoke:frontend` weak-link checks so iteration evidence/feedback item guards and `.forEach(...)` calls must stay in place.
- Updated Testing Guide and module review log with the new iteration item contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Backend Research iteration responses already define these item fields through Pydantic defaults; malformed persisted iteration payloads now fail as controlled client errors instead of breaking evidence-link lookup, readiness counters, warning rows, or feedback-history rendering.

## 2026-06-03 - Research verdict inputs item response guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab high-fanout response-guard recommendation by validating verdict-input comparison and evidence rows before `ResearchLoopsPage` renders metric tables or sends verdict evidence back into feedback. This is frontend contract validation only; it does not change Research storage, verdict scoring, feedback persistence, SignalOps, Backtest, run creation, or any simulation/live trading boundary.

Changes:
- Added `assertResearchMetricComparisonRow()` for each `ResearchVerdictInputs.comparison[]` item, requiring a stable `key` plus string label/quality/warning fields.
- Added `assertResearchVerdictEvidence()` for each `ResearchVerdictInputs.evidence[]` item, requiring source type/id, label, quality, summary, metrics object, and created timestamp.
- Wired both guards into `assertResearchVerdictInputs()` before the response reaches render state.
- Extended `smoke:frontend` weak-link checks so verdict comparison/evidence item guards and `.forEach(...)` calls must stay in place.
- Updated Testing Guide and module review log with the new verdict-input item contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Valid backend verdict-input responses already carry these fields through Pydantic defaults; malformed payloads now fail as controlled client errors instead of causing metric-row render or feedback evidence-send failures.

## 2026-06-03 - Research hypothesis draft item response guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab high-fanout response-guard recommendation by validating hypothesis-draft response items before `ResearchLoopsPage` renders draft cards or applies a draft into the iteration form. This is frontend contract validation only; it does not change Research storage, hypothesis generation, LLM execution, run creation, SignalOps, Backtest, or any simulation/live trading boundary.

Changes:
- Added `assertResearchActionSelection()` for `action_selection.target`, `rule_id`, `reason`, numeric `confidence`, and array `evidence`.
- Added `assertResearchHypothesisDraft()` for each draft item's `hypothesis`, `action_target`, `plan`, `rationale`, `source`, `target_modules`, and optional module/evidence arrays.
- Added optional `source` to the frontend `ResearchHypothesisDraft` type so backend `RULE` / `LLM` provenance is represented explicitly.
- Extended `smoke:frontend` weak-link checks so the item-level draft guard and action-selection guard must stay wired.
- Updated Testing Guide and module review log with the new guard contract.

Validation:
- `npm.cmd run typecheck`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/research`.

Risk:
- Low additive client-side validation. Valid backend rule/LLM draft responses are unchanged; malformed draft payloads now fail as controlled client errors instead of later card render or apply-time failures.

## 2026-06-03 - Strict-auth Plugin app-link navigation and page API fallback

Type: browser smoke stability / frontend route linkage / docs

Scope: strengthen the `portfolio-live-plugin` strict-auth browser chain so the Plugin Registry segment proves real app-link navigation before `/plugins`, and so Final Writer/Audit response fallbacks prefer the same browser tab's `/api` proxy before direct Node API calls. This changes smoke infrastructure only; it does not change app runtime behavior, backend schemas, Plugin storage, Portfolio import, SignalOps, or any simulation/live trading boundary.

Changes:
- Added `navigateByAppLink()` and used it to enter `/backend` before clicking the `/plugins` app link in `runPluginArchiveScenario()`.
- Added `pageApiJson()` and let `assertAuthedJsonOrApi()` optionally use page-level Bearer `/api` fallback for Final Writer and Audit Log response waits before direct API fallback.
- Extended `smoke:frontend` static guards to require the app-link navigation helper, page API fallback, and the Plugin navigation runtime marker.
- Updated testing docs to record the Plugin app-link requirement and Final/Audit fallback order.

Validation:
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including `ok strict-auth browser app-link navigation Plugin Registry prerequisite Backend Status route`, Final Writer, Audit Log, Live Run terminal stream, Plugin usage history, artifact hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- One intermediate `portfolio-live-plugin` run failed before reaching Plugin lifecycle because the existing Audit Log direct Node API fallback timed out even though the backend had returned an audit response. The page-level `/api` fallback was added before the direct fallback, and the final browser run passed.

Risk:
- Low smoke-only change. Fallbacks still require Bearer auth and bounded timeouts, and the Audit Log page still has to visibly render the expected run event. No production navigation, request client, plugin execution, order routing, or real-trade behavior changed.

## 2026-06-03 - Research trace import iteration response guard

Type: frontend Research Lab API client / static frontend smoke / docs

Scope: continue the Research Lab high-fanout response-guard recommendation by hardening the trace-import mutation response before it enters `/research-lab/traces` render state. This is frontend contract validation only; it does not change Research storage, Backtest, SignalOps, knowledge promotion, or any simulation/live trading boundary.

Changes:
- Added `assertResearchTraceImportIteration()` to validate each imported trace iteration item.
- The trace import guard now checks preview tags, each iteration's `order`, `hypothesis`, `external_verdict`, `evidence_count`, and optional persisted `iteration` shape.
- Extended `smoke:frontend` weak-link checks so `researchClient` must keep the trace-import item guard and apply it before rendering imported trace events/artifacts.

Validation:
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts` and `/research-lab/traces`.

Risk:
- Low additive client-side validation. Valid backend responses are unchanged; malformed trace-import payloads now fail as controlled client errors instead of causing render-time `.map()`/field access failures.

## 2026-06-03 - Portfolio broker-specific malformed-file repair suggestions

Type: backend Portfolio import validation / frontend Portfolio page UX / strict-auth browser smoke / docs

Scope: extend malformed-file diagnostics with broker-template confidence hints and bounded repair suggestions. This remains failed-import operator guidance only; it does not connect broker accounts, create snapshots from invalid files, route orders, change SignalOps, or alter any `simulation_only` / `is_real_trade=false` boundary.

Changes:
- Added failed-import `brokerTemplateHint`, `templateConfidenceNote`, and `repairSuggestions` derived from filename/source-name hints plus matched headers.
- Added broker-specific required-field repair copy for Eastmoney, HTSC, GTJA, Futu/Moomoo, and Tiger while retaining generic fallback guidance.
- Updated `/portfolio` to render template hint and repair suggestions beside observed headers and row preview.
- Extended backend coverage with a Futu/Moomoo malformed export missing required fields and kept the generic unknown-broker malformed-file assertions.
- Updated strict-auth browser malformed import coverage to verify Futu/Moomoo template hint, confidence note, and broker-specific repair text before valid broker imports continue.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py -q --basetemp=.tmp\pytest-portfolio-repair-suggestions`: passed, `17 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including malformed import broker template hint and repair suggestion, five broker imports, New Task risk preflight, Live Run stream query token, Final Writer, Audit Log, terminal stream event, Plugin artifact hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- One intermediate `portfolio-live-plugin` strict-auth run proved the new malformed import assertions and then timed out waiting for the Live Run URL after New Task start fallback had confirmed the run. The smoke now has a bounded SPA Live Run route fallback and still requires exact run id plus stream `api_key` assertions.

Risk:
- Low additive failure-path diagnostics. Suggestions are bounded strings and do not change successful import parsing, snapshot creation, New Task binding, or trading authority.
- Remaining work is a larger real-broker export corpus and any future broker-account connectivity design as a separate governed project.

## 2026-06-03 - Portfolio malformed-file row preview diagnostics

Type: backend Portfolio import validation / frontend Portfolio page UX / strict-auth browser smoke / docs

Scope: extend the malformed-file import diagnostics from column-level guidance to bounded row-level preview. Failed imports still stay failed, do not create snapshots, do not bind New Task context, and do not change broker connectivity, order routing, SignalOps, or any `simulation_only` / `is_real_trade=false` boundary.

Changes:
- Added bounded import diagnostics for observed source headers, recognized normalized fields, missing required fields, and the first malformed row preview.
- Passed those diagnostics through failed `/portfolio/imports` responses and persisted failed import job `importError` payloads.
- Updated `/portfolio` to render observed headers and row preview beside the existing failed-import reason, job id, required columns, accepted extensions, and recommended-column guidance.
- Extended focused backend assertions, strict-auth malformed CSV assertions, and static frontend smoke guards for `portfolio-import-observed-headers`, `portfolio-import-row-preview`, and `formatImportPreviewCells`.
- Hardened the strict-auth Audit Log visible-event wait with a bounded SPA route retry so a confirmed audit API response cannot fail the browser flow only because the page rendered late.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py -q --basetemp=.tmp\pytest-portfolio-import-row-preview`: passed, `16 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: passed, including malformed import observed headers, row preview, five broker imports, New Task risk preflight, Live Run stream query token, Final Writer, Audit Log, Plugin artifact hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- One intermediate `portfolio-live-plugin` strict-auth run proved the new observed-header and row-preview payload/UI assertions, then timed out later while waiting for the Audit Log event to become visible even though the audit API returned 200. After adding the bounded SPA Audit route retry, the final strict-auth run passed while still requiring the visible audit event before Plugin lifecycle checks.

Risk:
- Low additive failure-path diagnostics. The row preview is bounded and display-only; invalid files still cannot create usable snapshots or trading authority.
- The follow-up broker-specific repair entry adds template hints and repair suggestions; remaining work is larger real-broker export coverage and broker-account connectivity design.

## 2026-06-03 - Portfolio malformed-file import UX diagnostics

Type: backend Portfolio import validation / frontend Portfolio page UX / strict-auth browser smoke / docs

Scope: close the remaining Portfolio malformed-file UX recommendation for the file-import path. The change keeps failed imports failed, records a bounded failed import job, and shows actionable repair guidance on `/portfolio`; it does not create snapshots from invalid files, connect broker accounts, place orders, bypass New Task risk preflight, or change any `simulation_only` / `is_real_trade=false` boundary.

Changes:
- Added structured Portfolio import error diagnostics with `reason`, `jobId`, `filename`, accepted extensions, expected required/recommended columns, and import limits.
- Persisted failed import jobs with `raw_json.importError` so `GET /portfolio/imports/{job_id}` can explain failed imports instead of only returning a generic failure message.
- Added optional `importError` to the backend and frontend HoldingImportJob contracts.
- Extended the shared frontend `httpClient` with `ApiError`, preserving existing `Error.message` behavior while exposing HTTP `detail` and `payload` to callers that need structured diagnostics.
- Updated `/portfolio` to render `portfolio-import-error-detail` with reason, job id, required columns, accepted file types, and recommended columns after a malformed upload.
- Added a strict-auth browser malformed CSV upload before the five valid broker fixtures, proving Bearer auth, multipart `FormData`, structured `NO_VALID_HOLDING_ROWS` diagnostics, visible job id, and expected-column guidance.
- Hardened the portfolio-live-plugin New Task start response wait with a direct Bearer API fallback for the same run id when Playwright misses the start response event, while preserving exact-run and stream-token assertions.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py -q --basetemp=.tmp\pytest-portfolio-import-error-ux`: passed, `16 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: final run passed, including `ok strict-auth browser Portfolio import malformed-file UX`, five broker import markers, New Task portfolio risk preflight, Live Run stream query token, Final Writer, Audit Log, Plugin artifact hash verification, cleanup dry-run, and archive lifecycle.

Validation notes:
- One intermediate `portfolio-live-plugin` run passed the malformed-file UX and five broker uploads, then timed out waiting for the New Task start response event even though the backend returned `POST /api/analysis/runs/{run_id}/start` 200. The smoke now falls back to a direct Bearer API confirmation for the same `run_id` and keeps the exact-run/stream-token checks.

Risk:
- Low additive failure-path UX and diagnostics. Successful Portfolio import, snapshot persistence, New Task binding, and downstream run creation remain unchanged.
- Failed imports still do not create usable snapshots; the job id is diagnostic/audit evidence only.
- This closes the immediate unmapped/malformed file guidance gap, and follow-up entries add first-row repair evidence plus broker-specific repair suggestions; broader real-broker export collection and broker-account connectivity remain future work.

## 2026-06-03 - Portfolio Futu/Tiger broker-template import coverage

Type: backend Portfolio parser/tests / strict-auth browser smoke / docs

Scope: close the Portfolio broker-template diversity follow-up by adding Futu/Moomoo and Tiger import coverage beside Eastmoney, HTSC, and GTJA. This remains file-import-only template parsing and pre-task risk context; it does not connect broker accounts, place orders, alter SignalOps, or enable real-trade execution.

Changes:
- Added common spaced/symbolic English header aliases for portfolio imports, including `Stock Code`, `Security Code`, `Position`, `Available to Sell`, `Average Cost`, `Market Value`, and `P&L`.
- Added compact normalized-header fallback in the Portfolio row picker so space, punctuation, and underscore variants map to the same normalized holding fields.
- Added focused backend coverage for Futu/Moomoo spaced headers and Tiger CSV import persistence, including broker-template id/label, confidence, warnings, snapshot fields, and import job metadata.
- Extended the strict-auth browser Portfolio upload scenario from three fixtures to five: Eastmoney, HTSC, GTJA, Futu/Moomoo, and Tiger.
- Extended static frontend smoke guards for the new Futu/Moomoo and Tiger fixture names and broker labels.
- Increased the portfolio-live-plugin strict-auth start-run response wait to 90s after the five-upload chain exposed a slow first-run response while the imported snapshots had already succeeded.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_portfolio_store.py -q --basetemp=.tmp\pytest-portfolio-broker-templates`: passed, `15 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:portfolio-live-plugin`: final run passed with Eastmoney/HTSC/GTJA/Futu/Tiger import markers, New Task portfolio risk preflight, Live Run stream token, Final Writer/Audit fallbacks, Plugin artifact upload hash verification, cleanup dry-run, and archive lifecycle.

Risk:
- Low additive parser/test/smoke coverage. Header alias expansion is tolerant rather than destructive, and no existing canonical field names were removed.
- The strict-auth smoke had non-fatal bounded browser-response fallbacks for Final Writer and Audit Log direct API checks, but the scenario exited 0 and still rendered the required run/audit evidence.
- Broader real-broker export collection, malformed-file UX, and any broker-account connectivity remain separate future work. This does not change the `simulation_only` / `is_real_trade=false` boundary.

## 2026-06-03 - Technical Kline long-window regression retention summary

Type: backend/frontend Technical Kline governance / Quant Core / strict-auth browser smoke / docs

Scope: close the local Technical Kline follow-up gap around long-window reviewed-case regression visibility while preserving the review-only/no-trade-action boundary. This derives coverage only from retained local Technical Kline governance cases; it does not fetch market data, run parameter scans, trigger SignalOps, start Agent DAG execution, or create simulation/live trade actions.

Changes:
- Added `savedGovernance.caseImpact.longWindowRegression` with retained reviewed-case coverage across the last 200 local governance cases, current/baseline config case counts, config-version and symbol diversity, required classification coverage, remediation, and explicit `REVIEW_ONLY_NO_TRADE_ACTION` / `NO_DIRECT_TRADE_ACTION` boundaries.
- Extended Technical Kline focused tests for low-coverage and ready long-window regression states.
- Added `longWindowRegression` to the frontend Technical Kline typed client.
- Rendered the long-window regression retention summary on the active `/quant-core` Technical Kline case governance card.
- Extended strict-auth browser fixtures/assertions and static frontend smoke guards for the new panel and policy id.
- Updated API contract, testing guide, project assessment, quant improvement plan, and module review log.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_technical_kline_agent.py -q --basetemp=.tmp\pytest-technical-kline-long-window`: passed, `14 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed with the existing PostCSS `from` warning.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.

Risk:
- Low additive governance visibility. The new summary is derived from local reviewed Technical Kline cases and is non-blocking metadata; true external long-horizon real-market regression jobs and production-grade multi-window retention remain future infrastructure work.

## 2026-06-03 - Production health 30d long-trend observability

Type: backend observability/frontend Dashboard + Backend Status metrics contract / strict-auth browser smoke / docs

Scope: close the app-local longer-horizon production analytics gap by extending `/api/metrics.productionHealth` from `24h/7d` to `24h/7d/30d`, while keeping existing `trend` semantics for 24h-vs-7d and adding `longTrend` for 24h-vs-30d. This is read-only over retained local run/job/SignalOps evidence; it does not trigger live LLM calls, market-data calls, SignalOps ticks, Agent DAG execution, or simulation/live trading behavior.

Changes:
- Added `30d` to the default production-health windows and exposed `longTrend` as 24h-vs-30d deltas for run success, LLM success/failure, market fallback, and SignalOps tick.
- Extended the focused backend metrics test with a 30d-only baseline run and assertions for the 30d window plus longTrend deltas.
- Added `longTrend?: ProductionHealthTrend` to the frontend metrics contract.
- Extended Dashboard `dashboard-llm-live-call-trend` with long 30d LLM success/failure deltas.
- Extended Backend Status Health Trends from `24h/7d` to `24h/7d/30d` and showed long-baseline values in `backend-production-health-trend-deltas`.
- Extended strict-auth metrics fixtures/assertions and static frontend smoke guards for 30d/longTrend.
- Updated API contract, testing guide, assessment note, improvement-plan note, and module review log.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_observability_routes.py::test_metrics_exposes_production_health_aggregates_without_live_calls -q --basetemp=.tmp\pytest-production-health-30d`: passed, `1 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.

Risk notes:
- Low additive observability. Existing clients keep using `trend`; `longTrend` is optional on the frontend, and missing values render as `N/A`.
- 30d coverage is bounded by retained local run/job history; deployment-owned retention and external analytics remain separate future work.

## 2026-06-03 - Cross-page production health trend fixture smoke

Type: frontend Backend Status production-health refresh / strict-auth browser smoke / Dashboard + Backend Status production-health contract / docs

Scope: strengthen the remaining cross-page E2E evidence for production health by proving Dashboard and Backend Status consume the same Bearer-auth `/api/metrics.productionHealth` fixture in one scenario. This also adds an explicit Backend Status production-health refresh button so operators can re-fetch metrics after applying a strict-auth token. It does not change backend aggregation, live LLM calls, Agent DAG execution, SignalOps, or simulation/live trading boundaries.

Changes:
- Added `backend-production-health-refresh` and reused `loadProductionHealth()` so `/backend` can explicitly re-fetch `/api/metrics` after an initially unauthorized page load.
- Extended `runDashboardScenario()` so the existing `/api/metrics` fixture remains active while the browser moves from Dashboard to `/backend`.
- Verified Backend Status issues its own Bearer-auth `/api/metrics` request, receives the same trend payload, and renders baseline/delta values plus the same redacted LLM failure reason.
- Added the `ok strict-auth browser cross-page production health trend fixture` marker and static frontend smoke guard.
- Hardened `scripts/smoke-strict-auth-browser.ps1` by normalizing duplicate process `Path` / `PATH` keys before `Start-Process`, preventing Windows environment-case collisions from stopping the smoke before backend startup.
- Updated testing guide, project assessment, improvement-plan note, and module review log.

Validation:
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1` and `scripts\smoke-strict-auth-browser.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke-strict-auth-browser.ps1 -Scenario platform`: passed and printed `ok strict-auth browser cross-page production health trend fixture`.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.

Validation notes:
- The first direct wrapper rerun failed before backend startup because the inherited process environment contained duplicate `Path` / `PATH` keys; `Normalize-ProcessPathEnvironment` now removes the duplicate casing before `Start-Process`.
- A subsequent platform run showed the initial Backend Status production-health wait could miss `/api/metrics` after an unauthorized first page load; `backend-production-health-refresh` now gives operators and smoke a deterministic authenticated refresh path.

Risk notes:
- Low additive observability/test-contract change. The new route intercept still rejects missing Bearer auth and only fulfills the existing metrics endpoint.
- The cross-page assertion proves contract reuse across Dashboard and Backend Status, but broader cross-page state-matrix coverage for unrelated modules remains future work.

## 2026-06-03 - Backend Status production trend delta drill-down

Type: frontend Backend Status production-health observability / strict-auth browser smoke / docs

Scope: close the app-local Backend Status part of the remaining production trend drill-down gap by rendering `/api/metrics.productionHealth.trend` directly on `/backend`. This is read-only over the existing metrics payload; it does not trigger live LLM calls, alter Agent DAG execution, change SignalOps, or touch any simulation/live trading boundary.

Changes:
- Added a signed percentage helper to Backend Status and rendered `backend-production-health-trend-deltas` with baseline window, run success, LLM success/failure, market fallback, and SignalOps tick deltas.
- Extended strict-auth browser Backend Status diagnostics to wait for the trend-delta hook and verify the visible baseline plus metric labels.
- Extended static frontend smoke guards so `smoke:frontend` fails if Backend Status drops the trend hook or the strict-auth marker.
- Updated API contract, testing guide, assessment note, improvement-plan note, and module review log for the new Backend Status trend consumer.

Validation:
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed with exit code 0.

Risk notes:
- Low additive observability. Missing trend values still render as `N/A`, and the new block only consumes the optional typed metrics payload.
- Delta signs are direct current-minus-baseline values; failure-rate deltas are better when negative, while success-rate deltas are better when positive.
- No backend execution path, provider call, order routing, plugin execution, SignalOps lifecycle, Backtest, or real-trade behavior changed.

## 2026-06-03 - Dashboard LLM live-call production trend evidence

Type: backend observability/frontend Dashboard metrics contract / strict-auth browser smoke / docs

Scope: close the app-local part of the remaining production trend-analysis gap by carrying `/api/metrics.productionHealth.trend` through the typed frontend contract and rendering the LLM live-call 24h-vs-7d success/failure trend on Dashboard. This is read-only over retained run and `llmTrace` evidence; it does not trigger live LLM calls, change Agent DAG execution, alter SignalOps, or touch any simulation/live trading boundary.

Changes:
- Added `llmSuccessRateDelta` to the backend `productionHealth.trend` payload beside the existing LLM failure-rate delta and other health deltas.
- Extended the focused backend metrics test with a 7d baseline run, proving rounded 24h-vs-7d run success, LLM failure, and LLM success deltas.
- Added `ProductionHealthTrend` to `analysisClient`, wired `trend?: ProductionHealthTrend`, and rendered `dashboard-llm-live-call-trend` in Dashboard with signed success/failure percentage deltas.
- Extended strict-auth Dashboard metrics fixture/assertions with a 7d baseline, `trend.llmSuccessRateDelta=0.15`, and visible `success +15.0%` / `failure -15.0%` checks.
- Updated static frontend smoke guards, API contract, testing guide, assessment note, improvement-plan note, and module review log.

Validation:
- `npm.cmd run test:backend -- backend\tests\test_observability_routes.py::test_metrics_exposes_production_health_aggregates_without_live_calls -q --basetemp=.tmp\pytest-llm-trend-rerun2`: passed, `1 passed`.
- `node --check scripts\smoke-strict-auth-browser.mjs`: passed.
- PowerShell parse check for `scripts\smoke-frontend-routes.ps1`: passed.
- `npm.cmd run smoke:frontend`: passed, including `ok frontend weak-link contracts`.
- `npm.cmd run typecheck`: passed.
- `npm.cmd run lint`: passed.
- `npm.cmd run build`: passed; existing PostCSS `from` warning remains.
- `npm.cmd run smoke:strict-auth-browser:platform`: passed on the final standalone run.
- `git diff --check`: passed; LF/CRLF working-copy warnings remain.

Validation notes:
- One backend rerun failed before pytest because `uv` could not update a temporary Windows trampoline executable; the subsequent standalone rerun passed.
- One platform smoke run failed while `npm.cmd run build` was concurrently rewriting `frontend/dist`; the final standalone platform smoke passed after build completed.

Risk notes:
- Low additive observability. Missing `trend` remains optional on the frontend and renders `N/A`, so older metrics payloads do not crash Dashboard.
- Delta signs are direct current-minus-baseline values; failure-rate deltas are better when negative, while success-rate deltas are better when positive.
- The path remains read-only with `externalCalls=false`; no live provider calls, order execution, SignalOps lifecycle mutation, or real-trade behavior changed.

## Compressed Historical Log - 2026-06-02 and earlier

This section replaces the long-form historical entries from 2026-06-02 and earlier. It keeps the decision trail, module ownership, validation coverage, and architectural boundaries while removing repeated command transcripts and low-signal implementation minutiae.

### 2026-06-02 - Deployment sidecars, signed handoffs, and async job custody

- Consolidated external-provider readiness sidecars for plugin scans, Data Health monitors, analysis job queues, alert shippers, log shippers, and alert rule providers. The intent was to make provider ownership explicit without granting the local app hidden responsibility for unavailable external services.
- Built deployment handoff surfaces for ops logs, production alerts, external queues, and backtest parameter-scan jobs, including readiness status, inventory integrity checks, export bundles, and local query surfaces.
- Hardened SignalOps review custody with append-only decision events, candidate/baseline parameter diffs, checksums, signed exports, verification metadata, and handoff status. The trading boundary remained review/simulation focused.
- Added durable local backtest parameter-scan jobs with bounded multi-window scans, retained history, idempotent job attempts, local lease claiming, SQLite-lock fallback handling, and deployment handoff bundles.
- Strengthened strict-auth pre-merge coverage and browser scenario grouping so platform, SignalOps, research/backtest, plugin, portfolio, and live-run routes could be checked in smaller stable batches.
- Validation rollup: focused backend suites for plugin, Data Health, observability, SignalOps, backtest, analysis jobs, deployment handoff, and repo hygiene; strict-auth browser groups; frontend typecheck/lint/build/smoke where touched.
- Residual boundary: external sidecars describe and export readiness only; they do not make the local process an external provider, broker, or production alerting platform.

### 2026-06-01 - Strict-auth browser expansion, client guards, and governance visibility

- Split strict-auth browser scenarios into maintainable groups and expanded deep-link, app-link, seeded-state, upload, and route smoke coverage across Dashboard, Final Writer, Audit Log, New Task, Portfolio, Backtest, SignalOps, Plugin Registry, Config Versions, Agent Runtime, Data Health, Technical Kline, Case Library, Knowledge, Evaluation, and Research Lab.
- Reworked many frontend API boundaries to request unknown-shaped responses first, then narrow with local guards. This reduced nullable-field crashes and made malformed API payloads visible instead of trusted.
- Added or tightened role-aware write guards for New Task run creation, Portfolio snapshots, Backtest research actions, Live Run controls, Data Health checks, Plugin runtime checks, Technical Kline governance, Agent Runtime, Knowledge, Evaluation, Case Library, Data Compression, and Research trace import.
- Improved Research/Backtest/SignalOps evidence handoffs: selected-signal deep links, tick-to-research evidence bridges, backtest verdict inputs, reproducible experiment packages, parameter-scan validation protocol, workflow maturity and step guidance, regression waiver visibility, and post-publish impact summaries.
- Expanded Portfolio import coverage and diagnostics for malformed files and broker templates, including Futu, Tiger, GTJA, row previews, and repair suggestions.
- Improved operational visibility for worker diagnostics, queue summaries, source freshness, adapter event trails, ops log retention/export, plugin artifact scanning/cleanup, LLM live-call health, and production health trend evidence.
- Validation rollup: repeated `npm.cmd run typecheck`, `npm.cmd run lint`, `npm.cmd run build`, `npm.cmd run smoke:frontend`, strict-auth browser groups, and targeted backend suites for each touched surface.
- Residual boundary: UI and client hardening did not change backend enum contracts, trading policy, or the simulation-only posture.

### 2026-05-31 - Architecture guardrails, strict-auth smoke, plugin and ops hardening

- Added repository hygiene and architecture guardrails to keep current planning docs, package markers, module ownership, and canonical surfaces aligned.
- Refactored the analysis lifecycle into clearer core/facade paths for create/start/retry/persistence/compare, then added current-run hydration, linked-run browser coverage, SSE token bridging, worker lifecycle handling, and direct-run page stability.
- Expanded strict-auth browser smoke coverage for Dashboard, New Task to Live Run to Final report, Backtest sample runs, SignalOps forced ticks/review decisions/manual commands, Research Lab closed-loop flows, Backend Status, Config Versions, Agent Runtime, and Plugin Registry.
- Hardened ops and backup surfaces with SQLite backup/restore drills, simulated off-host copy, storage restore checks, local outbox channels, bounded webhook retries, structured ops log aggregation, worker lease observability, and local retention pruning.
- Developed plugin lifecycle governance: archive and upgrade flows, runtime quota plans, usage statistics/history, artifact migration metadata, upload hash verification, metadata scanning, retention dry-runs, and local hash denylist checks.
- Tightened admin and high-risk controls for config restore/rollback, Technical Kline governance, Agent Runtime writes, high-risk deletes, and config numeric validation.
- Validation rollup: repo hygiene tests, analysis lifecycle/core tests, strict-auth browser smokes, focused backend suites, encoding/readability guards, and diff checks.
- Residual boundary: restore, backup, plugin, and ops surfaces remained local/governed workflows rather than production migration or live deployment commands.

### 2026-05-30 to 2026-05-27 - Quant Core, MFE/MAE, Phase 1-3, and SignalOps K-line

- Replaced the old stage Bottom Research presentation with MFE/MAE evaluation and kept supporting-only research boundaries clear.
- Merged Quant Core into the canonical product surface, including core interpretation, redirects, linked evidence, Technical Kline case governance, and display/localization cleanup.
- Closed Phase 1-3 acceptance work around Research Lab closure, worker-mode execution, portfolio task links, security baseline hardening, and the next development plan refresh.
- Added SignalOps daily K-line decision-tree lifecycle coverage, backtest provenance rechecks, strategy review visibility, and simulated review/command boundaries.
- Validation rollup: browser closure smokes, worker-mode checks, route smokes, focused backend suites, frontend build/type/lint checks, and security baseline validation.
- Residual boundary: Quant Core and SignalOps work stayed deterministic/evidence-first, with LLM judgment secondary and no real broker order path.

### 2026-05-26 to 2026-05-24 - Research Lab productization and SignalOps validation gates

- Productized Bottom Research and Research Lab flows with nowcast paths, multi-horizon trend synthesis, one-click samples, canonical backtest integration, closure hardening, and live smoke coverage.
- Added SignalOps random-validation jobs, review hardening, strategy stability gates, K-line quality gates, ladder simulation gates, and AUTO_PAPER_V2 backtest synchronization.
- Split Quant Engine and DVG gate modes so horizon-specific behavior and evidence grading could be reasoned about separately.
- Validation rollup: Research Lab/backtest focused tests, SignalOps validation suites, browser smokes, and targeted route checks.
- Residual boundary: paper-trading automation remained simulated and evidence-gated.

### 2026-05-23 to 2026-05-21 - SignalOps review loop and P1-P4 closure

- Hardened SignalOps experiment validation, reproducible experiment loops, review queues, win-quality gates, rolling performance stats, and A-share trading-rule simulation semantics.
- Added AI-assisted SignalOps entry points and automatic paper-trading controls while preserving `simulation_only` / `is_real_trade=false` enforcement.
- Repaired local development launchers, stale-port fallback behavior, and one-click shutdown/startup ergonomics.
- Closed whole-code review and P1-P4 follow-up items across RBAC UI, closed-loop samples, config governance, route smoke coverage, SQLite jobs, production metrics, post-publish regression semantics, Case/Knowledge/Evaluation dashboards, and Research Lab guided workflow state.
- Validation rollup: route smokes, backend regression suites, frontend build/type/lint checks, launcher checks, and SignalOps scenario tests.
- Residual boundary: AI and SignalOps controls were product-facing orchestration for simulated decisions, not direct trading execution.

### 2026-05-20 - P0-P3 backlog closure, config security, and Research Lab expansion

- Consolidated and then closed the old open backlog, replacing it with active planning and assessment documents.
- Finished P0-P3 subagent follow-up work for status reconciliation, closed-loop samples, portfolio entry, backtest samples, provenance, SignalOps decision cards, live-call semantics, and observability classification.
- Hardened runtime security with LLM and market-data egress allowlists, no-key bypass prevention, runtime secret vault and key rotation, persistent analysis job lifecycle, declarative plugin hot-reload sandboxing, and frontend runtime configuration prompts.
- Expanded Research Lab P2-P7, cross-module data-link audits, hypothesis generation, artifact materialization, P2 closed-loop samples, evidence provenance, evaluation promotion fixes, and global market module work.
- Improved market-data cache/fallback behavior and placeholder-only defaults for stock-code entry.
- Validation rollup: focused backend tests, frontend type/lint/build checks, market-data and LLM guard tests, Research Lab suites, and route-level smoke checks.
- Residual boundary: backlog closure removed stale planning debt; it did not remove the requirement to keep current docs aligned after each development slice.

### 2026-05-19 to 2026-05-16 - Initial Research Lab, SignalOps, and baseline setup

- Established the development log, baseline engineering guardrails, AkShare/runtime setup notes, data-source health snapshots, portfolio import enhancement, run-compare snapshots, and Beijing-time display normalization.
- Built the first Research Lab plan and implementation passes: P0-P3 baseline, P4 verdict evidence engine, artifact visibility, evidence compression, knowledge-item compact display, stale-run fallback handling, and module sync rules.
- Developed early SignalOps surfaces for automatic lifecycle sedimentation, paper trading, funding/cash semantics, holdings, board-lot enforcement, session gates, stock-pool management, force-open/force-close commands, simulation metrics, and Case Library integration.
- Removed the earlier Coze SignalOps integration and replaced it with local architecture-consistent SignalOps behavior.
- Validation rollup: backend smoke/regression tests, frontend checks, runtime route reload checks, and manual smoke observations recorded in the original log.
- Residual boundary: early automation was explicitly simulated and used local evidence, not real trade execution.

### Historical Boundary Summary

- Trading policy remained simulation-only across the historical work: preserve `simulation_only=true`, `is_real_trade=false`, `SIM_*` identifiers, and the absence of a real broker order API unless policy is explicitly changed.
- Current planning authority is the active development guide, current project assessment, Quant improvement plan, testing/encoding docs, and the newest detailed development-log entries.
- Deprecated planning documents and old backlog phrasing should not be reintroduced as active sources of truth.
- Use git history for exact historical command transcripts, old line-by-line wording, or pre-compression implementation notes.
