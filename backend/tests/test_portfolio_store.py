from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.api import routes_portfolio
from app.core.portfolio_store import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_CELL_CHARS,
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    build_snapshot,
    decode_table,
    detect_broker_template,
    get_import_job,
    get_snapshot,
    list_snapshots,
    positions_from_rows,
    save_import_job,
)
from app.models.portfolio import (
    HoldingPosition,
    ManualPortfolioRequest,
    PortfolioSnapshot,
    PortfolioSnapshotSummary,
)


def _xlsx_bytes(rows):
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class _LargeUpload:
    filename = "holdings.csv"

    def __init__(self):
        self.read_size = None

    async def read(self, size=-1):
        self.read_size = size
        return b"x" * (MAX_IMPORT_BYTES + 1)


class _BytesUpload:
    def __init__(self, filename: str, raw: bytes):
        self.filename = filename
        self.raw = raw
        self.read_size = None

    async def read(self, size=-1):
        self.read_size = size
        return self.raw


def test_decode_xlsx_portfolio_rows_and_cash_weighting():
    raw = _xlsx_bytes(
        [
            ["股票代码", "股票名称", "持股数量", "可用股数", "成本价", "市值", "所属行业", "主题", "风险因子"],
            ["002846", "英联股份", 2000, 1000, 8.8, 30000, "包装", "消费", "流动性"],
            ["603663", "三祥新材", 1000, 1000, 12.5, 15000, "材料", "新材料", "周期"],
        ]
    )

    rows, encoding = decode_table(raw, "holdings.xlsx")
    positions, issues = positions_from_rows(rows)
    snapshot = build_snapshot(
        positions,
        issues,
        source_type="XLSX",
        source_name="test.xlsx",
        cash=5000,
        available_cash=3000,
        total_assets=50000,
    )

    assert encoding == "xlsx"
    assert len(positions) == 2
    assert positions[0].symbol == "002846"
    assert snapshot.sourceType == "XLSX"
    assert snapshot.totalAssets == 50000
    assert snapshot.cash == 5000
    assert snapshot.availableCash == 3000
    assert snapshot.totalPositionRatio == 0.9
    assert snapshot.evidenceUsage == "supporting_only"
    assert snapshot.evidenceStrength == "LOW"
    assert snapshot.simulationOnly is True
    assert snapshot.isRealTrade is False
    assert snapshot.strongConclusionAllowed is False
    assert positions[0].weight == 0.6


def test_portfolio_snapshot_models_sanitize_supporting_only_boundary():
    polluted_snapshot = {
        "snapshotId": "PF_POLLUTED_BOUNDARY",
        "sourceType": "CSV",
        "sourceName": "legacy",
        "accountName": "legacy-account",
        "totalAssets": 100000.0,
        "cash": 30000.0,
        "stockMarketValue": 70000.0,
        "availableCash": 30000.0,
        "totalPositionRatio": 0.7,
        "maxSinglePositionRatio": 0.7,
        "positionCount": 1,
        "qualityStatus": "OK",
        "issueCount": 0,
        "brokerTemplateId": "legacy",
        "brokerTemplateLabel": "Legacy",
        "templateConfidence": 1.0,
        "templateWarnings": [],
        "evidenceUsage": "primary",
        "evidenceStrength": "HIGH",
        "simulationOnly": False,
        "isRealTrade": True,
        "strongConclusionAllowed": True,
        "importedAt": "2026-06-01T00:00:00Z",
        "updatedAt": "2026-06-01T00:00:00Z",
        "positions": [],
        "issues": [],
    }

    detail = PortfolioSnapshot(**polluted_snapshot).model_dump()
    summary_payload = {
        key: value
        for key, value in polluted_snapshot.items()
        if key not in {"availableCash", "positions", "issues"}
    }
    summary = PortfolioSnapshotSummary(**summary_payload).model_dump()

    for payload in (detail, summary):
        assert payload["evidenceUsage"] == "supporting_only"
        assert payload["evidenceStrength"] == "PENDING"
        assert payload["simulationOnly"] is True
        assert payload["isRealTrade"] is False
        assert payload["strongConclusionAllowed"] is False


