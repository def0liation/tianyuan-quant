from __future__ import annotations

import csv
import io
import uuid
from zipfile import BadZipFile, ZipFile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy import delete, select

from ..db.session import AsyncSessionLocal
from ..db import models as m
from ..models.portfolio import (
    HoldingPosition,
    HoldingValidationIssue,
    PortfolioSnapshot,
    PortfolioSnapshotSummary,
)


COLUMN_ALIASES = {
    "symbol": {"symbol", "code", "stock_code", "security_code", "secu_code", "ticker", "证券代码", "股票代码", "代码"},
    "name": {"name", "stock_name", "security_name", "secu_name", "stockname", "证券名称", "股票名称", "名称"},
    "shares": {"shares", "holding", "current_qty", "current_quantity", "position_qty", "quantity", "qty", "balance", "持股数量", "持有股数", "股份余额", "证券数量", "股数"},
    "availableShares": {"available_shares", "availableshares", "available_qty", "sellable_qty", "available", "可用股数", "可卖数量", "可用数量"},
    "costPrice": {"cost_price", "costprice", "book_cost", "avg_cost", "cost", "成本价", "持仓成本", "成本"},
    "marketValue": {"market_value", "marketvalue", "market_capital", "current_value", "value", "市值", "持仓市值", "最新市值"},
    "pnl": {"pnl", "profit", "profit_loss", "unrealized_pnl", "盈亏", "浮动盈亏", "持仓盈亏"},
    "industry": {"industry", "行业", "所属行业"},
    "style": {"style", "风格"},
    "theme": {"theme", "主题", "板块"},
    "riskFactor": {"risk_factor", "riskfactor", "risk", "风险因子", "同质风险"},
}

COLUMN_ALIASES["symbol"].update({"stock code", "security code"})
COLUMN_ALIASES["name"].update({"stock name", "security name"})
COLUMN_ALIASES["shares"].update({"position", "current qty", "position qty"})
COLUMN_ALIASES["availableShares"].update({"available qty", "available to sell", "sellable qty", "sellable"})
COLUMN_ALIASES["costPrice"].update({"cost price", "book cost", "avg cost", "avg price", "average_cost", "average cost", "cost basis"})
COLUMN_ALIASES["marketValue"].update({"market value", "market capital", "current value"})
COLUMN_ALIASES["pnl"].update({"p&l", "pl", "profit loss", "unrealized p/l", "unrealized pl", "unrealized gain/loss"})

MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 5_000
MAX_IMPORT_COLUMNS = 64
MAX_IMPORT_CELL_CHARS = 2_000
MAX_XLSX_EXPANDED_BYTES = 32 * 1024 * 1024
MAX_XLSX_ZIP_ENTRIES = 128


BROKER_SOURCE_HINTS = {
    "eastmoney": ("eastmoney", "east money", "dfcf", "dongfang", "dongcai"),
    "htsc": ("htsc", "huatai", "hua tai"),
    "gtja": ("gtja", "guotai", "jun'an", "junan", "guotai junan"),
    "futu": ("futu", "moomoo"),
    "tiger": ("tiger", "laohu"),
    "generic_broker": ("broker", "holdings", "positions", "portfolio"),
}

BROKER_TEMPLATE_LABELS = {
    "eastmoney": "Eastmoney broker export",
    "htsc": "Huatai Securities export",
    "gtja": "Guotai Junan Securities export",
    "futu": "Futu/Moomoo broker export",
    "tiger": "Tiger broker export",
    "generic_broker": "Generic broker holdings export",
    "generic_table": "Generic holdings table",
    "manual_entry": "Manual entry",
    "signalops_sim": "SignalOps simulation snapshot",
}

BROKER_TEMPLATE_REQUIRED_FIELDS = ("symbol", "shares")
BROKER_TEMPLATE_REVIEW_FIELDS = ("name", "availableShares", "costPrice", "marketValue")

