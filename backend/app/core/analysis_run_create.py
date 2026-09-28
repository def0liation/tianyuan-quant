from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from ..models.knowledge import ActiveKnowledgeContextItem
from ..models.portfolio import PortfolioSnapshot
from .quant_engine_modes import quant_engine_profile

GetSnapshot = Callable[[str], Awaitable[Any]]
HydrateRunWithMarketData = Callable[[dict, str], Awaitable[dict]]
ApplyAgentFramework = Callable[[dict, dict, dict], dict]
NormalizeSymbol = Callable[[str], str]


class AnalysisRunCreateError(Exception):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class AnalysisRunCreateNotFound(AnalysisRunCreateError):
    status_code = 404


async def build_created_run(
    *,
    request: Any,
    run_id: str,
    research_loop_id: str | None,
    scenario_template: dict,
    runtime_summary: dict,
    knowledge_context: list | dict,
    get_snapshot: GetSnapshot,
    normalize_symbol: NormalizeSymbol,
    hydrate_run_with_market_data: HydrateRunWithMarketData,
    apply_agent_framework_to_run: ApplyAgentFramework,
) -> dict:
    scenario_data = real_run_seed(scenario_template)
    quant_engine = quant_engine_profile(request.quant_engine_mode, request.task_type)
    safe_knowledge_context = _sanitize_knowledge_context(knowledge_context)
    user_position = _user_position_from_constraints(
        scenario_data.get("userPosition", {}),
        request.user_constraints or {},
    )
    now = datetime.now().isoformat()
    run_data = {
        **scenario_data,
        "runId": run_id,
        "auditId": f"AUD_{run_id}",
        "runMode": request.run_mode,
        "environment": "API_ORCHESTRATED",
        "stockCode": request.symbol,
        "taskType": request.task_type,
        "quantEngine": quant_engine,
        "bottomResearchConfig": request.bottom_research_config or {},
        "userPosition": user_position,
        "agentRuntime": runtime_summary,
        "knowledgeContext": safe_knowledge_context,
        "createdAt": now,
        "updatedAt": now,
        "status": "CREATED",
        "job": None,
    }

    portfolio_audit_event = await _attach_portfolio_snapshot_if_requested(
        run_data,
        request=request,
        run_id=run_id,
        user_position=user_position,
        get_snapshot=get_snapshot,
        normalize_symbol=normalize_symbol,
    )
    _apply_add_position_constraints(run_data, user_position)

    run_data = await hydrate_run_with_market_data(run_data, request.symbol)
    run_data = apply_agent_framework_to_run(
        run_data,
        request.model_dump(),
        runtime_summary,
    )
    if portfolio_audit_event:
        run_data.setdefault("auditLog", []).append(portfolio_audit_event)

    run_data["agentOutputs"] = {}
    run_data["llmTrace"] = []
    run_data["streamEvents"] = [_created_run_simulation_boundary_event(run_id, now)]
    if research_loop_id or request.research_iteration_id:
        run_data["rdResearch"] = {
            "loopId": research_loop_id,
            "iterationId": request.research_iteration_id,
            "status": "RUN_CREATED",
            "stage": "RUN_CREATED",
            "linkedRunId": run_id,
            "source": {
                "mode": "LOCAL_SUPER_WORKFLOW",
                "inspiredBy": "microsoft/RD-Agent",
            },
        }
    return run_data


def _sanitize_knowledge_context(knowledge_context: list | dict) -> list[dict[str, Any]]:
    if not isinstance(knowledge_context, list):
        return []

    sanitized: list[dict[str, Any]] = []
    for item in knowledge_context:
        if not isinstance(item, dict):
            continue
        try:
            sanitized.append(ActiveKnowledgeContextItem(**item).model_dump())
        except ValueError:
            continue
    return sanitized


