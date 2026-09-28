from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .technical_kline_agent import TECHNICAL_KLINE_CASE_CLASSIFICATIONS


STORAGE_FILE = Path(__file__).resolve().parents[1] / "storage" / "technical_kline_governance.json"
CASE_IMPACT_MINIMUM_SAMPLE_SIZE = 5
CASE_IMPACT_MINIMUM_SYMBOLS = 2
CASE_IMPACT_CLASSIFICATION_ORDER = ("valid", "misjudge", "insufficient_data")
LONG_WINDOW_REGRESSION_MINIMUM_CASES = 8
LONG_WINDOW_REGRESSION_MINIMUM_CONFIGS = 2
LONG_WINDOW_REGRESSION_MINIMUM_SYMBOLS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> Dict[str, Any]:
    return {
        "config": {},
        "case_classification": "",
        "updated_at": "",
        "updated_by": "",
        "change_reason": "",
        "cases": [],
        "audit_log": [],
    }


def _load_state() -> Dict[str, Any]:
    if not STORAGE_FILE.exists():
        return _default_state()
    try:
        data = json.loads(STORAGE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    if not isinstance(data, dict):
        return _default_state()
    state = _default_state()
    state.update(data)
    if not isinstance(state.get("config"), dict):
        state["config"] = {}
    if not isinstance(state.get("cases"), list):
        state["cases"] = []
    if not isinstance(state.get("audit_log"), list):
        state["audit_log"] = []
    return state


def _save_state(state: Dict[str, Any]) -> Dict[str, Any]:
    STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STORAGE_FILE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STORAGE_FILE)
    return state


def _merge_config(base: Dict[str, Any], override: Dict[str, Any] | None) -> Dict[str, Any]:
    merged = copy.deepcopy(base if isinstance(base, dict) else {})
    if not isinstance(override, dict):
        return merged
    for key, value in override.items():
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            current = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = _merge_config(current, value)
        else:
            merged[key] = value
    return merged