GENERIC_REQUIRED_FIELD_REPAIR = {
    "symbol": "Add a security code column such as symbol, stock_code, Stock Code, or Security Code.",
    "shares": "Add a holding quantity column such as shares, quantity, position, current_qty, or Position.",
}

BROKER_TEMPLATE_REQUIRED_FIELD_REPAIR = {
    "eastmoney": {
        "symbol": "For Eastmoney exports, keep or rename the security code column to stock_code or symbol.",
        "shares": "For Eastmoney exports, keep or rename the holding quantity column to holding, current_qty, quantity, or shares.",
    },
    "htsc": {
        "symbol": "For Huatai/HTSC exports, keep or rename the security code column to secu_code, stock_code, or symbol.",
        "shares": "For Huatai/HTSC exports, keep or rename the balance/holding column to balance, quantity, holding, or shares.",
    },
    "gtja": {
        "symbol": "For Guotai Junan exports, keep or rename the security code column to security_code, stock_code, or symbol.",
        "shares": "For Guotai Junan exports, keep or rename the position quantity column to position_qty, quantity, Position, or shares.",
    },
    "futu": {
        "symbol": "For Futu/Moomoo exports, keep or rename the code column to Stock Code, Symbol, or stock_code.",
        "shares": "For Futu/Moomoo exports, keep or rename the position column to Quantity, Position, Available Qty, or shares.",
    },
    "tiger": {
        "symbol": "For Tiger exports, keep or rename the code column to Symbol, Stock Code, or stock_code.",
        "shares": "For Tiger exports, keep or rename the position column to Position, Available to Sell, Quantity, or shares.",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_header(value: Any) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _matched_import_fields(rows: Iterable[Dict[str, Any]]) -> set[str]:
    headers: set[str] = set()
    for row in rows:
        headers.update(str(key or "") for key in row.keys())
    normalized_headers = {_normalize_header(header) for header in headers if str(header or "").strip()}
    matched: set[str] = set()
    for field, aliases in COLUMN_ALIASES.items():
        alias_keys = {_normalize_header(alias) for alias in aliases}
        if normalized_headers.intersection(alias_keys):
            matched.add(field)
    return matched


def _source_hint_template_id(filename: str = "", source_name: str = "") -> str:
    source_text = f"{filename} {source_name}".lower()
    for candidate, hints in BROKER_SOURCE_HINTS.items():
        if any(hint in source_text for hint in hints):
            return candidate
    return ""


def _template_confidence_note(
    template: Dict[str, Any],
    matched_fields: list[str],
    missing_required: list[str],
    *,
    source_hint_matched: bool,
) -> str:
    label = str(template.get("brokerTemplateLabel") or template.get("brokerTemplateId") or "Unknown template")
    confidence = float(template.get("templateConfidence") or 0.0)
    matched_text = ", ".join(matched_fields) if matched_fields else "none"
    missing_text = ", ".join(missing_required) if missing_required else "none"
    hint_text = "source hint matched" if source_hint_matched else "no broker-specific source hint matched"
    return (
        f"{label} confidence {confidence:.0%}: {hint_text}; "
        f"matched fields: {matched_text}; missing required: {missing_text}."
    )


def _repair_suggestions(template_id: str, missing_required: list[str], matched_fields: list[str]) -> list[str]:
    suggestions: list[str] = []
    repair_map = BROKER_TEMPLATE_REQUIRED_FIELD_REPAIR.get(template_id, {})
    for field in missing_required:
        suggestion = repair_map.get(field) or GENERIC_REQUIRED_FIELD_REPAIR.get(field)
        if suggestion and suggestion not in suggestions:
            suggestions.append(suggestion)
    if not matched_fields:
        suggestions.append(
            "Rename broker export headers to the accepted aliases before importing; no Portfolio holding fields were recognized."
        )
    if template_id in {"generic_broker", "generic_table"}:
        suggestions.append(
            "Include the broker name in the upload file name or source name when using a known broker template."
        )
    return suggestions[:4]


def import_field_diagnostics(
    rows: Iterable[Dict[str, Any]],
    *,
    filename: str = "",
    source_name: str = "",
    source_type: str = "CSV",
) -> Dict[str, Any]:
    rows_list = list(rows)
    observed_headers: list[str] = []
    for row in rows_list:
        for key in row.keys():
            header = str(key or "").strip()
            if header and header not in observed_headers:
                observed_headers.append(header)

    matched_fields = sorted(_matched_import_fields(rows_list))
    missing_required = [
        field for field in BROKER_TEMPLATE_REQUIRED_FIELDS
        if field not in set(matched_fields)
    ]
    template = detect_broker_template(rows_list, filename=filename, source_name=source_name, source_type=source_type)
    template_id = str(template.get("brokerTemplateId") or "")
    source_hint_id = _source_hint_template_id(filename=filename, source_name=source_name)
    source_hint_matched = bool(source_hint_id and source_hint_id != "generic_broker")
    preview_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows_list[:3], start=2):
        cells: dict[str, str] = {}
        for key in observed_headers[:8]:
            value = str(row.get(key, "") or "")
            cells[key] = value[:80]
        preview_rows.append({"rowNumber": index, "cells": cells})

    return {
        "observedHeaders": observed_headers[:MAX_IMPORT_COLUMNS],
        "matchedFields": matched_fields,
        "missingRequiredFields": missing_required,
        "rowPreview": preview_rows,
        "brokerTemplateHint": {
            "brokerTemplateId": template_id,
            "brokerTemplateLabel": template.get("brokerTemplateLabel"),
            "templateConfidence": template.get("templateConfidence"),
            "templateWarnings": template.get("templateWarnings") or [],
        },
        "templateConfidenceNote": _template_confidence_note(
            template,
            matched_fields,
            missing_required,
            source_hint_matched=source_hint_matched,
        ),
        "repairSuggestions": _repair_suggestions(template_id, missing_required, matched_fields),
    }


def detect_broker_template(
    rows: Iterable[Dict[str, Any]],
    *,
    filename: str = "",
    source_name: str = "",
    source_type: str = "CSV",
) -> Dict[str, Any]:
    matched = _matched_import_fields(list(rows))
    template_id = _source_hint_template_id(filename=filename, source_name=source_name)
    if not template_id:
        template_id = "generic_broker" if set(BROKER_TEMPLATE_REQUIRED_FIELDS).issubset(matched) else "generic_table"

    missing_required = [field for field in BROKER_TEMPLATE_REQUIRED_FIELDS if field not in matched]
    missing_review = [field for field in BROKER_TEMPLATE_REVIEW_FIELDS if field not in matched]
    warnings: list[str] = []
    if missing_required:
        warnings.append("Required holding columns were not fully mapped: " + ", ".join(missing_required) + ".")
    if missing_review:
        warnings.append("Review broker template mapping for optional columns: " + ", ".join(missing_review) + ".")
    if template_id in {"generic_broker", "generic_table"}:
        warnings.append("No broker-specific source hint matched; generic column aliases were used.")

    review_hits = len([field for field in BROKER_TEMPLATE_REVIEW_FIELDS if field in matched])
    required_hits = len([field for field in BROKER_TEMPLATE_REQUIRED_FIELDS if field in matched])
    base = 0.35 + 0.2 * required_hits + 0.08 * review_hits
    if template_id not in {"generic_broker", "generic_table"}:
        base += 0.12
    confidence = round(max(0.0, min(base, 0.98)), 2)
    if source_type.upper() == "MANUAL":
        return {
            "brokerTemplateId": "manual_entry",
            "brokerTemplateLabel": BROKER_TEMPLATE_LABELS["manual_entry"],
            "templateConfidence": 1.0,
            "templateWarnings": [],
        }
    if source_type.upper() == "SIGNALOPS_SIM":
        return {
            "brokerTemplateId": "signalops_sim",
            "brokerTemplateLabel": BROKER_TEMPLATE_LABELS["signalops_sim"],
            "templateConfidence": 1.0,
            "templateWarnings": [],
        }
    return {
        "brokerTemplateId": template_id,
        "brokerTemplateLabel": BROKER_TEMPLATE_LABELS.get(template_id, template_id),
        "templateConfidence": confidence,
        "templateWarnings": warnings,
    }


def _broker_template_fields(raw: Dict[str, Any] | None, source_type: str) -> Dict[str, Any]:
    raw = raw or {}
    fallback = detect_broker_template([], source_type=source_type)
    return {
        "brokerTemplateId": raw.get("brokerTemplateId") or fallback["brokerTemplateId"],
        "brokerTemplateLabel": raw.get("brokerTemplateLabel") or fallback["brokerTemplateLabel"],
        "templateConfidence": raw.get("templateConfidence", fallback["templateConfidence"]),
        "templateWarnings": raw.get("templateWarnings") or fallback["templateWarnings"],
    }


def _portfolio_evidence_strength(
    *,
    source_type: str,
    position_count: int,
    quality_status: str,
    issue_count: int,
    template_confidence: float,
) -> str:
    if position_count <= 0:
        return "MISSING"
    normalized_quality = str(quality_status or "").upper()
    if normalized_quality not in {"OK", "READY", "PASS", "HEALTHY", "VALID"} or issue_count > 0:
        return "LOW"
    normalized_source = str(source_type or "").upper()
    if normalized_source in {"SAMPLE", "SIGNALOPS_SIM"}:
        return "LOW"
    if normalized_source in {"CSV", "XLSX", "TSV", "IMPORTED"} and template_confidence < 0.8:
        return "LOW"
    return "MEDIUM"


def _portfolio_boundary_fields(
    *,
    source_type: str,
    position_count: int,
    quality_status: str,
    issue_count: int,
    template_confidence: float,
) -> Dict[str, Any]:
    return {
        "evidenceUsage": "supporting_only",
        "evidenceStrength": _portfolio_evidence_strength(
            source_type=source_type,
            position_count=position_count,
            quality_status=quality_status,
            issue_count=issue_count,
            template_confidence=template_confidence,
        ),
        "simulationOnly": True,
        "isRealTrade": False,
        "strongConclusionAllowed": False,
    }


def normalize_symbol(value: Any) -> str:
    text = str(value or "").strip().upper()
    if "." in text:
        return text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _pick(row: Dict[str, Any], key: str) -> Any:
    aliases = COLUMN_ALIASES[key]
    normalized = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        if alias.lower() in normalized:
            return normalized[alias.lower()]
    compact = {_normalize_header(k): v for k, v in row.items()}
    for alias in aliases:
        alias_key = _normalize_header(alias)
        if alias_key in compact:
            return compact[alias_key]
    return ""


def decode_table(raw: bytes, filename: str) -> Tuple[List[Dict[str, Any]], str]:
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_BYTES} byte limit.")
    lower = filename.lower()
    if lower.endswith(".xlsx"):
        return _decode_xlsx(raw), "xlsx"
    if lower.endswith(".xls"):
        raise ValueError("Legacy .xls import is not enabled. Please save the file as .xlsx or CSV.")
    delimiter = "\t" if lower.endswith(".tsv") else ","
    for encoding in ("utf-8-sig", "gbk", "utf-16"):
        try:
            text = raw.decode(encoding)
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            if reader.fieldnames and len(reader.fieldnames) > MAX_IMPORT_COLUMNS:
                raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_COLUMNS} column limit.")
            records: List[Dict[str, Any]] = []
            for row_number, row in enumerate(reader, start=2):
                if len(records) >= MAX_IMPORT_ROWS:
                    raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_ROWS} row limit.")
                records.append(_bounded_record(dict(row), row_number=row_number))
            return records, encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode file. Please use UTF-8 or GBK CSV.")


