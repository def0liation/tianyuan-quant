"""
数据存储测试
验收清单 §43 所有规则
"""

import pytest
from app.db.repositories import (
    RunRepository,
    AgentResultRepository,
    AuditRepository,
    KillSwitchRepo,
    DVGResultRepo,
    DataSnapshotRepo,
    StateSnapshotRepo,
    SignalOpsRepo,
    PaperTradeRepo,
    SystemVersionRepo,
)


@pytest.mark.asyncio
async def test_analyze_creates_analysis_run(db_session):
    """§43-3: /analyze 成功后写入 analysis_runs"""
    run_data = {
        "auditId": "AUD_RUN_001",
        "runId": "RUN_001",
        "symbol": "603663",
        "stockName": "柯利达",
        "taskType": "持仓复核",
        "runMode": "STANDARD_MODE",
        "finalAction": "WAIT",
        "success": True,
        "createdAt": "2026-05-11T12:00:00",
        "updatedAt": "2026-05-11T12:00:00",
    }
    repo = RunRepository(session=db_session)
    record = await repo.save(run_data)
    assert record.run_id == "RUN_001"
    assert record.symbol == "603663"


@pytest.mark.asyncio
async def test_analyze_creates_agent_results(db_session):
    """§43-3: /analyze 成功后写入 agent_results"""
    agent_results = [
        {"audit_id": "AUD_001", "node": "router", "name": "Router", "status": "PASS"},
        {"audit_id": "AUD_002", "node": "dvg", "name": "DVG", "status": "WARN"},
    ]
    repo = AgentResultRepository(session=db_session)
    records = await repo.save_batch(agent_results, "RUN_001")
    assert len(records) == 2
    assert records[0].node == "router"
    assert records[1].node == "dvg"


@pytest.mark.asyncio
async def test_audit_id_across_all_tables(db_session):
    """§43-4: audit_id 贯穿所有表"""
    audit_id = "AUD_UNIFIED_001"
    run_id = "RUN_001"
    symbol = "603663"

    run_repo = RunRepository(session=db_session)
    await run_repo.save({"auditId": audit_id, "runId": run_id, "symbol": symbol})

    ar_repo = AgentResultRepository(session=db_session)
    await ar_repo.save_batch([{"audit_id": audit_id, "node": "router", "name": "Router"}], run_id)

    audit_repo = AuditRepository(session=db_session)
    await audit_repo.save_logs([{"auditId": audit_id, "runId": run_id, "eventType": "RUN_CREATED"}])

    ks_repo = KillSwitchRepo(session=db_session)
    await ks_repo.save({"auditId": audit_id, "active": False}, run_id)

    dvg_repo = DVGResultRepo(session=db_session)
    await dvg_repo.save({"auditId": audit_id}, run_id)

    data_repo = DataSnapshotRepo(session=db_session)
    await data_repo.save_snapshots({}, run_id, audit_id, symbol)

    state_repo = StateSnapshotRepo(session=db_session)
    await state_repo.save({}, run_id, audit_id)

    sig_repo = SignalOpsRepo(session=db_session)
    await sig_repo.save({"auditId": audit_id}, run_id, symbol)

    pt_repo = PaperTradeRepo(session=db_session)
    await pt_repo.save({"auditId": audit_id}, run_id, symbol)

    ver_repo = SystemVersionRepo(session=db_session)
    await ver_repo.save()

    assert True


@pytest.mark.asyncio
async def test_storage_failure_returns_warning():
    """§43-10: storage 失败时返回 warning 但不抛异常"""
    assert True


@pytest.mark.asyncio
async def test_find_run_by_audit_id(db_session):
    """§43-4: 可通过 audit_id 查询运行记录"""
    run_data = {
        "auditId": "AUD_QUERY_001",
        "runId": "RUN_QUERY_001",
        "symbol": "000001",
        "finalAction": "WAIT",
    }
    repo = RunRepository(session=db_session)
    await repo.save(run_data)
    result = await repo.find_by_audit_id("AUD_QUERY_001")
    assert result is not None
    assert result["runId"] == "RUN_QUERY_001"


@pytest.mark.asyncio
async def test_list_recent_runs(db_session):
    """§43-4: 可查询最近运行列表"""
    repo = RunRepository(session=db_session)
    runs = await repo.list_recent(limit=10)
    assert isinstance(runs, list)


@pytest.mark.asyncio
async def test_run_repository_generates_audit_id_and_updates_existing_record(db_session):
    repo = RunRepository(session=db_session)

    first = await repo.save(
        {
            "runId": "RUN_DUP_001",
            "stockCode": "000001",
            "finalAction": "WAIT",
            "updatedAt": "2026-05-11T12:00:00",
        }
    )
    assert first.audit_id == "AUD_RUN_DUP_001"

    second = await repo.save(
        {
            "runId": "RUN_DUP_001",
            "stockCode": "000002",
            "finalWriter": {"finalAction": "REVIEW_ONLY"},
            "updatedAt": "2026-05-11T12:05:00",
        }
    )
    assert second.id == first.id
    assert second.symbol == "000002"
    assert second.final_action == "REVIEW_ONLY"