def test_portfolio_snapshot_list_route_declares_boundary_response_model():
    route = next(
        item
        for item in routes_portfolio.router.routes
        if getattr(item, "path", "") == "/portfolio/snapshots"
    )

    assert route.response_model == list[PortfolioSnapshotSummary]


def test_detect_broker_template_records_confidence_and_warnings():
    rows = [
        {
            "stock_code": "002846",
            "holding": "2000",
            "cost_price": "8.8",
            "market_value": "30000",
        }
    ]

    template = detect_broker_template(rows, filename="eastmoney-holdings.csv", source_name="eastmoney export")

    assert template["brokerTemplateId"] == "eastmoney"
    assert template["brokerTemplateLabel"] == "Eastmoney broker export"
    assert template["templateConfidence"] >= 0.8
    assert template["templateWarnings"] == [
        "Review broker template mapping for optional columns: name, availableShares."
    ]


def test_detect_broker_template_supports_gtja_column_aliases():
    rows = [
        {
            "security_code": "600519",
            "security_name": "Kweichow Moutai",
            "current_qty": "20",
            "available_qty": "20",
            "avg_cost": "1550",
            "market_capital": "31000",
            "profit_loss": "1200",
        }
    ]

    template = detect_broker_template(rows, filename="gtja-positions.csv", source_name="guotai junan")
    positions, issues = positions_from_rows(rows)

    assert template["brokerTemplateId"] == "gtja"
    assert template["brokerTemplateLabel"] == "Guotai Junan Securities export"
    assert template["templateConfidence"] >= 0.9
    assert template["templateWarnings"] == []
    assert issues == []
    assert positions[0].symbol == "600519"
    assert positions[0].availableShares == 20
    assert positions[0].costPrice == 1550
    assert positions[0].marketValue == 31000
    assert positions[0].pnl == 1200


def test_detect_broker_template_supports_futu_moomoo_spaced_headers():
    rows = [
        {
            "Stock Code": "00700.HK",
            "Stock Name": "Tencent",
            "Quantity": "100",
            "Available Qty": "80",
            "Average Cost": "320",
            "Market Value": "35000",
            "Unrealized P/L": "3000",
        }
    ]

    template = detect_broker_template(rows, filename="futu-moomoo-positions.csv", source_name="moomoo export")
    positions, issues = positions_from_rows(rows)

    assert template["brokerTemplateId"] == "futu"
    assert template["brokerTemplateLabel"] == "Futu/Moomoo broker export"
    assert template["templateConfidence"] >= 0.9
    assert template["templateWarnings"] == []
    assert issues == []
    assert positions[0].symbol == "00700"
    assert positions[0].availableShares == 80
    assert positions[0].costPrice == 320
    assert positions[0].marketValue == 35000
    assert positions[0].pnl == 3000


@pytest.mark.asyncio
async def test_import_portfolio_route_persists_broker_template_metadata():
    raw = b"stock_code,stock_name,holding,available,cost_price,market_value\n002846,Yinglian,2000,1000,8.8,30000\n"
    upload = _BytesUpload("eastmoney-holdings.csv", raw)

    result = await routes_portfolio.import_portfolio(
        file=upload,
        source_name="eastmoney",
        account_name="",
        cash=0.0,
        available_cash=0.0,
        total_assets=0.0,
    )
    snapshot = result.snapshot
    loaded = await get_snapshot(snapshot.snapshotId)
    job = await get_import_job(result.jobId)

    assert upload.read_size == MAX_IMPORT_BYTES + 1
    assert snapshot.brokerTemplateId == "eastmoney"
    assert snapshot.templateConfidence >= 0.8
    assert snapshot.evidenceUsage == "supporting_only"
    assert snapshot.evidenceStrength == "MEDIUM"
    assert snapshot.simulationOnly is True
    assert snapshot.isRealTrade is False
    assert snapshot.strongConclusionAllowed is False
    assert loaded is not None
    assert loaded.brokerTemplateLabel == "Eastmoney broker export"
    assert loaded.evidenceUsage == "supporting_only"
    assert loaded.evidenceStrength == "MEDIUM"
    assert loaded.simulationOnly is True
    assert loaded.isRealTrade is False
    assert loaded.strongConclusionAllowed is False
    summaries = await list_snapshots()
    summary = next(item for item in summaries if item.snapshotId == snapshot.snapshotId)
    assert summary.evidenceUsage == "supporting_only"
    assert summary.evidenceStrength == "MEDIUM"
    assert summary.simulationOnly is True
    assert summary.isRealTrade is False
    assert summary.strongConclusionAllowed is False
    assert job is not None
    assert job["brokerTemplateId"] == "eastmoney"


