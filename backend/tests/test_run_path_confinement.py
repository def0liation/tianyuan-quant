from pathlib import Path

import pytest

from app.core import agent_runtime_store


@pytest.mark.parametrize("separator", ["/", "\\"])
def test_run_reads_do_not_escape_into_adjacent_private_json(separator):
    if separator == "\\" and Path("a\\b").name == "a\\b":
        pytest.skip("Windows path separator counterexample")
    private = agent_runtime_store.RUNS_DIR.parent / "adjacent-private.json"
    private.write_text('{"marker":"synthetic-private-fixture"}', encoding="utf-8")
    assert agent_runtime_store.get_run(f"..{separator}adjacent-private") is None
    assert agent_runtime_store.delete_run(f"..{separator}adjacent-private") is False
    assert private.exists()


@pytest.mark.parametrize("run_id", ["../outside", "..\\outside", "C:outside", "bad\0id"])
def test_invalid_run_storage_names_are_rejected_without_writing(run_id):
    with pytest.raises(ValueError, match="run id"):
        agent_runtime_store.save_run({"runId": run_id, "status": "CREATED"})
    assert agent_runtime_store.get_run(run_id) is None