def _created_run_simulation_boundary_event(run_id: str, created_at: str) -> dict:
    return {
        "event_type": "RUN_CREATED",
        "run_id": run_id,
        "node_id": "system",
        "message": "Analysis run created in local simulation-only mode.",
        "payload": {
            "simulation_only": True,
            "is_real_trade": False,
            "allowed_order_namespace": "SIM_*",
        },
        "audit_id": f"AUD_CREATE_{run_id}",
        "timestamp": created_at,
    }


def _pending_paper_trading_boundary() -> dict:
    return {
        "status": "PENDING",
        "observationPeriod": 14,
        "entryAssumptions": [],
        "invalidationConditions": [],
        "trackedSymbols": [],
        "simulationActions": [],
        "simulatedProfit": 0.0,
        "maxDrawdown": 0.0,
        "triggeredInvalidation": False,
        "writtenToLedger": False,
        "triggeredErrorLedger": False,
        "simulation_only": True,
        "is_real_trade": False,
        "simulationOnly": True,
        "isRealTrade": False,
        "allowed_order_namespace": "SIM_*",
        "latest_action": "SIM_HOLD",
        "warnings": ["等待 Paper Trading Agent 真实运行；仅允许 SIM_* 沙箱动作。"],
    }


def _user_position_from_constraints(user_position: dict, user_constraints: dict) -> dict:
    next_position = dict(user_position)
    next_position["currentPositionRatio"] = user_constraints.get(
        "position_ratio",
        next_position.get("currentPositionRatio", 0),
    )
    if "shares" in user_constraints:
        next_position["currentShares"] = user_constraints["shares"]
    next_position["costPrice"] = user_constraints.get("cost_price", next_position.get("costPrice", 0))
    next_position["maxAcceptableDrawdown"] = user_constraints.get(
        "max_drawdown",
        next_position.get("maxAcceptableDrawdown", 0.08),
    )
    next_position["sellableBottomWarehouse"] = user_constraints.get(
        "allow_t0",
        next_position.get("sellableBottomWarehouse", False),
    )
    next_position["allowAddPosition"] = user_constraints.get(
        "allow_add",
        next_position.get("allowAddPosition", False),
    )
    return next_position


async def _attach_portfolio_snapshot_if_requested(
    run_data: dict,
    *,
    request: Any,
    run_id: str,
    user_position: dict,
    get_snapshot: GetSnapshot,
    normalize_symbol: NormalizeSymbol,
) -> dict | None:
    if not request.portfolio_snapshot_id:
        return None

    snapshot = await get_snapshot(request.portfolio_snapshot_id)
    if snapshot is None:
        raise AnalysisRunCreateNotFound("Portfolio snapshot not found")
    snapshot_payload_source = snapshot.model_dump() if hasattr(snapshot, "model_dump") else snapshot
    snapshot = PortfolioSnapshot(**snapshot_payload_source)

    request_symbol = normalize_symbol(request.symbol)
    matched = next((p for p in snapshot.positions if normalize_symbol(p.symbol) == request_symbol), None)
    portfolio_boundary = {
        "evidenceUsage": snapshot.evidenceUsage,
        "evidenceStrength": snapshot.evidenceStrength,
        "simulationOnly": snapshot.simulationOnly,
        "isRealTrade": snapshot.isRealTrade,
        "strongConclusionAllowed": snapshot.strongConclusionAllowed,
    }
    holdings_payload = [
        {
            "symbol": p.symbol,
            "name": p.name,
            "shares": p.shares,
            "availableShares": p.availableShares,
            "costPrice": p.costPrice,
            "marketValue": p.marketValue,
            "pnl": p.pnl,
            "industry": p.industry,
            "style": p.style,
            "theme": p.theme,
            "riskFactor": p.riskFactor,
            "positionRatio": p.weight,
            "weight": p.weight,
            "updatedAt": p.updatedAt,
        }
        for p in snapshot.positions
    ]
    run_data["portfolioSnapshot"] = snapshot.model_dump()
    run_data["portfolio"].update(
        {
            "holdings": holdings_payload,
            "portfolioCoverage": "HOLDINGS_CONNECTED",
            "snapshotId": snapshot.snapshotId,
            "snapshotUpdatedAt": snapshot.updatedAt,
            "currentTotalPosition": snapshot.totalPositionRatio,
            "singleStockPosition": matched.weight if matched else 0,
            "restrictionReasons": [] if matched else ["Selected snapshot has no holding row for this symbol."],
            **portfolio_boundary,
            "provenance": {
                "sourceType": "PORTFOLIO_SNAPSHOT",
                "sourceId": snapshot.snapshotId,
                "snapshotId": snapshot.snapshotId,
                "sourceName": snapshot.sourceName,
                "accountName": snapshot.accountName,
                "importedAt": snapshot.importedAt,
                "updatedAt": snapshot.updatedAt,
                "note": "Portfolio snapshot is supporting-only context for simulation analysis.",
                **portfolio_boundary,
            },
        }
    )
    if matched:
        run_data["userPosition"]["currentShares"] = matched.shares
        run_data["userPosition"]["currentPositionRatio"] = matched.weight
        run_data["userPosition"]["costPrice"] = matched.costPrice
        run_data["userPosition"]["sellableBottomWarehouse"] = matched.availableShares > 0
        run_data["stockName"] = matched.name or run_data.get("stockName", "")

    return {
        "timestamp": datetime.now().isoformat(),
        "runId": run_id,
        "node": "portfolio",
        "eventType": "PORTFOLIO_SNAPSHOT_ATTACHED",
        "message": f"Attached portfolio snapshot {snapshot.snapshotId}.",
        "statusBefore": "USER_INPUT_ONLY",
        "statusAfter": "HOLDINGS_CONNECTED",
        "inputHash": "",
        "outputHash": "",
        "auditId": f"AUD_PF_{run_id}",
    }