@pytest.mark.asyncio
async def test_import_portfolio_route_detects_htsc_tsv_template_without_warnings():
    raw = b"code\tname\tshares\tavailable_shares\tcost\tvalue\n603663\tSanxiang\t1500\t900\t11.2\t16800\n"
    upload = _BytesUpload("htsc-holdings.tsv", raw)

    result = await routes_portfolio.import_portfolio(
        file=upload,
        source_name="huatai export",
        account_name="htsc-account",
        cash=12000.0,
        available_cash=8000.0,
        total_assets=28800.0,
    )
    snapshot = result.snapshot
    loaded = await get_snapshot(snapshot.snapshotId)
    job = await get_import_job(result.jobId)

    assert snapshot.sourceType == "CSV"
    assert snapshot.brokerTemplateId == "htsc"
    assert snapshot.brokerTemplateLabel == "Huatai Securities export"
    assert snapshot.templateConfidence >= 0.9
    assert snapshot.templateWarnings == []
    assert snapshot.positions[0].symbol == "603663"
    assert snapshot.accountName == "htsc-account"
    assert loaded is not None
    assert loaded.brokerTemplateId == "htsc"
    assert job is not None
    assert job["brokerTemplateId"] == "htsc"


@pytest.mark.asyncio
async def test_import_portfolio_route_detects_gtja_csv_template_without_warnings():
    raw = (
        b"security_code,security_name,current_qty,available_qty,avg_cost,market_capital,profit_loss\n"
        b"600519,Kweichow Moutai,20,20,1550,31000,1200\n"
    )
    upload = _BytesUpload("gtja-positions.csv", raw)

    result = await routes_portfolio.import_portfolio(
        file=upload,
        source_name="guotai junan export",
        account_name="gtja-account",
        cash=5000.0,
        available_cash=5000.0,
        total_assets=36000.0,
    )
    snapshot = result.snapshot
    loaded = await get_snapshot(snapshot.snapshotId)
    job = await get_import_job(result.jobId)

    assert snapshot.sourceType == "CSV"
    assert snapshot.brokerTemplateId == "gtja"
    assert snapshot.brokerTemplateLabel == "Guotai Junan Securities export"
    assert snapshot.templateConfidence >= 0.9
    assert snapshot.templateWarnings == []
    assert snapshot.positions[0].symbol == "600519"
    assert snapshot.positions[0].availableShares == 20
    assert snapshot.positions[0].pnl == 1200
    assert snapshot.accountName == "gtja-account"
    assert loaded is not None
    assert loaded.brokerTemplateId == "gtja"
    assert job is not None
    assert job["brokerTemplateId"] == "gtja"


@pytest.mark.asyncio
async def test_import_portfolio_route_detects_tiger_csv_template_without_warnings():
    raw = (
        b"Symbol,Stock Name,Position,Available to Sell,Avg Price,Market Value,P&L\n"
        b"AAPL,Apple,12,12,180,2280,120\n"
    )
    upload = _BytesUpload("tiger-portfolio.csv", raw)

    result = await routes_portfolio.import_portfolio(
        file=upload,
        source_name="tiger export",
        account_name="tiger-account",
        cash=1000.0,
        available_cash=1000.0,
        total_assets=3280.0,
    )
    snapshot = result.snapshot
    loaded = await get_snapshot(snapshot.snapshotId)
    job = await get_import_job(result.jobId)

    assert snapshot.sourceType == "CSV"
    assert snapshot.brokerTemplateId == "tiger"
    assert snapshot.brokerTemplateLabel == "Tiger broker export"
    assert snapshot.templateConfidence >= 0.9
    assert snapshot.templateWarnings == []
    assert snapshot.positions[0].symbol == "AAPL"
    assert snapshot.positions[0].availableShares == 12
    assert snapshot.positions[0].costPrice == 180
    assert snapshot.positions[0].marketValue == 2280
    assert snapshot.positions[0].pnl == 120
    assert snapshot.accountName == "tiger-account"
    assert loaded is not None
    assert loaded.brokerTemplateId == "tiger"
    assert job is not None
    assert job["brokerTemplateId"] == "tiger"