def _decode_xlsx(raw: bytes) -> List[Dict[str, Any]]:
    # Shared strings and workbook metadata load before row iteration limits.
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_XLSX_ZIP_ENTRIES:
                raise ValueError(f"XLSX archive exceeds the {MAX_XLSX_ZIP_ENTRIES} entry limit.")
            if sum(entry.file_size for entry in entries) > MAX_XLSX_EXPANDED_BYTES:
                raise ValueError(f"XLSX archive exceeds the {MAX_XLSX_EXPANDED_BYTES} expanded byte limit.")
    except BadZipFile as exc:
        raise ValueError("Invalid XLSX archive. Please export a valid workbook or CSV.") from exc

    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError("XLSX import requires openpyxl. Please install backend requirements or export CSV.") from exc

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        row_iter = worksheet.iter_rows(values_only=True)
        header_values = next(row_iter, None)
        if not header_values:
            return []
        headers = [str(value or "").strip() for value in header_values]
        if not any(headers):
            return []
        if len(headers) > MAX_IMPORT_COLUMNS:
            raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_COLUMNS} column limit.")

        records: List[Dict[str, Any]] = []
        for row_number, values in enumerate(row_iter, start=2):
            if not any(value not in (None, "") for value in values):
                continue
            if len(records) >= MAX_IMPORT_ROWS:
                raise ValueError(f"Portfolio import exceeds the {MAX_IMPORT_ROWS} row limit.")
            row = {headers[index]: value for index, value in enumerate(values) if index < len(headers)}
            records.append(_bounded_record(row, row_number=row_number))
        return records
    finally:
        workbook.close()


