from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..core.portfolio_store import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_CELL_CHARS,
    MAX_IMPORT_COLUMNS,
    MAX_IMPORT_ROWS,
    build_snapshot,
    decode_table,
    detect_broker_template,
    get_import_job,
    get_snapshot,
    import_field_diagnostics,
    list_snapshots,
    positions_from_rows,
    delete_snapshot,
    save_import_job,
    save_snapshot,
)
from ..models.portfolio import (
    HoldingImportJob,
    HoldingImportResponse,
    ManualPortfolioRequest,
    PortfolioSnapshot,
    PortfolioSnapshotSummary,
)


router = APIRouter()


PORTFOLIO_IMPORT_REQUIRED_COLUMNS = [
    "symbol / stock_code / Stock Code / Security Code",
    "shares / quantity / position / current_qty",
]
PORTFOLIO_IMPORT_RECOMMENDED_COLUMNS = [
    "name / stock_name / Stock Name",
    "available_shares / available_qty / Available to Sell",
    "cost_price / avg_cost / Average Cost",
    "market_value / Market Value",
    "pnl / profit_loss / P&L",
]
PORTFOLIO_IMPORT_ACCEPTED_EXTENSIONS = [".csv", ".tsv", ".xlsx"]


def _portfolio_import_error_reason(message: str) -> str:
    text = message.lower()
    if "byte limit" in text:
        return "FILE_TOO_LARGE"
    if "row limit" in text:
        return "TOO_MANY_ROWS"
    if "column limit" in text or "declared column count" in text:
        return "COLUMN_LIMIT_OR_MISMATCH"
    if "cell" in text or "header" in text:
        return "CELL_TOO_LARGE"
    if "decode" in text:
        return "UNSUPPORTED_ENCODING"
    if "legacy .xls" in text:
        return "LEGACY_XLS_UNSUPPORTED"
    if "xlsx import requires openpyxl" in text:
        return "XLSX_READER_UNAVAILABLE"
    if "no valid holding rows" in text:
        return "NO_VALID_HOLDING_ROWS"
    return "IMPORT_VALIDATION_ERROR"


def _portfolio_import_error_detail(
    message: str,
    job_id: str,
    filename: str,
    rows: list[dict] | None = None,
    *,
    source_name: str = "",
    source_type: str = "UNKNOWN",
) -> dict:
    detail = {
        "message": message,
        "jobId": job_id,
        "filename": filename,
        "reason": _portfolio_import_error_reason(message),
        "acceptedExtensions": PORTFOLIO_IMPORT_ACCEPTED_EXTENSIONS,
        "expectedColumns": {
            "required": PORTFOLIO_IMPORT_REQUIRED_COLUMNS,
            "recommended": PORTFOLIO_IMPORT_RECOMMENDED_COLUMNS,
        },
        "limits": {
            "maxBytes": MAX_IMPORT_BYTES,
            "maxRows": MAX_IMPORT_ROWS,
            "maxColumns": MAX_IMPORT_COLUMNS,
            "maxCellChars": MAX_IMPORT_CELL_CHARS,
        },
    }
    if rows:
        detail.update(import_field_diagnostics(rows, filename=filename, source_name=source_name, source_type=source_type))
    return detail


@router.post("/portfolio/imports", response_model=HoldingImportResponse)
async def import_portfolio(
    file: UploadFile = File(...),
    source_name: str = Form("uploaded-file"),
    account_name: str = Form(""),
    cash: float = Form(0.0),
    available_cash: float = Form(0.0),
    total_assets: float = Form(0.0),
):
    job_id = f"IMP_{uuid.uuid4().hex[:12]}"
    filename = file.filename or "holdings.csv"
    rows: list[dict] = []
    source_type = "UNKNOWN"
    try:
        raw = await file.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_BYTES} byte limit.")
        rows, encoding = decode_table(raw, filename)
        source_type = "XLSX" if encoding == "xlsx" else "CSV"
        broker_template = detect_broker_template(rows, filename=filename, source_name=source_name, source_type=source_type)
        positions, issues = positions_from_rows(rows)
        if not positions:
            raise ValueError("No valid holding rows found. Please check symbol and shares columns.")
        snapshot = build_snapshot(
            positions=positions,
            issues=issues,
            source_type=source_type,
            source_name=f"{source_name} ({filename}, {encoding})",
            account_name=account_name,
            cash=cash,
            available_cash=available_cash,
            total_assets=total_assets,
            broker_template_id=broker_template["brokerTemplateId"],
            broker_template_label=broker_template["brokerTemplateLabel"],
            template_confidence=broker_template["templateConfidence"],
            template_warnings=broker_template["templateWarnings"],
        )
        await save_snapshot(snapshot)
        await save_import_job(job_id, filename, "COMPLETED", snapshot, "Imported holdings snapshot.", source_type)
        return HoldingImportResponse(jobId=job_id, status="COMPLETED", message="Imported holdings snapshot.", snapshot=snapshot)
    except ValueError as exc:
        detail = _portfolio_import_error_detail(
            str(exc),
            job_id,
            filename,
            rows,
            source_name=source_name,
            source_type=source_type,
        )
        await save_import_job(job_id, filename, "FAILED", None, str(exc), "UNKNOWN", import_error=detail)
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        detail = _portfolio_import_error_detail(
            "Portfolio import failed.",
            job_id,
            filename,
            rows,
            source_name=source_name,
            source_type=source_type,
        )
        detail["reason"] = "INTERNAL_IMPORT_ERROR"
        await save_import_job(job_id, filename, "FAILED", None, "Portfolio import failed.", "UNKNOWN", import_error=detail)
        raise HTTPException(status_code=500, detail=detail) from exc


@router.get("/portfolio/imports/{job_id}", response_model=HoldingImportJob)
async def get_portfolio_import_job(job_id: str):
    job = await get_import_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Portfolio import job not found")
    return job


@router.post("/portfolio/manual", response_model=PortfolioSnapshot)
async def create_manual_portfolio(request: ManualPortfolioRequest):
    positions, issues = positions_from_rows(position.model_dump() for position in request.positions)
    if not positions:
        raise HTTPException(status_code=400, detail="No valid holding rows found. Please check symbol and shares fields.")
    snapshot = build_snapshot(
        positions=positions,
        issues=issues,
        source_type="MANUAL",
        source_name=request.sourceName,
        account_name=request.accountName,
        cash=request.cash,
        available_cash=request.availableCash,
        total_assets=request.totalAssets,
    )
    return await save_snapshot(snapshot)


@router.get("/portfolio/snapshots", response_model=list[PortfolioSnapshotSummary])
async def get_portfolio_snapshots():
    return await list_snapshots()


@router.get("/portfolio/snapshots/{snapshot_id}", response_model=PortfolioSnapshot)
async def get_portfolio_snapshot(snapshot_id: str):
    snapshot = await get_snapshot(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Portfolio snapshot not found")
    return snapshot


@router.delete("/portfolio/snapshots/{snapshot_id}")
async def delete_portfolio_snapshot(snapshot_id: str):
    deleted = await delete_snapshot(snapshot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Portfolio snapshot not found")
    return {"deleted": snapshot_id}