@pytest.mark.asyncio
async def test_import_job_can_be_queried_after_save():
    raw = _xlsx_bytes(
        [
            ["股票代码", "股票名称", "持股数量", "成本价", "市值"],
            ["002846", "英联股份", 2000, 8.8, 30000],
        ]
    )
    rows, _ = decode_table(raw, "holdings.xlsx")
    positions, issues = positions_from_rows(rows)
    snapshot = build_snapshot(positions, issues, source_type="XLSX", source_name="test.xlsx")

    await save_import_job("IMP_TEST_XLSX", "holdings.xlsx", "COMPLETED", snapshot, "ok", "XLSX")
    job = await get_import_job("IMP_TEST_XLSX")

    assert job is not None
    assert job["jobId"] == "IMP_TEST_XLSX"
    assert job["sourceType"] == "XLSX"
    assert job["rowsImported"] == 1
    assert job["snapshotId"] == snapshot.snapshotId


@pytest.mark.asyncio
async def test_manual_portfolio_route_normalizes_symbol_and_persists_positions():
    snapshot = await routes_portfolio.create_manual_portfolio(
        ManualPortfolioRequest(
            sourceName="manual route test",
            cash=50000,
            availableCash=50000,
            totalAssets=100000,
            positions=[
                HoldingPosition(
                    symbol="603663.SZ",
                    name="科伦药业",
                    shares=600,
                    availableShares=500,
                    costPrice=20,
                    marketValue=12000,
                )
            ],
        )
    )

    assert snapshot.positions[0].symbol == "603663"
    assert snapshot.positions[0].weight == 0.12
    loaded = await get_snapshot(snapshot.snapshotId)
    assert loaded is not None
    assert loaded.positions[0].symbol == "603663"


@pytest.mark.asyncio
async def test_manual_portfolio_route_rejects_empty_symbol():
    with pytest.raises(HTTPException) as exc:
        await routes_portfolio.create_manual_portfolio(
            ManualPortfolioRequest(
                sourceName="bad manual route test",
                positions=[HoldingPosition(symbol="", shares=100)],
            )
        )

    assert exc.value.status_code == 400
    assert "No valid holding rows" in exc.value.detail


def test_decode_csv_rejects_imports_over_row_limit():
    raw = ("symbol,shares\n" + "\n".join(f"{index:06d},100" for index in range(MAX_IMPORT_ROWS + 1))).encode()

    with pytest.raises(ValueError, match="row limit"):
        decode_table(raw, "holdings.csv")


def test_decode_csv_rejects_imports_over_column_limit():
    headers = [f"col{index}" for index in range(MAX_IMPORT_COLUMNS + 1)]
    raw = (",".join(headers) + "\n" + ",".join("1" for _ in headers)).encode()

    with pytest.raises(ValueError, match="column limit"):
        decode_table(raw, "holdings.csv")


def test_decode_csv_rejects_large_cells():
    raw = f"symbol,shares\n603663,{'1' * (MAX_IMPORT_CELL_CHARS + 1)}".encode()

    with pytest.raises(ValueError, match="cell"):
        decode_table(raw, "holdings.csv")


@pytest.mark.asyncio
async def test_import_portfolio_route_rejects_files_over_byte_limit():
    upload = _LargeUpload()

    with pytest.raises(HTTPException) as exc:
        await routes_portfolio.import_portfolio(file=upload, source_name="oversized")

    assert upload.read_size == MAX_IMPORT_BYTES + 1
    assert exc.value.status_code == 400
    assert "byte limit" in exc.value.detail["message"]
    assert exc.value.detail["jobId"].startswith("IMP_")
    assert exc.value.detail["reason"] == "FILE_TOO_LARGE"
    assert exc.value.detail["limits"]["maxBytes"] == MAX_IMPORT_BYTES
    assert ".csv" in exc.value.detail["acceptedExtensions"]


