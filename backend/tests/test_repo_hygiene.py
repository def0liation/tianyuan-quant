import ast
import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

LAYER_BOUNDARY_DIRS = (
    BACKEND_ROOT / "app" / "core",
    BACKEND_ROOT / "app" / "modules",
    BACKEND_ROOT / "app" / "db",
    BACKEND_ROOT / "app" / "models",
)

API_LAYER_DYNAMIC_REFERENCE_MARKERS = (
    "app.api",
    "backend.app.api",
    "routes_analysis",
)

ENCODING_SCAN_ROOTS = (
    REPO_ROOT / "docs",
    REPO_ROOT / "frontend" / "src",
    BACKEND_ROOT / "app",
)
ENCODING_SCAN_EXTRA_FILES = (
    REPO_ROOT / "README.md",
)

TEXT_FILE_EXTENSIONS = {
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}

ENCODING_SCAN_EXCLUDED_RELATIVE_PATHS = {
    Path("docs") / "ENCODING_AUDIT.md",
    Path("docs") / "MODULE_INTERACTION_REVIEW_LOG.md",
}

MOJIBAKE_SENTINELS = (
    "�",
    "Ã",
    "Â",
    "â€",
    "乣",
    "銆",
    "锛",
    "鑷",
    "绾",
    "鏄",
)

REQUIRED_GITIGNORE_PATTERNS = {
    ".env",
    ".env.*",
    ".chrome-headless-profile/",
    ".playwright-cli/",
    ".uv-cache/",
    ".uv-runtime-cache/",
    ".tmp/",
    ".logs/",
    "output/",
    "frontend/dist/",
    "backend/.venv/",
    "backend/app/storage/agent_runtime.secrets.json",
    "backend/app/storage/agent_runtime.secret.key",
    "backend/app/storage/*.json",
    "backend/app/storage/runs/",
    "docs/MODULE_INTERACTION_REVIEW_LOG.md",
}

MODULES_PACKAGE_INIT = BACKEND_ROOT / "app" / "modules" / "__init__.py"
AGENT_REGISTRY = BACKEND_ROOT / "app" / "modules" / "agent_registry.py"
AGENT_EXECUTOR = BACKEND_ROOT / "app" / "core" / "agent_executor.py"
PLUGIN_STORE = BACKEND_ROOT / "app" / "core" / "plugin_store.py"
TESTING_GUIDE = REPO_ROOT / "docs" / "TESTING_GUIDE.md"
FULL_RUN_CHECKLIST = REPO_ROOT / "docs" / "FULL_RUN_CHECKLIST.md"
AUDIT_REPLAY_GUIDE = REPO_ROOT / "docs" / "AUDIT_REPLAY.md"
CODE_REVIEW_FIX_GUIDE = REPO_ROOT / "docs" / "CODE_REVIEW_FIX_GUIDE_2026-05-21.md"
DEVELOPMENT_GUIDE = REPO_ROOT / "docs" / "DEVELOPMENT_GUIDE.md"
DEVELOPMENT_LOG = REPO_ROOT / "docs" / "DEVELOPMENT_LOG.md"
ENCODING_AUDIT = REPO_ROOT / "docs" / "ENCODING_AUDIT.md"
PROJECT_DEVELOPMENT_ASSESSMENT = REPO_ROOT / "docs" / "PROJECT_DEVELOPMENT_ASSESSMENT.md"
QUANT_SYSTEM_IMPROVEMENT_PLAN = REPO_ROOT / "docs" / "QUANT_SYSTEM_IMPROVEMENT_PLAN.md"
START_DEV = REPO_ROOT / "start-dev.ps1"
START_DEV_DOC = REPO_ROOT / "START_DEV.md"
PACKAGE_JSON = REPO_ROOT / "package.json"
MAIN_APP = BACKEND_ROOT / "app" / "main.py"
AUDIT_BASELINE_SCRIPT = REPO_ROOT / "scripts" / "audit-development-baseline.ps1"
PRE_MERGE_VALIDATION = REPO_ROOT / "scripts" / "pre-merge-validation.ps1"
TEST_BACKEND_SCRIPT = REPO_ROOT / "scripts" / "test-backend.ps1"
ANALYSIS_WORKER_SMOKE = REPO_ROOT / "scripts" / "smoke-analysis-worker.ps1"
MODULE_PARTICIPATION_VALIDATION = REPO_ROOT / "scripts" / "module-participation-validation.ps1"
PHASE_1_3_VALIDATION = REPO_ROOT / "scripts" / "phase1-3-validation.ps1"
RESEARCH_CLOSURE_LIVE_SMOKE = REPO_ROOT / "scripts" / "smoke-research-closure-live.ps1"
STRICT_AUTH_BROWSER_SMOKE = REPO_ROOT / "scripts" / "smoke-strict-auth-browser.ps1"
SMOKE_FRONTEND_ROUTES = REPO_ROOT / "scripts" / "smoke-frontend-routes.ps1"