def _bounded_record(row: Dict[str, Any], *, row_number: int) -> Dict[str, Any]:
    if None in row:
        raise ValueError(f"Portfolio import row {row_number} exceeds the declared column count.")
    if len(row) > MAX_IMPORT_COLUMNS:
        raise ValueError(f"Portfolio import row {row_number} exceeds the {MAX_IMPORT_COLUMNS} column limit.")
    for key, value in row.items():
        if len(str(key or "")) > MAX_IMPORT_CELL_CHARS:
            raise ValueError(f"Portfolio import row {row_number} has a header over {MAX_IMPORT_CELL_CHARS} characters.")
        if len(str(value or "")) > MAX_IMPORT_CELL_CHARS:
            raise ValueError(f"Portfolio import row {row_number} has a cell over {MAX_IMPORT_CELL_CHARS} characters.")
    return row


def positions_from_rows(rows: Iterable[Dict[str, Any]]) -> Tuple[List[HoldingPosition], List[HoldingValidationIssue]]:
    positions: List[HoldingPosition] = []
    issues: List[HoldingValidationIssue] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        symbol = normalize_symbol(_pick(row, "symbol"))
        name = str(_pick(row, "name") or "").strip()
        shares = parse_number(_pick(row, "shares"))
        available = parse_number(_pick(row, "availableShares"))
        cost = parse_number(_pick(row, "costPrice"))
        market_value = parse_number(_pick(row, "marketValue"))
        pnl = parse_number(_pick(row, "pnl"))

        if not symbol:
            issues.append(HoldingValidationIssue(rowNumber=index, field="symbol", level="ERROR", message="Missing stock symbol."))
            continue
        if symbol in seen:
            issues.append(HoldingValidationIssue(rowNumber=index, symbol=symbol, field="symbol", level="WARN", message="Duplicate symbol; rows are kept separately."))
        seen.add(symbol)
        if shares <= 0:
            issues.append(HoldingValidationIssue(rowNumber=index, symbol=symbol, field="shares", level="WARN", message="Shares are zero or missing."))
        if cost <= 0:
            issues.append(HoldingValidationIssue(rowNumber=index, symbol=symbol, field="costPrice", level="WARN", message="Cost price is zero or missing."))
        if market_value <= 0 and shares > 0 and cost > 0:
            market_value = shares * cost
            issues.append(HoldingValidationIssue(rowNumber=index, symbol=symbol, field="marketValue", level="INFO", message="Market value was estimated from shares and cost price."))

        positions.append(
            HoldingPosition(
                symbol=symbol,
                name=name,
                shares=shares,
                availableShares=available,
                costPrice=cost,
                marketValue=market_value,
                pnl=pnl,
                industry=str(_pick(row, "industry") or "").strip(),
                style=str(_pick(row, "style") or "").strip(),
                theme=str(_pick(row, "theme") or "").strip(),
                riskFactor=str(_pick(row, "riskFactor") or "").strip(),
                updatedAt=now_iso(),
                raw=row,
            )
        )
    return positions, issues