@pytest.mark.asyncio
async def test_import_portfolio_route_returns_structured_error_for_unmapped_file():
    upload = _BytesUpload("unknown-broker.csv", b"foo,bar\n1,2\n")

    with pytest.raises(HTTPException) as exc:
        await routes_portfolio.import_portfolio(file=upload, source_name="unknown broker")

    detail = exc.value.detail
    assert exc.value.status_code == 400
    assert detail["reason"] == "NO_VALID_HOLDING_ROWS"
    assert detail["jobId"].startswith("IMP_")
    assert detail["filename"] == "unknown-broker.csv"
    assert any("symbol" in item for item in detail["expectedColumns"]["required"])
    assert any("shares" in item for item in detail["expectedColumns"]["required"])
    assert ".xlsx" in detail["acceptedExtensions"]
    assert detail["limits"]["maxRows"] == MAX_IMPORT_ROWS
    assert detail["observedHeaders"] == ["foo", "bar"]
    assert detail["matchedFields"] == []
    assert detail["missingRequiredFields"] == ["symbol", "shares"]
    assert detail["rowPreview"] == [{"rowNumber": 2, "cells": {"foo": "1", "bar": "2"}}]
    assert detail["brokerTemplateHint"]["brokerTemplateId"] == "generic_broker"
    assert detail["brokerTemplateHint"]["templateConfidence"] == 0.35
    assert "no broker-specific source hint matched" in detail["templateConfidenceNote"]
    assert any("no Portfolio holding fields" in item for item in detail["repairSuggestions"])

    job = await get_import_job(detail["jobId"])
    assert job is not None
    assert job["status"] == "FAILED"
    assert job["snapshotId"] is None
    assert job["rowsImported"] == 0
    assert job["message"] == detail["message"]
    assert job["importError"]["reason"] == "NO_VALID_HOLDING_ROWS"
    assert job["importError"]["jobId"] == detail["jobId"]
    assert job["importError"]["observedHeaders"] == ["foo", "bar"]
    assert job["importError"]["rowPreview"][0]["cells"]["foo"] == "1"
    assert job["importError"]["brokerTemplateHint"]["brokerTemplateId"] == "generic_broker"


@pytest.mark.asyncio
async def test_import_portfolio_route_returns_broker_specific_repair_suggestions():
    upload = _BytesUpload("futu-malformed.csv", b"Stock Name,Market Value\nYinglian,1000\n")

    with pytest.raises(HTTPException) as exc:
        await routes_portfolio.import_portfolio(file=upload, source_name="moomoo export")

    detail = exc.value.detail
    assert exc.value.status_code == 400
    assert detail["reason"] == "NO_VALID_HOLDING_ROWS"
    assert detail["observedHeaders"] == ["Stock Name", "Market Value"]
    assert detail["matchedFields"] == ["marketValue", "name"]
    assert detail["missingRequiredFields"] == ["symbol", "shares"]
    assert detail["brokerTemplateHint"]["brokerTemplateId"] == "futu"
    assert detail["brokerTemplateHint"]["brokerTemplateLabel"] == "Futu/Moomoo broker export"
    assert detail["brokerTemplateHint"]["templateConfidence"] >= 0.6
    assert "Futu/Moomoo broker export" in detail["templateConfidenceNote"]
    assert "source hint matched" in detail["templateConfidenceNote"]
    assert any("Futu/Moomoo exports" in item and "Stock Code" in item for item in detail["repairSuggestions"])
    assert any("Futu/Moomoo exports" in item and "Quantity" in item for item in detail["repairSuggestions"])
    assert detail["rowPreview"] == [
        {"rowNumber": 2, "cells": {"Stock Name": "Yinglian", "Market Value": "1000"}}
    ]

    job = await get_import_job(detail["jobId"])
    assert job is not None
    assert job["importError"]["brokerTemplateHint"]["brokerTemplateId"] == "futu"
    assert job["importError"]["repairSuggestions"] == detail["repairSuggestions"]