RETIRED_COZE_PATHS = (
    REPO_ROOT / "skill.md",
    BACKEND_ROOT / "app" / "api" / "routes_coze_signalops.py",
    BACKEND_ROOT / "app" / "core" / "coze_signalops_bridge.py",
    BACKEND_ROOT / "app" / "models" / "coze_signalops.py",
    BACKEND_ROOT / "tests" / "test_coze_signalops_bridge.py",
)

RETIRED_ROOT_FRONTEND_PATHS = (
    REPO_ROOT / "src",
    REPO_ROOT / "index.html",
    REPO_ROOT / "vite.config.ts",
    REPO_ROOT / "tsconfig.json",
    REPO_ROOT / "tsconfig.node.json",
    REPO_ROOT / "tailwind.config.js",
    REPO_ROOT / "postcss.config.js",
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for directory in LAYER_BOUNDARY_DIRS:
        files.extend(
            path
            for path in directory.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return files


def _retained_text_files() -> list[Path]:
    files: list[Path] = []
    for root in ENCODING_SCAN_ROOTS:
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in TEXT_FILE_EXTENSIONS
            and path.relative_to(REPO_ROOT) not in ENCODING_SCAN_EXCLUDED_RELATIVE_PATHS
            and "storage" not in path.relative_to(REPO_ROOT).parts
            and "__pycache__" not in path.parts
        )
    files.extend(
        path
        for path in ENCODING_SCAN_EXTRA_FILES
        if path.is_file()
        and path.suffix.lower() in TEXT_FILE_EXTENSIONS
        and path.relative_to(REPO_ROOT) not in ENCODING_SCAN_EXCLUDED_RELATIVE_PATHS
    )
    return files


def _violating_api_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.api" or alias.name.startswith("app.api."):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "app.api" or module.startswith("app.api."):
                violations.append(f"from {module} import ...")
            if node.level > 0 and (module == "api" or module.startswith("api.")):
                violations.append(f"from {'.' * node.level}{module} import ...")
    return violations


def _violating_api_string_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue

        value = node.value.strip()
        if value.startswith("routes_") or any(
            marker in value for marker in API_LAYER_DYNAMIC_REFERENCE_MARKERS
        ):
            violations.append(f"string reference {value!r}")
    return violations


def test_core_layers_do_not_import_api_route_modules():
    violations: list[str] = []
    for path in _python_files():
        for import_text in _violating_api_imports(path):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {import_text}")
        for reference_text in _violating_api_string_references(path):
            violations.append(f"{path.relative_to(REPO_ROOT)}: {reference_text}")

    assert violations == []


def test_gitignore_protects_sensitive_runtime_and_generated_artifacts():
    ignored = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    missing = sorted(REQUIRED_GITIGNORE_PATTERNS - ignored)
    assert missing == []


def test_testing_guide_does_not_promote_archived_backlog_as_current_plan():
    source = TESTING_GUIDE.read_text(encoding="utf-8")
    removed_backlog_link = (
        "OPEN_DEVELOPMENT_BACKLOG.md]"
        "(./"
        "OPEN_DEVELOPMENT_BACKLOG.md) 为准"
    )

    assert removed_backlog_link not in source
    assert "历史未完成项来源" not in source
    assert "PROJECT_DEVELOPMENT_ASSESSMENT.md" in source
    assert "QUANT_SYSTEM_IMPROVEMENT_PLAN.md" in source
    assert "DEVELOPMENT_LOG.md" in source


def test_retired_full_run_checklist_and_legacy_testing_tail_stay_removed():
    source = TESTING_GUIDE.read_text(encoding="utf-8")

    assert not FULL_RUN_CHECKLIST.exists()
    assert not AUDIT_REPLAY_GUIDE.exists()
    assert not CODE_REVIEW_FIX_GUIDE.exists()
    assert "pytest tests/ -v" not in source
    assert "15 个 Agent" not in source
    assert "/analyze 成功后写入" not in source
    assert "FULL_RUN_CHECKLIST.md" not in source
    assert "旧手工清单处理" in source


def test_current_assessment_docs_do_not_restore_stale_validation_baselines():
    combined = "\n".join(
        (
            PROJECT_DEVELOPMENT_ASSESSMENT.read_text(encoding="utf-8"),
            QUANT_SYSTEM_IMPROVEMENT_PLAN.read_text(encoding="utf-8"),
        )
    )

    stale_markers = (
        "13 Agent DAG",
        "最新基线为 `64 passed",
        "`63 passed, 4 warnings`",
        "461 passed, 2 failed",
        "下一阶段完成后，系统应达到",
        "Backtest、Research、Case、Knowledge、Evaluation 不再是空表",
    )
    for marker in stale_markers:
        assert marker not in combined

    assert "validate:phase1-3" in combined
    assert "validate:premerge" in combined
    assert "validate:module-participation" in combined
    assert "当前 10 个活跃 Agent" in combined


def test_development_log_records_current_default_premerge_gate():
    source = DEVELOPMENT_LOG.read_text(encoding="utf-8")

    assert "2026-06-19 - Default premerge gate current-state validation" in source
    for marker in (
        "9 steps",
        "597 passed",
        "frontend responsive smoke",
        "47 routes / 188 checks",
        "strict-auth browser matrix",
        "LF/CRLF",
    ):
        assert marker in source


def test_development_log_records_research_bridge_ui_boundary_premerge_gate():
    source = DEVELOPMENT_LOG.read_text(encoding="utf-8")
    header = "## 2026-06-19 - Research bridge docs strong-conclusion guard"
    start = source.index(header)
    next_section = source.index("\n## ", start + len(header))
    section = source[start:next_section]

    for marker in (
        "npm.cmd run validate:premerge",
        "9 steps",
        "frontend responsive smoke",
        "strict-auth browser matrix",
        "Research Backtest visible verdict-inputs boundary",
        "SignalOps visible Research evidence boundary",
    ):
        assert marker in section
    assert "pre-merge gate failed at backend regression" in section
    assert "ok pre-merge validation" in section


def test_audit_baseline_checks_full_closed_loop_participation_tables():
    source = AUDIT_BASELINE_SCRIPT.read_text(encoding="utf-8")

    assert '"closure_required_tables": closure_required' in source
    for table in (
        "portfolio_snapshots",
        "holding_positions",
        "analysis_runs",
        "agent_results",
        "signals",
        "paper_orders",
        "backtest_runs",
        "research_evidence_links",
        "research_loops",
        "case_library",
        "knowledge_patches",
        "knowledge_versions",
        "evaluation_runs",
        "analysis_jobs",
    ):
        assert f'"{table}"' in source


def test_closed_loop_participation_smoke_is_available_and_checks_persistence_tables():
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    source = (BACKEND_ROOT / "tests" / "test_closed_loop_sample.py").read_text(encoding="utf-8")

    assert '"smoke:closed-loop-participation"' in package
    assert "test_p2_closed_loop_sample_route_materializes_full_chain" in package
    for marker in (
        "AnalysisRunDB",
        "AgentResultDB",
        "analysis_job_store.get_sqlite_job",
        "PortfolioSnapshotDB",
        "HoldingPositionDB",
        "SignalDB",
        "PaperOrderDB",
        "BacktestRunDB",
        "BacktestSignalDB",
        "KnowledgePatchDB",
        "KnowledgeVersionDB",
        "EvaluationRunDB",
        "ResearchEvidenceLinkDB",
    ):
        assert marker in source


def test_premerge_gate_runs_closed_loop_participation_smoke_by_default():
    source = PRE_MERGE_VALIDATION.read_text(encoding="utf-8")

    assert "[switch]$SkipClosedLoopParticipation" in source
    assert "closed-loop participation smoke" in source
    assert "smoke:closed-loop-participation" in source
    assert source.index("smoke:closed-loop-participation") < source.index("typecheck")


def test_analysis_worker_smoke_is_available_and_runs_in_premerge_by_default():
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    premerge = PRE_MERGE_VALIDATION.read_text(encoding="utf-8")
    smoke = ANALYSIS_WORKER_SMOKE.read_text(encoding="utf-8")

    assert '"smoke:analysis-worker"' in package
    assert "[switch]$SkipAnalysisWorkerSmoke" in premerge
    assert "analysis worker smoke" in premerge
    assert "smoke:analysis-worker" in premerge
    assert premerge.index("smoke:analysis-worker") < premerge.index("typecheck")
    assert '.Substring(0, 8)' in smoke
    for marker in (
        "test_worker_mode_start_queues_without_background_task",
        "test_worker_once_claims_queued_run_and_executes",
        "test_worker_heartbeat_updates_while_run_is_executing",
        "test_worker_running_cancel_request_is_observed_by_heartbeat",
        "test_claim_next_job_respects_concurrency_group_limit",
        "test_stale_reconciliation_updates_sqlite_only_job",
        ".tmp\\pytest-analysis-worker-smoke-$runId",
        ".tmp\\analysis-worker-cli-smoke\\$runId\\analysis-worker.db",
        ".tmp\\analysis-worker-cli-smoke\\$runId\\analysis_jobs.json",
    ):
        assert marker in smoke


def test_backend_pytest_wrapper_keeps_uv_trampolines_out_of_repo_temp():
    source = TEST_BACKEND_SCRIPT.read_text(encoding="utf-8")

    assert '$SystemTempRoot = if ($env:LOCALAPPDATA)' in source
    assert 'Join-Path $env:LOCALAPPDATA "Temp\\tianyuan-quant-agent-ui"' in source
    assert '$PytestTempDir = Join-Path $SystemTempRoot' in source
    assert '$env:TEMP = $PytestTempDir' in source
    assert '$env:TMP = $PytestTempDir' in source
    assert '(".tmp\\pytest-temp-{0}" -f $TempRunId)' not in source
    assert '$PytestBaseTempDir = Join-Path $Root (".tmp\\pytest-basetemp-{0}" -f $TempRunId)' in source


def test_phase_1_3_validation_runs_closure_worker_and_browser_acceptance():
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    source = PHASE_1_3_VALIDATION.read_text(encoding="utf-8")

    assert '"validate:phase1-3"' in package
    assert "audit:baseline" in source
    assert "validate:module-participation" in source
    assert '"typecheck"' in source
    assert '"lint"' in source
    assert '"build"' in source
    assert "smoke:frontend" in source
    assert "smoke:research-closure:browser" in source
    assert "status --short" in source
    assert "[switch]$SkipBrowserSmoke" in source


def test_research_closure_browser_smoke_cleans_spawned_process_trees():
    source = RESEARCH_CLOSURE_LIVE_SMOKE.read_text(encoding="utf-8")

    assert "function Stop-ProcessTree" in source
    assert "ParentProcessId -eq $ProcessId" in source
    assert "Stop-ProcessTree -ProcessId $frontendProcess.Id" in source
    assert "Stop-ProcessTree -ProcessId $backendProcess.Id" in source


def test_strict_auth_browser_smoke_cleans_spawned_process_trees():
    source = STRICT_AUTH_BROWSER_SMOKE.read_text(encoding="utf-8")

    assert "function Stop-ProcessTree" in source
    assert "ParentProcessId -eq $ProcessId" in source
    assert "Stop-ProcessTree -ProcessId $frontendProcess.Id" in source
    assert "Stop-ProcessTree -ProcessId $backendProcess.Id" in source


def test_frontend_smoke_keeps_research_bridge_doc_markers_in_helper():
    source = SMOKE_FRONTEND_ROUTES.read_text(encoding="utf-8")

    assert "function Assert-ResearchBridgeDocBoundaryMarkers" in source
    assert "$researchBridgeDocMarkerSources = @(" in source
    assert "foreach ($markerSource in $MarkerSources)" in source
    assert "Research bridge strong-conclusion marker" in source
    assert "Assert-ResearchBridgeDocBoundaryMarkers -MarkerSources $researchBridgeDocMarkerSources" in source
    for marker_source in (
        "DEVELOPMENT_GUIDE",
        "API_CONTRACT",
        "TESTING_GUIDE",
        "PROJECT_DEVELOPMENT_ASSESSMENT",
        "QUANT_SYSTEM_IMPROVEMENT_PLAN",
    ):
        assert marker_source in source


def test_module_participation_validation_covers_primary_runtime_modules():
    package = PACKAGE_JSON.read_text(encoding="utf-8")
    source = MODULE_PARTICIPATION_VALIDATION.read_text(encoding="utf-8")

    assert '"validate:module-participation"' in package
    assert '.Substring(0, 8)' in source
    assert "test_auto_paper_tick_creates_sim_buy_without_manual_intervention" in source
    assert "test_auto_paper_tick_route_forced_and_blocked" in source
    assert "test_mfe_mae_quant_core_chain.py" in source
    assert "test_p2_closed_loop_sample_route_materializes_full_chain" in source
    assert ".tmp\\pytest-module-signalops-$runId" in source
    assert ".tmp\\pytest-module-mfe-mae-$runId" in source
    assert ".tmp\\pytest-module-closed-loop-$runId" in source
    assert "closed-loop persistence participation" in source
    assert "smoke:analysis-worker" in source
    for path in (
        "backend\\tests\\test_data_reliability_routes.py",
        "backend\\tests\\test_portfolio_store.py",
        "backend\\tests\\test_backtest_engine.py",
        "backend\\tests\\test_backtest_signalops_sample.py",
        "backend\\tests\\test_backtest_store.py",
        "backend\\tests\\test_research_store.py",
        "backend\\tests\\test_research_artifact_store.py",
        "backend\\tests\\test_research_verdict_store.py",
        "backend\\tests\\test_evaluation.py",
        "backend\\tests\\test_plugin_store.py",
        "backend\\tests\\test_plugin_runtime.py",
        "backend\\tests\\test_observability_routes.py",
    ):
        assert f'"{path}"' in source


def test_plugin_artifact_upload_uses_short_temp_filename_for_windows_paths():
    source = PLUGIN_STORE.read_text(encoding="utf-8")

    assert 'f".upload-{uuid.uuid4().hex[:12]}.tmp"' in source
    assert 'f".{storage_filename}.{uuid.uuid4().hex}.tmp"' not in source


def test_default_backend_regression_covers_high_risk_module_participation():
    source = TEST_BACKEND_SCRIPT.read_text(encoding="utf-8")

    for path in (
        "backend\\tests\\test_http_auth.py",
        "backend\\tests\\test_config_routes.py",
        "backend\\tests\\test_agent_runtime.py",
        "backend\\tests\\test_analysis_workflow.py",
        "backend\\tests\\test_analysis_lifecycle_core_services.py",
        "backend\\tests\\test_analysis_run_compare.py",
        "backend\\tests\\test_mfe_mae_quant_core_chain.py",
        "backend\\tests\\test_market_data_runner.py",
        "backend\\tests\\test_market_data_adapter.py",
        "backend\\tests\\test_data_reliability_routes.py",
        "backend\\tests\\test_portfolio_store.py",
        "backend\\tests\\test_auto_paper_trading.py",
        "backend\\tests\\test_auto_paper_routes.py",
        "backend\\tests\\test_signalops_lifecycle_store.py",
        "backend\\tests\\test_signalops.py",
        "backend\\tests\\test_signalops_routes.py",
        "backend\\tests\\test_backtest_engine.py",
        "backend\\tests\\test_backtest_signalops_sample.py",
        "backend\\tests\\test_backtest_store.py",
        "backend\\tests\\test_research_store.py",
        "backend\\tests\\test_research_artifact_store.py",
        "backend\\tests\\test_research_verdict_store.py",
        "backend\\tests\\test_evaluation.py",
        "backend\\tests\\test_plugin_store.py",
        "backend\\tests\\test_plugin_runtime.py",
        "backend\\tests\\test_analysis_job_sqlite.py",
        "backend\\tests\\test_analysis_job_reconciliation.py",
        "backend\\tests\\test_observability_routes.py",
        "backend\\tests\\test_repo_hygiene.py",
    ):
        assert f'"{path}"' in source


def test_retained_docs_and_sources_are_valid_utf8():
    invalid_files: list[str] = []
    for path in _retained_text_files():
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            relative = path.relative_to(REPO_ROOT)
            invalid_files.append(f"{relative}: {exc}")

    assert invalid_files == []


def test_retained_docs_and_sources_do_not_reintroduce_mojibake_strings():
    hits: list[str] = []
    for path in _retained_text_files():
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for sentinel in MOJIBAKE_SENTINELS:
                if sentinel in line:
                    relative = path.relative_to(REPO_ROOT)
                    hits.append(f"{relative}:{line_number}: {sentinel}")

    assert hits == []


def test_encoding_review_guidance_is_guarded_by_strict_utf8_scan():
    audit = ENCODING_AUDIT.read_text(encoding="utf-8")
    guide = DEVELOPMENT_GUIDE.read_text(encoding="utf-8")
    log = DEVELOPMENT_LOG.read_text(encoding="utf-8")
    source = Path(__file__).read_text(encoding="utf-8")

    assert "Do not rely on the Windows PowerShell default text reader" in audit
    assert "Strict UTF-8 decoding found no invalid files" in audit
    assert "backend/tests/test_repo_hygiene.py" in audit
    assert "retained-text UTF-8 and mojibake sentinel scan" in audit
    assert "def test_retained_docs_and_sources_are_valid_utf8" in source
    assert "def test_retained_docs_and_sources_do_not_reintroduce_mojibake_strings" in source
    assert "2026-05-21 代码审查修复指南已完成并删除" in guide
    assert "R1-R13、T1-T3、D1-D3 均无剩余当前开发项" in guide
    assert "UTF-8/mojibake guard" in guide
    assert "R1-R13, T1-T3, and D1-D3 items were already verified closed" in log


def test_agent_modules_package_marker_has_active_registry_owner():
    package_tree = ast.parse(MODULES_PACKAGE_INIT.read_text(encoding="utf-8"), filename=str(MODULES_PACKAGE_INIT))
    meaningful_nodes = [
        node
        for node in package_tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    assert meaningful_nodes == []

    registry_source = AGENT_REGISTRY.read_text(encoding="utf-8")
    assert "_AGENT_CLASSES" in registry_source
    assert "def run_agent(" in registry_source
    assert "def registered_agents(" in registry_source

    executor_source = AGENT_EXECUTOR.read_text(encoding="utf-8")
    assert "from ..modules.agent_registry import run_agent as run_agent_module" in executor_source
    assert "run_agent_module(agent_id, run, prior_outputs)" in executor_source


def test_start_dev_install_requires_explicit_backend_venv_recreation():
    source = START_DEV.read_text(encoding="utf-8")
    doc = START_DEV_DOC.read_text(encoding="utf-8")

    assert "[switch]$RecreateBackendVenv" in source
    assert "Refusing to remove it during -Install without explicit confirmation" in source
    assert ".\\start-dev.ps1 -Install -RecreateBackendVenv" in source

    guard_index = source.index("if (-not $RecreateBackendVenv)")
    remove_index = source.index("Remove-Item -LiteralPath $BackendVenvDir -Recurse -Force")
    assert guard_index < remove_index

    assert ".\\start-dev.ps1 -Install -RecreateBackendVenv" in doc


def test_coze_signalops_bridge_remains_retired_from_active_runtime():
    active_files = [path.relative_to(REPO_ROOT).as_posix() for path in RETIRED_COZE_PATHS if path.exists()]

    assert active_files == []
    assert "coze" not in MAIN_APP.read_text(encoding="utf-8").lower()
    assert "coze" not in PACKAGE_JSON.read_text(encoding="utf-8").lower()

    testing_guide = TESTING_GUIDE.read_text(encoding="utf-8")
    assert "Coze-facing bridge is no longer an active surface" in testing_guide


def test_retired_root_frontend_app_stays_removed_and_launchers_delegate_to_frontend():
    active_paths = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in RETIRED_ROOT_FRONTEND_PATHS
        if path.exists()
    ]
    assert active_paths == []

    scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
    for script_name in ("dev", "build", "lint", "typecheck", "preview"):
        assert "npm.cmd --prefix frontend run" in scripts[script_name]

    assert scripts["test:frontend"] == "npm.cmd --prefix frontend run typecheck"