def build_snapshot(
    positions: List[HoldingPosition],
    issues: List[HoldingValidationIssue],
    source_type: str,
    source_name: str,
    account_name: str = "",
    cash: float = 0.0,
    available_cash: float = 0.0,
    total_assets: float = 0.0,
    broker_template_id: str = "",
    broker_template_label: str = "",
    template_confidence: float | None = None,
    template_warnings: List[str] | None = None,
) -> PortfolioSnapshot:
    stock_market_value = sum(max(0.0, p.marketValue) for p in positions)
    total_assets = total_assets or stock_market_value + max(0.0, cash)
    for position in positions:
        position.weight = round(position.marketValue / total_assets, 6) if total_assets > 0 else 0.0
    total_position = round(stock_market_value / total_assets, 6) if total_assets > 0 else 0.0
    quality = "ERROR" if any(i.level == "ERROR" for i in issues) else "WARN" if issues else "OK"
    timestamp = now_iso()
    default_template = detect_broker_template([], source_type=source_type)
    resolved_template_confidence = round(
        max(0.0, min(float(default_template["templateConfidence"] if template_confidence is None else template_confidence), 1.0)),
        2,
    )
    return PortfolioSnapshot(
        snapshotId=f"PF_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}",
        sourceType=source_type,
        sourceName=source_name,
        accountName=account_name,
        totalAssets=round(total_assets, 4),
        cash=round(cash, 4),
        stockMarketValue=round(stock_market_value, 4),
        availableCash=round(available_cash, 4),
        totalPositionRatio=total_position,
        maxSinglePositionRatio=max((p.weight for p in positions), default=0.0),
        positionCount=len(positions),
        qualityStatus=quality,
        issueCount=len(issues),
        brokerTemplateId=broker_template_id or default_template["brokerTemplateId"],
        brokerTemplateLabel=broker_template_label or default_template["brokerTemplateLabel"],
        templateConfidence=resolved_template_confidence,
        templateWarnings=template_warnings if template_warnings is not None else default_template["templateWarnings"],
        **_portfolio_boundary_fields(
            source_type=source_type,
            position_count=len(positions),
            quality_status=quality,
            issue_count=len(issues),
            template_confidence=resolved_template_confidence,
        ),
        importedAt=timestamp,
        updatedAt=timestamp,
        positions=positions,
        issues=issues,
    )


