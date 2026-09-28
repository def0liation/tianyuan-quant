[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

$PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if ($PythonCommand) {
    $PythonExe = $PythonCommand.Source
}
elseif (Test-Path $BundledPython) {
    $PythonExe = $BundledPython
}
else {
    throw "No usable Python interpreter was found. Install Python, or run inside Codex with the bundled Python runtime available."
}

$PythonCode = @'
import datetime as _dt
import json
import pathlib
import sqlite3
import subprocess

root = pathlib.Path.cwd()


def run_command(args):
    try:
        result = subprocess.run(
            args,
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        text = result.stdout.rstrip()
        if result.returncode != 0 and result.stderr.strip():
            suffix = result.stderr.strip()
            text = f"{text}\n{suffix}".strip() if text else suffix
        return text
    except Exception as exc:
        return f"ERROR: {exc}"


tables = [
    "portfolio_snapshots",
    "holding_positions",
    "analysis_runs",
    "agent_results",
    "signals",
    "paper_orders",
    "backtest_runs",
    "backtest_signals",
    "research_loops",
    "research_iterations",
    "research_evidence_links",
    "case_library",
    "knowledge_patches",
    "knowledge_versions",
    "evaluation_runs",
    "analysis_jobs",
]

db_path = root / "storage" / "tianyuan_quant.db"
counts = {}
db_error = None
if db_path.exists():
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = int(cur.fetchone()[0])
                except Exception as exc:
                    counts[table] = f"ERROR: {exc}"
    except Exception as exc:
        db_error = str(exc)
else:
    db_error = "database file not found"

git_status = run_command(["git", "status", "--short"])
branch = run_command(["git", "branch", "--show-current"])
head = run_command(["git", "rev-parse", "--short", "HEAD"])

closure_required = [
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
]

closure_gaps = []
for table in closure_required:
    value = counts.get(table)
    if not isinstance(value, int) or value <= 0:
        closure_gaps.append(table)

report = {
    "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    "cwd": str(root),
    "git": {
        "branch": branch,
        "head": head,
        "dirty": bool(git_status),
        "status": git_status.splitlines() if git_status else [],
    },
    "database": {
        "path": str(db_path),
        "exists": db_path.exists(),
        "error": db_error,
        "counts": counts,
    },
    "closure_required_tables": closure_required,
    "closure_gaps": closure_gaps,
    "non_negotiable_boundaries": [
        "simulation_only=true",
        "is_real_trade=false",
        "SIM_* actions only",
        "no broker connection",
        "no real order API",
    ],
    "storage_authority": {
        "sqlite_primary": [
            "portfolio",
            "backtest",
            "research",
            "case_library",
            "knowledge",
            "evaluation",
            "analysis_jobs mirror",
        ],
        "json_runtime_or_artifact": [
            "analysis run snapshots",
            "auto paper runtime config",
            "agent runtime skeleton",
            "knowledge iteration compatibility artifact",
        ],
        "secrets": [
            "backend/app/storage/agent_runtime.secrets.json",
            "backend/app/storage/agent_runtime.secret.key",
        ],
    },
}

print(json.dumps(report, indent=2, ensure_ascii=False))
'@

Push-Location $Root
try {
    $PythonCode | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
