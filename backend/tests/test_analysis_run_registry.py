from app.api import routes_analysis
from app.core.analysis_run_registry import contains_run, get_run, iter_runs


def test_analysis_run_registry_uses_bound_routes_analysis_store(monkeypatch):
    monkeypatch.setattr(
        routes_analysis,
        "runs_store",
        {
            "RUN_ACTIVE_001": {"runId": "RUN_ACTIVE_001", "status": "COMPLETED"},
            "RUN_MOCK_001": {"runId": "RUN_MOCK_001", "status": "COMPLETED"},
        },
    )

    assert get_run("RUN_ACTIVE_001") == {"runId": "RUN_ACTIVE_001", "status": "COMPLETED"}
    assert contains_run("RUN_ACTIVE_001") is True
    assert get_run("RUN_MOCK_001") is None
    assert contains_run("RUN_MOCK_001") is False
    assert list(iter_runs()) == [("RUN_ACTIVE_001", {"runId": "RUN_ACTIVE_001", "status": "COMPLETED"})]