async def save_import_job(
    job_id: str,
    filename: str,
    status: str,
    snapshot: PortfolioSnapshot | None,
    message: str,
    source_type: str = "CSV",
    import_error: Dict[str, Any] | None = None,
) -> None:
    raw_json = snapshot.model_dump() if snapshot else {}
    if snapshot is None and import_error:
        raw_json = {"importError": import_error}
    async with AsyncSessionLocal() as db:
        db.add(
            m.HoldingImportJobDB(
                job_id=job_id,
                snapshot_id=snapshot.snapshotId if snapshot else None,
                filename=filename,
                source_type=source_type,
                status=status,
                rows_total=len(snapshot.positions) + len(snapshot.issues) if snapshot else 0,
                rows_imported=len(snapshot.positions) if snapshot else 0,
                issue_count=len(snapshot.issues) if snapshot else 0,
                message=message,
                raw_json=raw_json,
            )
        )
        await db.commit()


async def get_import_job(job_id: str) -> Dict[str, Any] | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(m.HoldingImportJobDB).where(m.HoldingImportJobDB.job_id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            return None
        broker_template = _broker_template_fields(job.raw_json if isinstance(job.raw_json, dict) else {}, job.source_type or "CSV")
        import_error = (job.raw_json or {}).get("importError") if isinstance(job.raw_json, dict) else None
        return {
            "jobId": job.job_id,
            "snapshotId": job.snapshot_id,
            "filename": job.filename,
            "sourceType": job.source_type,
            "status": job.status,
            "rowsTotal": job.rows_total or 0,
            "rowsImported": job.rows_imported or 0,
            "issueCount": job.issue_count or 0,
            **broker_template,
            "message": job.message,
            "importError": import_error if isinstance(import_error, dict) else None,
            "createdAt": job.created_at,
        }


async def save_snapshot(snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(m.HoldingPositionDB).where(m.HoldingPositionDB.snapshot_id == snapshot.snapshotId))
        await db.execute(delete(m.HoldingValidationIssueDB).where(m.HoldingValidationIssueDB.snapshot_id == snapshot.snapshotId))
        record = m.PortfolioSnapshotDB(
            snapshot_id=snapshot.snapshotId,
            source_type=snapshot.sourceType,
            source_name=snapshot.sourceName,
            account_name=snapshot.accountName,
            total_assets=snapshot.totalAssets,
            cash=snapshot.cash,
            stock_market_value=snapshot.stockMarketValue,
            available_cash=snapshot.availableCash,
            total_position_ratio=snapshot.totalPositionRatio,
            max_single_position_ratio=snapshot.maxSinglePositionRatio,
            position_count=snapshot.positionCount,
            quality_status=snapshot.qualityStatus,
            issue_count=snapshot.issueCount,
            imported_at=snapshot.importedAt,
            updated_at=snapshot.updatedAt,
            raw_json=snapshot.model_dump(),
        )
        db.add(record)
        db.add_all(
            [
                m.HoldingPositionDB(
                    snapshot_id=snapshot.snapshotId,
                    symbol=p.symbol,
                    name=p.name,
                    shares=p.shares,
                    available_shares=p.availableShares,
                    cost_price=p.costPrice,
                    market_value=p.marketValue,
                    pnl=p.pnl,
                    industry=p.industry,
                    style=p.style,
                    theme=p.theme,
                    risk_factor=p.riskFactor,
                    weight=p.weight,
                    updated_at=p.updatedAt,
                    raw_json=p.raw,
                )
                for p in snapshot.positions
            ]
        )
        db.add_all(
            [
                m.HoldingValidationIssueDB(
                    snapshot_id=snapshot.snapshotId,
                    row_number=i.rowNumber,
                    symbol=i.symbol,
                    field=i.field,
                    level=i.level,
                    message=i.message,
                )
                for i in snapshot.issues
            ]
        )
        await db.commit()
    return snapshot


async def list_snapshots() -> List[PortfolioSnapshotSummary]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(m.PortfolioSnapshotDB).order_by(m.PortfolioSnapshotDB.imported_at.desc()))
        records = result.scalars().all()
        return [
            PortfolioSnapshotSummary(
                snapshotId=r.snapshot_id,
                sourceType=r.source_type,
                sourceName=r.source_name,
                accountName=r.account_name,
                totalAssets=r.total_assets or 0,
                stockMarketValue=r.stock_market_value or 0,
                cash=r.cash or 0,
                totalPositionRatio=r.total_position_ratio or 0,
                maxSinglePositionRatio=r.max_single_position_ratio or 0,
                positionCount=r.position_count or 0,
                qualityStatus=r.quality_status,
                issueCount=r.issue_count or 0,
                **_broker_template_fields(r.raw_json if isinstance(r.raw_json, dict) else {}, r.source_type or "MANUAL"),
                **_portfolio_boundary_fields(
                    source_type=r.source_type or "MANUAL",
                    position_count=r.position_count or 0,
                    quality_status=r.quality_status or "",
                    issue_count=r.issue_count or 0,
                    template_confidence=float(
                        _broker_template_fields(r.raw_json if isinstance(r.raw_json, dict) else {}, r.source_type or "MANUAL").get("templateConfidence", 0)
                    ),
                ),
                importedAt=r.imported_at,
                updatedAt=r.updated_at,
            )
            for r in records
        ]