def active_governance_config(overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    state = _load_state()
    config = _merge_config(state.get("config") or {}, overrides)
    case_classification = ""
    if isinstance(overrides, dict):
        case_classification = str(overrides.get("caseClassification") or "").strip().lower()
    if not case_classification:
        case_classification = str(state.get("case_classification") or "").strip().lower()
    if case_classification in TECHNICAL_KLINE_CASE_CLASSIFICATIONS:
        config["caseClassification"] = case_classification
    return config


def public_governance_state(
    *,
    current_config_hash: str = "",
    current_prompt_version: str = "",
) -> Dict[str, Any]:
    state = _load_state()
    all_cases = [case for case in list(state.get("cases") or [])[-200:] if isinstance(case, dict)]
    cases = all_cases[-25:]
    return {
        "config": state.get("config") or {},
        "caseClassification": state.get("case_classification") or "",
        "updatedAt": state.get("updated_at") or "",
        "updatedBy": state.get("updated_by") or "",
        "changeReason": state.get("change_reason") or "",
        "cases": cases,
        "caseImpact": _case_impact_summary(
            all_cases,
            current_config_hash=current_config_hash,
            current_prompt_version=current_prompt_version,
        ),
        "auditLog": list(state.get("audit_log") or [])[-25:],
    }


def save_governance_config(
    config: Dict[str, Any],
    *,
    case_classification: str = "",
    changed_by: str = "frontend",
    change_reason: str = "",
) -> Dict[str, Any]:
    state = _load_state()
    updated_at = _now()
    next_classification = str(case_classification or "").strip().lower()
    if next_classification and next_classification not in TECHNICAL_KLINE_CASE_CLASSIFICATIONS:
        next_classification = ""
    state["config"] = _merge_config(state.get("config") or {}, config)
    state["case_classification"] = next_classification
    state["updated_at"] = updated_at
    state["updated_by"] = changed_by or "frontend"
    state["change_reason"] = change_reason or "Technical Kline governance parameters updated."
    state.setdefault("audit_log", []).append(
        {
            "event": "CONFIG_UPDATED",
            "createdAt": updated_at,
            "changedBy": state["updated_by"],
            "changeReason": state["change_reason"],
            "configHash": _hash_payload(state["config"]),
            "caseClassification": state["case_classification"],
        }
    )
    state["audit_log"] = state["audit_log"][-100:]
    return _save_state(state)


def rollback_governance_config(*, changed_by: str = "frontend", reason: str = "") -> Dict[str, Any]:
    state = _load_state()
    updated_at = _now()
    state["config"] = {}
    state["case_classification"] = ""
    state["updated_at"] = updated_at
    state["updated_by"] = changed_by or "frontend"
    state["change_reason"] = reason or "Rollback to default Technical Kline governance."
    state.setdefault("audit_log", []).append(
        {
            "event": "CONFIG_ROLLED_BACK",
            "createdAt": updated_at,
            "changedBy": state["updated_by"],
            "changeReason": state["change_reason"],
            "configHash": _hash_payload({}),
            "caseClassification": "",
        }
    )
    state["audit_log"] = state["audit_log"][-100:]
    return _save_state(state)


def record_case(case: Dict[str, Any]) -> Dict[str, Any]:
    state = _load_state()
    created_at = _now()
    classification = str(case.get("classification") or "").strip().lower()
    if classification not in TECHNICAL_KLINE_CASE_CLASSIFICATIONS:
        classification = "valid"
    case_id = _case_id(case, created_at)
    record = {
        "caseId": case_id,
        "symbol": str(case.get("symbol") or "").strip(),
        "classification": classification,
        "note": str(case.get("note") or "").strip(),
        "runId": str(case.get("run_id") or "").strip(),
        "analysisStatus": str(case.get("analysis_status") or "").strip(),
        "technicalBias": str(case.get("technical_bias") or "").strip(),
        "configHash": str(case.get("config_hash") or "").strip(),
        "promptVersion": str(case.get("prompt_version") or "").strip(),
        "createdAt": created_at,
    }
    state.setdefault("cases", []).append(record)
    state["cases"] = state["cases"][-200:]
    state.setdefault("audit_log", []).append(
        {
            "event": "CASE_RECORDED",
            "createdAt": created_at,
            "caseId": case_id,
            "classification": classification,
            "symbol": record["symbol"],
        }
    )
    state["audit_log"] = state["audit_log"][-100:]
    _save_state(state)
    return record


def link_case_library_case(
    technical_case_id: str,
    *,
    case_library_case_id: str = "",
    status: str = "MIRRORED",
    error: str = "",
) -> Dict[str, Any]:
    state = _load_state()
    updated_at = _now()
    case_library_case_id = str(case_library_case_id or "").strip()
    status = str(status or "MIRRORED").strip().upper()
    error = str(error or "").strip()
    linked_record: Dict[str, Any] = {}
    for record in state.get("cases") or []:
        if record.get("caseId") != technical_case_id:
            continue
        record["caseLibraryCaseId"] = case_library_case_id
        record["caseLibraryStatus"] = status
        if error:
            record["caseLibraryError"] = error[:240]
        else:
            record.pop("caseLibraryError", None)
        linked_record = dict(record)
        break
    if linked_record:
        state.setdefault("audit_log", []).append(
            {
                "event": "CASE_LIBRARY_LINKED" if case_library_case_id else "CASE_LIBRARY_LINK_FAILED",
                "createdAt": updated_at,
                "caseId": technical_case_id,
                "caseLibraryCaseId": case_library_case_id,
                "status": status,
            }
        )
        state["audit_log"] = state["audit_log"][-100:]
        _save_state(state)
        return linked_record
    return {}


def _empty_classification_counts() -> Dict[str, int]:
    return {classification: 0 for classification in CASE_IMPACT_CLASSIFICATION_ORDER}


def _case_rates(counts: Dict[str, int], total: int) -> Dict[str, float | None]:
    if total <= 0:
        return {
            "validRate": None,
            "misjudgeRate": None,
            "insufficientDataRate": None,
        }
    return {
        "validRate": round((counts.get("valid", 0) / total), 4),
        "misjudgeRate": round((counts.get("misjudge", 0) / total), 4),
        "insufficientDataRate": round((counts.get("insufficient_data", 0) / total), 4),
    }


def _case_impact_status(total: int) -> str:
    if total <= 0:
        return "NO_CASES"
    if total < CASE_IMPACT_MINIMUM_SAMPLE_SIZE:
        return "LOW_SAMPLE"
    return "READY"


def _representative_case_set_summary(
    *,
    total_cases: int,
    classification_counts: Dict[str, int],
    symbols: set[str],
) -> Dict[str, Any]:
    missing_classifications = [
        classification
        for classification in CASE_IMPACT_CLASSIFICATION_ORDER
        if int(classification_counts.get(classification, 0)) <= 0
    ]
    required_case_delta = max(CASE_IMPACT_MINIMUM_SAMPLE_SIZE - total_cases, 0)
    required_symbol_delta = max(CASE_IMPACT_MINIMUM_SYMBOLS - len(symbols), 0)
    if total_cases <= 0:
        status = "NO_CASES"
    elif required_case_delta or required_symbol_delta or missing_classifications:
        status = "LOW_COVERAGE"
    else:
        status = "READY"

    next_actions: List[str] = []
    if required_case_delta:
        next_actions.append(f"Add {required_case_delta} reviewed Technical Kline case(s).")
    if required_symbol_delta:
        next_actions.append(f"Add reviewed Technical Kline cases from {required_symbol_delta} additional symbol(s).")
    if missing_classifications:
        next_actions.append(
            "Add reviewed Technical Kline cases classified as: "
            + ", ".join(missing_classifications)
            + "."
        )
    if not next_actions:
        next_actions.append("Representative case set is ready for review-only parameter governance.")

    return {
        "policyId": "technical_kline_representative_case_set_v1",
        "status": status,
        "minimumReviewedCases": CASE_IMPACT_MINIMUM_SAMPLE_SIZE,
        "minimumSymbols": CASE_IMPACT_MINIMUM_SYMBOLS,
        "requiredClassifications": list(CASE_IMPACT_CLASSIFICATION_ORDER),
        "reviewedCaseCount": total_cases,
        "uniqueSymbolCount": len(symbols),
        "symbols": sorted(symbols)[:20],
        "missingClassifications": missing_classifications,
        "blocking": False,
        "action": "review_ready" if status == "READY" else "expand_representative_history",
        "boundary": "REVIEW_ONLY_NO_TRADE_ACTION",
        "remediation": {
            "requiredReviewedCaseDelta": required_case_delta,
            "requiredUniqueSymbolDelta": required_symbol_delta,
            "missingClassifications": missing_classifications,
            "nextActions": next_actions,
        },
    }


def _rate_delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None:
        return None
    return round(current - baseline, 4)


def _parameter_version_review_summary(
    *,
    current_config_hash: str,
    current_group: Dict[str, Any] | None,
    config_groups: List[Dict[str, Any]],
    representative_status: str,
) -> Dict[str, Any]:
    current_total = int(current_group.get("totalCases", 0)) if current_group else 0
    baseline_groups = [group for group in config_groups if group.get("configHash") != current_config_hash]
    baseline = baseline_groups[0] if baseline_groups else None

    if current_total <= 0:
        status = "NO_CURRENT_CONFIG_CASES"
        action = "record_current_config_cases"
    elif current_total < CASE_IMPACT_MINIMUM_SAMPLE_SIZE:
        status = "LOW_CURRENT_CONFIG_SAMPLE"
        action = "expand_current_config_cases"
    elif representative_status != "READY":
        status = "INCOMPLETE_REPRESENTATIVE_CASE_SET"
        action = "expand_representative_history"
    elif not baseline:
        status = "NO_BASELINE_CONFIG"
        action = "record_previous_or_baseline_config_cases"
    else:
        status = "READY_FOR_REVIEW"
        action = "review_parameter_version_delta"

    current_counts = dict(current_group.get("classificationCounts") or {}) if current_group else _empty_classification_counts()
    missing_current_classifications = [
        classification
        for classification in CASE_IMPACT_CLASSIFICATION_ORDER
        if int(current_counts.get(classification, 0)) <= 0
    ]
    comparison = None
    if current_group and baseline:
        comparison = {
            "baselineConfigHash": baseline.get("configHash") or "",
            "baselineCaseCount": int(baseline.get("totalCases") or 0),
            "validRateDelta": _rate_delta(current_group.get("validRate"), baseline.get("validRate")),
            "misjudgeRateDelta": _rate_delta(current_group.get("misjudgeRate"), baseline.get("misjudgeRate")),
            "insufficientDataRateDelta": _rate_delta(
                current_group.get("insufficientDataRate"),
                baseline.get("insufficientDataRate"),
            ),
        }

    return {
        "policyId": "technical_kline_parameter_version_review_v1",
        "status": status,
        "action": action,
        "currentConfigHash": current_config_hash,
        "currentConfigCaseCount": current_total,
        "currentConfigClassificationCounts": current_counts,
        "missingCurrentConfigClassifications": missing_current_classifications,
        "baselineConfigCount": len(baseline_groups),
        "comparison": comparison,
        "boundary": "REVIEW_ONLY_NO_TRADE_ACTION",
    }


def _long_window_regression_summary(
    *,
    total_cases: int,
    classification_counts: Dict[str, int],
    symbols: set[str],
    config_groups: List[Dict[str, Any]],
    current_config_hash: str,
    current_group: Dict[str, Any] | None,
    representative_status: str,
) -> Dict[str, Any]:
    config_count = len(config_groups)
    baseline_groups = [group for group in config_groups if group.get("configHash") != current_config_hash]
    baseline_case_count = sum(int(group.get("totalCases") or 0) for group in baseline_groups)
    current_case_count = int(current_group.get("totalCases") or 0) if current_group else 0
    missing_classifications = [
        classification
        for classification in CASE_IMPACT_CLASSIFICATION_ORDER
        if int(classification_counts.get(classification, 0)) <= 0
    ]
    required_case_delta = max(LONG_WINDOW_REGRESSION_MINIMUM_CASES - total_cases, 0)
    required_config_delta = max(LONG_WINDOW_REGRESSION_MINIMUM_CONFIGS - config_count, 0)
    required_symbol_delta = max(LONG_WINDOW_REGRESSION_MINIMUM_SYMBOLS - len(symbols), 0)

    if total_cases <= 0:
        status = "NO_CASES"
        action = "record_reviewed_long_window_cases"
    elif required_case_delta or required_config_delta or required_symbol_delta or missing_classifications:
        status = "LOW_COVERAGE"
        action = "expand_long_window_review_history"
    elif current_case_count <= 0:
        status = "NO_CURRENT_CONFIG_CASES"
        action = "record_current_config_long_window_cases"
    elif baseline_case_count <= 0:
        status = "NO_BASELINE_CONFIG"
        action = "retain_baseline_config_long_window_cases"
    elif representative_status != "READY":
        status = "INCOMPLETE_REPRESENTATIVE_CASE_SET"
        action = "expand_representative_history"
    else:
        status = "READY_FOR_REVIEW"
        action = "review_long_window_parameter_regression"

    next_actions: List[str] = []
    if required_case_delta:
        next_actions.append(f"Retain {required_case_delta} additional reviewed Technical Kline case(s).")
    if required_config_delta:
        next_actions.append(f"Retain reviewed cases from {required_config_delta} additional config version(s).")
    if required_symbol_delta:
        next_actions.append(f"Retain reviewed cases from {required_symbol_delta} additional symbol(s).")
    if missing_classifications:
        next_actions.append(
            "Retain reviewed long-window cases classified as: "
            + ", ".join(missing_classifications)
            + "."
        )
    if not next_actions:
        next_actions.append("Long-window reviewed-case regression is ready for review-only parameter governance.")

    return {
        "policyId": "technical_kline_long_window_regression_v1",
        "status": status,
        "action": action,
        "minimumReviewedCases": LONG_WINDOW_REGRESSION_MINIMUM_CASES,
        "minimumConfigVersions": LONG_WINDOW_REGRESSION_MINIMUM_CONFIGS,
        "minimumSymbols": LONG_WINDOW_REGRESSION_MINIMUM_SYMBOLS,
        "reviewedCaseCount": total_cases,
        "uniqueSymbolCount": len(symbols),
        "configVersionCount": config_count,
        "baselineConfigCount": len(baseline_groups),
        "currentConfigHash": current_config_hash,
        "currentConfigCaseCount": current_case_count,
        "baselineCaseCount": baseline_case_count,
        "retainedCaseLimit": 200,
        "symbols": sorted(symbols)[:20],
        "missingClassifications": missing_classifications,
        "windows": [
            {
                "label": "retained_review_history",
                "caseCount": total_cases,
                "scope": "last_200_governance_cases",
            },
            {
                "label": "current_config",
                "caseCount": current_case_count,
                "scope": current_config_hash or "UNKNOWN",
            },
            {
                "label": "baseline_configs",
                "caseCount": baseline_case_count,
                "scope": "all_non_current_retained_configs",
            },
        ],
        "blocking": False,
        "boundary": "REVIEW_ONLY_NO_TRADE_ACTION",
        "dataPolicy": "REVIEWED_REAL_TUSHARE_KLINE_CASES_ONLY",
        "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
        "remediation": {
            "requiredReviewedCaseDelta": required_case_delta,
            "requiredConfigVersionDelta": required_config_delta,
            "requiredUniqueSymbolDelta": required_symbol_delta,
            "missingClassifications": missing_classifications,
            "nextActions": next_actions,
        },
    }


def _case_impact_summary(
    cases: List[Dict[str, Any]],
    *,
    current_config_hash: str = "",
    current_prompt_version: str = "",
) -> Dict[str, Any]:
    total_counts = _empty_classification_counts()
    by_config: Dict[str, Dict[str, Any]] = {}
    total_cases = 0
    symbols: set[str] = set()

    for raw_case in cases:
        if not isinstance(raw_case, dict):
            continue
        classification = str(raw_case.get("classification") or "").strip().lower()
        if classification not in TECHNICAL_KLINE_CASE_CLASSIFICATIONS:
            classification = "valid"
        config_hash = str(raw_case.get("configHash") or "UNKNOWN").strip() or "UNKNOWN"
        prompt_version = str(raw_case.get("promptVersion") or "").strip()
        created_at = str(raw_case.get("createdAt") or "").strip()
        symbol = str(raw_case.get("symbol") or "").strip()
        total_cases += 1
        total_counts[classification] += 1
        if symbol:
            symbols.add(symbol)

        group = by_config.setdefault(
            config_hash,
            {
                "configHash": config_hash,
                "promptVersions": set(),
                "totalCases": 0,
                "classificationCounts": _empty_classification_counts(),
                "latestCaseAt": "",
            },
        )
        group["totalCases"] += 1
        group["classificationCounts"][classification] += 1
        if prompt_version:
            group["promptVersions"].add(prompt_version)
        if created_at and created_at > group["latestCaseAt"]:
            group["latestCaseAt"] = created_at

    config_groups: List[Dict[str, Any]] = []
    for group in by_config.values():
        total = int(group["totalCases"])
        counts = dict(group["classificationCounts"])
        config_groups.append(
            {
                "configHash": group["configHash"],
                "promptVersions": sorted(group["promptVersions"]),
                "totalCases": total,
                "classificationCounts": counts,
                "latestCaseAt": group["latestCaseAt"],
                **_case_rates(counts, total),
            }
        )

    config_groups.sort(key=lambda item: (item.get("latestCaseAt") or "", item.get("configHash") or ""), reverse=True)
    current_group = next((item for item in config_groups if item["configHash"] == current_config_hash), None)
    current_counts = dict(current_group["classificationCounts"]) if current_group else _empty_classification_counts()
    current_total = int(current_group["totalCases"]) if current_group else 0
    warnings: List[str] = []
    if total_cases and total_cases < CASE_IMPACT_MINIMUM_SAMPLE_SIZE:
        warnings.append("LOW_TECHNICAL_KLINE_CASE_SAMPLE")
    if total_cases and len(symbols) < CASE_IMPACT_MINIMUM_SYMBOLS:
        warnings.append("LOW_TECHNICAL_KLINE_SYMBOL_DIVERSITY")
    missing_classifications = [
        classification
        for classification in CASE_IMPACT_CLASSIFICATION_ORDER
        if int(total_counts.get(classification, 0)) <= 0
    ]
    for classification in missing_classifications:
        warnings.append(f"MISSING_TECHNICAL_KLINE_CLASSIFICATION:{classification}")
    if current_config_hash and total_cases and not current_group:
        warnings.append("CURRENT_CONFIG_HAS_NO_REVIEWED_CASES")
    representative_case_set = _representative_case_set_summary(
        total_cases=total_cases,
        classification_counts=total_counts,
        symbols=symbols,
    )
    long_window_regression = _long_window_regression_summary(
        total_cases=total_cases,
        classification_counts=total_counts,
        symbols=symbols,
        config_groups=config_groups,
        current_config_hash=current_config_hash,
        current_group=current_group,
        representative_status=str(representative_case_set.get("status") or ""),
    )
    if total_cases and long_window_regression.get("status") != "READY_FOR_REVIEW":
        warnings.append("LONG_WINDOW_REGRESSION_NOT_READY")

    return {
        "policy": {
            "policyId": "technical_kline_case_impact_review_v1",
            "usage": "REVIEW_ONLY_PARAMETER_GOVERNANCE",
            "minimumCasesForDecision": CASE_IMPACT_MINIMUM_SAMPLE_SIZE,
            "weakSampleAction": "supporting_only",
            "tradeActionPolicy": "NO_DIRECT_TRADE_ACTION",
        },
        "status": _case_impact_status(total_cases),
        "totalCases": total_cases,
        "classificationCounts": total_counts,
        **_case_rates(total_counts, total_cases),
        "currentConfig": {
            "configHash": current_config_hash,
            "promptVersion": current_prompt_version,
            "status": _case_impact_status(current_total),
            "caseCount": current_total,
            "classificationCounts": current_counts,
            **_case_rates(current_counts, current_total),
        },
        "byConfigHash": config_groups[:8],
        "representativeCaseSet": representative_case_set,
        "parameterVersionReview": _parameter_version_review_summary(
            current_config_hash=current_config_hash,
            current_group=current_group,
            config_groups=config_groups,
            representative_status=str(representative_case_set.get("status") or ""),
        ),
        "longWindowRegression": long_window_regression,
        "warnings": warnings,
    }


def _hash_payload(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _case_id(case: Dict[str, Any], created_at: str) -> str:
    seed = json.dumps(
        {
            "symbol": case.get("symbol"),
            "classification": case.get("classification"),
            "note": case.get("note"),
            "run_id": case.get("run_id"),
            "created_at": created_at,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"TKCASE_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12].upper()}"