def _apply_add_position_constraints(run_data: dict, user_position: dict) -> None:
    run_data["portfolio"]["allowAddPosition"] = bool(user_position.get("allowAddPosition", False))
    if not run_data["portfolio"]["allowAddPosition"]:
        return
    run_data["portfolio"]["restrictionReasons"] = list(
        dict.fromkeys(
            [
                *run_data["portfolio"].get("restrictionReasons", []),
                "仅用户允许加仓候选；仍需 DVG、QIAM、执行层全部通过后才可能升级",
            ]
        )
    )


def real_run_seed(template: dict) -> dict:
    """Use scenario templates only as UI presets; never seed a new run with mock analysis outputs."""
    user_position = dict(template.get("userPosition") or {})
    current_ratio = user_position.get("currentPositionRatio", 0)
    max_drawdown = user_position.get("maxAcceptableDrawdown", 0.08)
    pending_dvg = {
        "status": "WARN",
        "dataReliability": "LOW",
        "confirmedRatio": 0,
        "inferredRatio": 0,
        "unknownRatio": 1,
        "coreUnknownCount": 0,
        "freshnessStatus": "PENDING",
        "sourceIntegrity": "PENDING",
        "hallucinationRiskScore": 80,
        "hallucinationRiskLevel": "HIGH",
        "criticalMissingData": ["数据源尚未完成拉取"],
        "dataConflicts": [],
        "allowedOutputLevel": "REVIEW_ONLY",
        "qiamPermission": "ALLOW_WITH_DISCOUNT",
        "scenarioPermission": "ALLOW_WITH_DISCOUNT",
        "executionPermission": "ALLOW_WITH_DISCOUNT",
        "finalDecisionCap": "WAIT",
        "hardStop": False,
        "provenance": {"sourceType": "PENDING", "note": "等待真实数据源拉取后由 DVG 重新计算"},
    }
    pending_risk = {
        "complianceRedLines": [],
        "f0IndividualHardRisks": [],
        "f1ExtremeChipCollapse": [],
        "f4ThreePartyFundResonanceOutflow": [],
        "l0AbsoluteLiquidityRedLine": [],
        "m0SystemicRisk": [],
        "aStockMicrostructureUnexecutable": [],
        "qiamBlockBuy": [],
        "portfolioRiskOverLimit": [],
        "executionUnreachable": [],
    }
    pending_atrade = {
        "t1Status": True,
        "sellableBottomWarehouse": bool(user_position.get("sellableBottomWarehouse", False)),
        "priceLimitStatus": "NORMAL",
        "stDelistingRisk": False,
        "level2Available": False,
        "depthAvailable": False,
        "executionReachability": "CONDITIONALLY_REACHABLE",
        "liquidityRisk": "MEDIUM",
        "flashCrashVacuumStatus": False,
        "slippageLimit": 0.005,
        "participationLimit": 0.1,
    }
    pending_kill_switch = {
        "active": False,
        "level": "NONE",
        "triggerNode": "",
        "triggerRule": "",
        "blockedPaths": [],
        "allowedPaths": ["WAIT", "REVIEW_ONLY", "HOLD"],
        "finalWriterMode": "NORMAL",
        "auditId": "AUD_KS_NONE",
    }
    pending_guardrail_hub = {
        "status": "PENDING",
        "finalDecisionCap": "WAIT",
        "killSwitch": copy.deepcopy(pending_kill_switch),
        "dvg": copy.deepcopy(pending_dvg),
        "risk": copy.deepcopy(pending_risk),
        "atrade": copy.deepcopy(pending_atrade),
        "gateResults": {
            "dvg": {"status": "PENDING", "auditId": "AUD_DVG_PENDING"},
            "risk": {"status": "PENDING", "auditId": "AUD_RISK_PENDING"},
            "atrade": {"status": "PENDING", "auditId": "AUD_ATRADE_PENDING"},
        },
        "warnings": ["等待 Guardrail Hub 真实运行；旧 DVG/Risk/Trade 字段仅作兼容展示。"],
        "auditId": "AUD_GUARDRAIL_HUB_PENDING",
        "preRun": True,
    }
    return {
        "runMode": template.get("runMode", "STANDARD_MODE"),
        "environment": "API_ORCHESTRATED",
        "dataMode": "LIVE_PENDING",
        "stockCode": template.get("stockCode", ""),
        "stockName": "",
        "taskType": template.get("taskType", "持仓复核"),
        "userPosition": user_position,
        "nodes": [],
        "guardrailHub": copy.deepcopy(pending_guardrail_hub),
        "dvg": copy.deepcopy(pending_dvg),
        "risk": copy.deepcopy(pending_risk),
        "atrade": copy.deepcopy(pending_atrade),
        "market": {
            "marketSentiment": "NEUTRAL",
            "volatilityIndex": 0,
            "liquidityIndex": 0,
            "institutionalActivity": "LOW",
            "retailSentiment": "NEUTRAL",
            "sectorRotation": [],
            "macroIndicators": {},
            "provenance": {"sourceType": "PENDING", "note": "等待真实行情和辅助数据源"},
        },
        "factorSlicing": {
            "mode": "AUTO",
            "factors": [],
            "factorClusters": [],
            "regimeClassification": "UNKNOWN",
            "factorStability": 0,
            "missingFactorData": ["因子输入尚未完成拉取"],
            "factorDataSource": "PENDING",
            "provenance": {"sourceType": "PENDING", "note": "等待真实数据后计算"},
        },
        "quantEngine": quant_engine_profile(None, template.get("taskType", "持仓复核")),
        "chipKb": {
            "currentPool": "C",
            "suggestedPool": "C",
            "migrationDirection": "STABLE",
            "hitRiskPatches": [],
            "hitPositivePatches": [],
            "dataConfidenceLevel": 0,
            "coreMissingData": ["筹码数据尚未完成拉取"],
            "signalOpsMappingStatus": "PENDING",
            "triggerConditions": [],
            "invalidationConditions": [],
            "reviewCycle": 0,
        },
        "qiam": {
            "calculationMode": "STANDARD",
            "dvgPermission": False,
            "rawBuySuitability": "NEUTRAL",
            "discountFactor": 0,
            "finalBuySuitability": "NEUTRAL",
            "probabilityBandUp": 0.33,
            "probabilityBandSideways": 0.34,
            "probabilityBandDown": 0.33,
            "probabilitySource": "PENDING",
            "expectedPayoffQuality": 0,
            "regimeFit": 0,
            "momentumQuality": 0,
            "volatilityCondition": 0,
            "liquidityAdjustedSignal": 0,
            "modelConfidenceRaw": 0,
            "modelConfidenceFinal": 0,
            "overfitRisk": 0,
            "distributionDrift": 0,
            "decisionEffect": 0,
            "missingData": ["QIAM 输入尚未完成拉取"],
            "downgradeReasons": ["新任务不再使用模板买入候选，等待真实 Agent 运行"],
        },
        "portfolio": {
            "currentTotalPosition": current_ratio,
            "singleStockPosition": current_ratio,
            "industryExposure": {},
            "styleExposure": {},
            "themeConcentration": 0,
            "sameRiskFactorConcentration": 0,
            "maxDrawdownConstraint": max_drawdown,
            "singleStockPositionCap": 0.15,
            "allowAddPosition": False,
            "allowHeavyPosition": False,
            "restrictionReasons": ["未接入真实持仓明细，默认禁止加仓候选"],
            "portfolioCoverage": "USER_INPUT_ONLY",
            "evidenceUsage": "supporting_only",
            "evidenceStrength": "LOW",
            "simulationOnly": True,
            "isRealTrade": False,
            "strongConclusionAllowed": False,
            "provenance": {
                "sourceType": "USER_INPUT",
                "sourceId": "USER_INPUT_ONLY",
                "evidenceUsage": "supporting_only",
                "evidenceStrength": "LOW",
                "simulationOnly": True,
                "isRealTrade": False,
                "strongConclusionAllowed": False,
                "note": "仅使用用户输入仓位，不使用模板行业敞口",
            },
        },
        "execution": {
            "allowedActions": ["WAIT", "REVIEW_ONLY"],
            "prohibitedActions": ["BUY_CANDIDATE", "ADD_CANDIDATE", "EXECUTION_BUY"],
            "executionReachability": "CONDITIONALLY_REACHABLE",
            "batchPaths": [],
            "slippageLimit": 0.005,
            "participationLimit": 0.1,
            "manualConfirmationItems": ["所有执行动作需要人工复核"],
            "forbiddenActions": ["自动下单", "市价追涨"],
        },
        "signalOps": {
            "signalStatus": "WATCH",
            "riskPassed": False,
            "dvgPassed": False,
            "qiamPassed": False,
            "executionReachable": False,
            "triggerConditions": [],
            "invalidationConditions": [],
            "reviewFields": ["真实数据源", "门禁结果", "人工确认"],
            "blockedReason": "",
        },
        "paperTrading": _pending_paper_trading_boundary(),
        "marketData": None,
        "marketTechnical": None,
        "quantCore": None,
        "mfeMaeResearch": None,
        "bottomResearch": None,
        "auxiliaryData": None,
        "agentResults": [],
        "dagEvents": [],
        "skippedNodes": [],
        "tokenUsage": None,
        "debateArtifacts": None,
        "orchestratorPlan": None,
        "finalContext": None,
        "agentOutputs": {},
        "llmTrace": [],
        "finalAction": "WAIT",
        "killSwitch": copy.deepcopy(pending_kill_switch),
        "auditLog": [],
        "reviewLedger": [],
        "finalWriter": {
            "mode": "PENDING",
            "finalAction": "WAIT",
            "humanConfirmationRequired": True,
            "auditId": "AUD_FW_PENDING",
            "sections": [
                {
                    "title": "等待真实运行",
                    "content": "新任务不会预置模板买入结论。请启动运行，等待数据源和 Agent 链路完成后再查看最终动作。",
                    "riskLevel": "MEDIUM",
                    "requiresConfirmation": True,
                }
            ],
        },
    }