async def get_snapshot(snapshot_id: str) -> PortfolioSnapshot | None:
    async with AsyncSessionLocal() as db:
        snap_result = await db.execute(select(m.PortfolioSnapshotDB).where(m.PortfolioSnapshotDB.snapshot_id == snapshot_id))
        snap = snap_result.scalar_one_or_none()
        if snap is None:
            return None
        pos_result = await db.execute(select(m.HoldingPositionDB).where(m.HoldingPositionDB.snapshot_id == snapshot_id))
        issue_result = await db.execute(select(m.HoldingValidationIssueDB).where(m.HoldingValidationIssueDB.snapshot_id == snapshot_id))
        positions = [
            HoldingPosition(
                symbol=p.symbol,
                name=p.name,
                shares=p.shares or 0,
                availableShares=p.available_shares or 0,
                costPrice=p.cost_price or 0,
                marketValue=p.market_value or 0,
                pnl=p.pnl or 0,
                industry=p.industry or "",
                style=p.style or "",
                theme=p.theme or "",
                riskFactor=p.risk_factor or "",
                weight=p.weight or 0,
                updatedAt=p.updated_at or "",
                raw=p.raw_json or {},
            )
            for p in pos_result.scalars().all()
        ]
        issues = [
            HoldingValidationIssue(
                rowNumber=i.row_number or 0,
                symbol=i.symbol or "",
                field=i.field or "",
                level=i.level or "WARN",
                message=i.message or "",
            )
            for i in issue_result.scalars().all()
        ]
        broker_template = _broker_template_fields(snap.raw_json if isinstance(snap.raw_json, dict) else {}, snap.source_type or "MANUAL")
        return PortfolioSnapshot(
            snapshotId=snap.snapshot_id,
            sourceType=snap.source_type,
            sourceName=snap.source_name,
            accountName=snap.account_name,
            totalAssets=snap.total_assets or 0,
            cash=snap.cash or 0,
            stockMarketValue=snap.stock_market_value or 0,
            availableCash=snap.available_cash or 0,
            totalPositionRatio=snap.total_position_ratio or 0,
            maxSinglePositionRatio=snap.max_single_position_ratio or 0,
            positionCount=snap.position_count or 0,
            qualityStatus=snap.quality_status,
            issueCount=snap.issue_count or 0,
            **broker_template,
            **_portfolio_boundary_fields(
                source_type=snap.source_type or "MANUAL",
                position_count=snap.position_count or 0,
                quality_status=snap.quality_status or "",
                issue_count=snap.issue_count or 0,
                template_confidence=float(broker_template.get("templateConfidence", 0)),
            ),
            importedAt=snap.imported_at,
            updatedAt=snap.updated_at,
            positions=positions,
            issues=issues,
        )


async def delete_snapshot(snapshot_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(delete(m.PortfolioSnapshotDB).where(m.PortfolioSnapshotDB.snapshot_id == snapshot_id))
        await db.execute(delete(m.HoldingPositionDB).where(m.HoldingPositionDB.snapshot_id == snapshot_id))
        await db.execute(delete(m.HoldingValidationIssueDB).where(m.HoldingValidationIssueDB.snapshot_id == snapshot_id))
        await db.commit()
        return bool(result.rowcount)
