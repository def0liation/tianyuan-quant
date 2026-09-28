from fastapi import APIRouter, HTTPException
import logging

from ..core.agent_framework import get_agent_prompt_payload, get_framework_payload
from ..core.llm_profile_tester import test_llm_profile_connection
from ..core.market_data_runner import test_market_data_profile_connection
from ..core.agent_runtime_store import (
    get_runtime_config,
    build_runtime_config_diff,
    update_agent_llm,
    update_market_data_adapter_config,
    update_runtime_settings,
    upsert_market_data_profile,
    upsert_llm_profile,
    get_data_sources_config,
    get_market_data_adapter_configs,
    public_data_sources_config,
    runtime_config_audit_snapshot,
    save_data_sources_config,
    test_market_data_profile,
)
from ..core.config_store import config_store
from ..core.operator_context import current_operator
from ..models.agent_runtime import (
    AgentRuntimeConfig,
    LLMConfigTestRequest,
    LLMConfigTestResult,
    MarketDataConfigTestRequest,
    MarketDataConfigTestResult,
    UpdateMarketDataAdapterConfigRequest,
    UpdateAgentLLMRequest,
    UpdateRuntimeSettingsRequest,
    UpsertMarketDataProfileRequest,
    UpsertLLMProfileRequest,
    DataSourcesConfig,
    UpdateDataSourcesRequest,
    LLMProfileConfig,
)


router = APIRouter()
logger = logging.getLogger(__name__)


async def _record_runtime_config_audit(
    *,
    surface: str,
    subject: str,
    before: dict,
    after: dict,
    summary: str,
):
    if before == after:
        return None
    return await config_store.record_external_change(
        scope="agent_runtime",
        surface=surface,
        subject=subject,
        before=before,
        after=after,
        diff=build_runtime_config_diff(before, after),
        summary=summary,
        operator=current_operator(),
    )


def _diagnose_data_source_error(error_msg: str) -> str:
    text = (error_msg or "").lower()
    if (
        "401" in text
        or "token" in text
        or "permission" in text
        or "权限" in error_msg
        or "积分" in error_msg
    ):
        return "TOKEN_OR_PERMISSION"
    if "timeout" in text or "timed out" in text:
        return "NETWORK_TIMEOUT"
    if "no records" in text or "empty" in text:
        return "NO_RECORDS"
    return "ADAPTER_ERROR"


def _format_data_source_error(error_msg: str, api_label: str) -> str:
    diagnosis = _diagnose_data_source_error(error_msg)
    if diagnosis == "TOKEN_OR_PERMISSION":
        return (
            f"Tushare {api_label} 返回 401：当前 Token 无权访问该接口，或账号积分/权限不足。"
            "行情接口可用不代表宏观、财务、筹码等接口也可用；请在 Tushare 后台开通权限/提升积分，"
            "或暂时关闭该数据源。系统会把该项标记为未接入，不再用模板值伪装真实数据。"
        )
    if diagnosis == "NETWORK_TIMEOUT":
        return "连接超时，请检查网络或稍后重试。"
    if "Tushare" in error_msg and "failed with code" in error_msg:
        return f"Tushare 接口返回错误: {error_msg}"
    if "token" in error_msg.lower():
        return "Token 无效或已过期，请检查配置。"
    return "连接失败，请检查配置或稍后重试。"


@router.get("/agents/framework")
async def get_agents_framework():
    return get_framework_payload()


@router.get("/agents/runtime", response_model=AgentRuntimeConfig)
async def get_agents_runtime():
    return get_runtime_config()


@router.patch("/agents/runtime", response_model=AgentRuntimeConfig)
async def patch_agents_runtime(request: UpdateRuntimeSettingsRequest):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    try:
        response = update_runtime_settings(request)
    except KeyError as exc:
        logger.exception("Runtime settings not found")
        raise HTTPException(status_code=404, detail="配置未找到") from exc


    await _record_runtime_config_audit(
        surface="runtime_settings",
        subject="agent_runtime",
        before=before,
        after=runtime_config_audit_snapshot(include_secret_versions=True),
        summary="Agent runtime settings changed.",
    )
    return response


@router.put("/agents/runtime/llm-profiles/{profile_id}", response_model=AgentRuntimeConfig)
async def put_llm_profile(profile_id: str, request: UpsertLLMProfileRequest):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    response = upsert_llm_profile(profile_id, request)
    await _record_runtime_config_audit(
        surface="llm_profile",
        subject=profile_id,
        before=before,
        after=runtime_config_audit_snapshot(include_secret_versions=True),
        summary=f"LLM profile changed: {profile_id}.",
    )
    return response


@router.put("/agents/runtime/market-data-profiles/{profile_id}", response_model=AgentRuntimeConfig)
async def put_market_data_profile(profile_id: str, request: UpsertMarketDataProfileRequest):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    response = upsert_market_data_profile(profile_id, request)
    await _record_runtime_config_audit(
        surface="market_data_profile",
        subject=profile_id,
        before=before,
        after=runtime_config_audit_snapshot(include_secret_versions=True),
        summary=f"Market data profile changed: {profile_id}.",
    )
    return response


@router.patch("/agents/{agent_id}/llm", response_model=AgentRuntimeConfig)
async def patch_agent_llm(agent_id: str, request: UpdateAgentLLMRequest):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    try:
        response = update_agent_llm(agent_id, request)
    except KeyError as exc:
        logger.exception("Agent LLM not found for %s", agent_id)
        raise HTTPException(status_code=404, detail="资源不存在") from exc


    await _record_runtime_config_audit(
        surface="agent_llm_assignment",
        subject=agent_id,
        before=before,
        after=runtime_config_audit_snapshot(include_secret_versions=True),
        summary=f"Agent LLM assignment changed: {agent_id}.",
    )
    return response


@router.post("/agents/runtime/test", response_model=LLMConfigTestResult)
async def post_llm_profile_test(request: LLMConfigTestRequest):
    return await test_llm_profile_connection(
        request.profile_id,
        live_call=request.live_call,
        test_prompt=request.test_prompt,
    )


@router.post("/agents/runtime/validate-config", response_model=LLMConfigTestResult)
async def post_llm_profile_validate_config(config: LLMProfileConfig):
    """Validate LLM profile configuration without saving or making live API calls."""
    from ..core.agent_runtime_store import test_llm_profile_config

    return test_llm_profile_config(config)


@router.post("/agents/runtime/market-data/test", response_model=MarketDataConfigTestResult)
async def post_market_data_profile_test(request: MarketDataConfigTestRequest):
    return await test_market_data_profile_connection(
        request.profile_id,
        live_call=request.live_call,
        symbol=request.symbol,
    )


@router.get("/agents/{agent_id}/prompt")
async def get_agent_prompt(agent_id: str):
    try:
        return get_agent_prompt_payload(agent_id)
    except KeyError as exc:
        logger.exception("Agent prompt not found for %s", agent_id)
        raise HTTPException(status_code=404, detail="资源不存在") from exc


@router.get("/agents/data-sources")
async def get_data_sources():
    return public_data_sources_config(get_data_sources_config())


@router.put("/agents/data-sources")
async def put_data_sources(request: UpdateDataSourcesRequest):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    sources = None
    if request.sources is not None:
        sources = [s.model_dump() for s in request.sources]
    response = public_data_sources_config(save_data_sources_config(request.tushare_token, sources))
    await _record_runtime_config_audit(
        surface="data_sources_config",
        subject="default",
        before=before,
        after=runtime_config_audit_snapshot(include_secret_versions=True),
        summary="Data sources config changed.",
    )
    return response


@router.post("/agents/data-sources/{key}/test")
async def post_data_source_test(key: str):
    import time
    from ..core.agent_runtime_store import get_data_sources_config, get_default_market_data_profile
    from ..core.market_data_runner import (
        _call_tushare_http_api_raw,
        _call_tushare_realtime_quote_sdk,
        _tushare_records_from_payload,
    )

    config = get_data_sources_config()
    config_sources = {s.get("key"): s for s in config.get("sources", [])}
    cfg = config_sources.get(key, {})

    if not cfg.get("enabled", False):
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": "NOT_CONFIGURED",
            "message": "该数据源未启用，请先启用后再测试。",
        }

    if not config.get("tushare_token", ""):
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": "NOT_CONFIGURED",
            "message": "未配置 tushare token，请先填写 token。",
        }

    api_name = cfg.get("tushare_api", "")
    if not api_name:
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": "NOT_CONFIGURED",
            "message": "未配置 tushare API 名称。",
        }

    profile = get_default_market_data_profile()
    field_result = test_market_data_profile(profile.id)
    if field_result.status not in {"READY", "CONFIGURED"}:
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": field_result.status,
            "message": field_result.message,
            "details": field_result.details,
        }
    ts_code = "603663.SH"

    from datetime import date, timedelta
    today = date.today()
    yesterday = today - timedelta(days=1)
    from app.core.adapters.tushare_adapter import _last_quarter_end
    last_quarter_end = _last_quarter_end(today)
    api_names = [part.strip() for part in api_name.split("/") if part.strip()]
    macro_api_names = api_names
    start_30d = (today - timedelta(days=30)).strftime("%Y%m%d")
    end_today = today.strftime("%Y%m%d")

    param_builders = {
        "fundamentals": {"ts_code": ts_code, "period": last_quarter_end},
        "announcements": {"ts_code": ts_code},
        "moneyflow": {"ts_code": ts_code, "trade_date": yesterday.strftime("%Y%m%d")},
        "chip": {"ts_code": ts_code, "start_date": start_30d, "end_date": end_today},
    }
    api_param_builders = {
        "stock_basic": {"exchange": "", "list_status": "L"},
        "namechange": {"ts_code": ts_code},
        "stock_hsgt": {"type": "HK_SH", "start_date": start_30d, "end_date": end_today},
        "fund_basic": {"market": "E", "status": "L"},
        "fund_daily": {"ts_code": "510300.SH", "start_date": start_30d, "end_date": end_today},
        "fut_basic": {"exchange": "CFFEX"},
        "opt_basic": {"exchange": "SSE"},
        "hk_basic": {"list_status": "L"},
        "us_basic": {"limit": "100"},
        "fx_obasic": {"exchange": "FXCM"},
        "income": {"ts_code": ts_code, "period": last_quarter_end},
        "balancesheet": {"ts_code": ts_code, "period": last_quarter_end},
        "cashflow": {"ts_code": ts_code, "period": last_quarter_end},
        "fina_indicator": {"ts_code": ts_code, "period": last_quarter_end},
        "pledge_stat": {"ts_code": ts_code},
        "repurchase": {"ts_code": ts_code},
        "share_float": {"ts_code": ts_code},
        "top_list": {"trade_date": yesterday.strftime("%Y%m%d")},
        "top_inst": {"trade_date": yesterday.strftime("%Y%m%d")},
        "margin_detail": {"trade_date": yesterday.strftime("%Y%m%d")},
        "moneyflow": {"ts_code": ts_code, "trade_date": yesterday.strftime("%Y%m%d")},
        "moneyflow_hsgt": {"start_date": start_30d, "end_date": end_today},
        "moneyflow_mkt_dc": {"trade_date": yesterday.strftime("%Y%m%d")},
        "stk_holdernumber": {"ts_code": ts_code},
        "cyq_perf": {"ts_code": ts_code, "start_date": start_30d, "end_date": end_today},
        "cyq_chips": {"ts_code": ts_code, "start_date": start_30d, "end_date": end_today},
        "concept": {},
        "concept_detail": {},
        "broker_recommend": {"month": today.strftime("%Y%m")},
        "stk_factor": {"ts_code": ts_code, "start_date": start_30d, "end_date": end_today},
    }

    try:
        started = time.perf_counter()
        if key == "realtime_quote":
            result = _call_tushare_realtime_quote_sdk(profile, ts_code)
            records = result.get("records", [])
        elif key == "kline_quote":
            records = []
            api_results = []
            failures = []
            kline_params = {
                api: {
                    "ts_code": ts_code,
                    "start_date": (today - timedelta(days=120)).strftime("%Y%m%d"),
                    "end_date": today.strftime("%Y%m%d"),
                }
                for api in api_names
            }
            for kline_api in api_names:
                try:
                    kline_result = _call_tushare_http_api_raw(
                        profile,
                        kline_api,
                        kline_params.get(kline_api, {"ts_code": ts_code}),
                    )
                    kline_records = _tushare_records_from_payload(kline_result)
                    records.extend(kline_records)
                    api_results.append(
                        {
                            "api": kline_api,
                            "status": "READY",
                            "record_count": len(kline_records),
                        }
                    )
                except Exception as kline_exc:
                    error_msg = str(kline_exc)
                    failures.append({"api": kline_api, "error": error_msg})
                    api_results.append(
                        {
                            "api": kline_api,
                            "status": "FAILED",
                            "diagnosis": _diagnose_data_source_error(error_msg),
                            "error": error_msg,
                        }
                    )

            latency_ms = int((time.perf_counter() - started) * 1000)
            if failures and not records:
                failed_apis = "/".join(item["api"] for item in failures)
                return {
                    "key": key,
                    "name": cfg.get("name", key),
                    "status": "FAILED",
                    "message": _format_data_source_error(
                        "; ".join(item["error"] for item in failures),
                        failed_apis or api_name,
                    ),
                    "diagnosis": _diagnose_data_source_error("; ".join(item["error"] for item in failures)),
                    "latency_ms": latency_ms,
                    "record_count": 0,
                    "api_results": api_results,
                    "failed_apis": [item["api"] for item in failures],
                }

            return {
                "key": key,
                "name": cfg.get("name", key),
                "status": "READY",
                "message": (
                    f"已分别测试 K 线接口 {api_name}，获取 {len(records)} 条真实记录。"
                    + (f" 其中 {len(failures)} 个接口失败，请查看明细。" if failures else "")
                ),
                "latency_ms": latency_ms,
                "record_count": len(records),
                "api_results": api_results,
                "failed_apis": [item["api"] for item in failures],
            }
        elif key == "macro":
            records = []
            api_results = []
            failures = []
            macro_params = {
                "cn_cpi": {"start_m": f"{today.year - 1}01", "end_m": f"{today.year}12"},
                "cn_gdp": {"start_q": f"{today.year - 2}Q1", "end_q": f"{today.year}Q4"},
                "shibor_lpr": {},
            }
            for macro_api in macro_api_names:
                try:
                    macro_result = _call_tushare_http_api_raw(
                        profile,
                        macro_api,
                        macro_params.get(macro_api, {}),
                    )
                    macro_records = _tushare_records_from_payload(macro_result)
                    records.extend(macro_records)
                    api_results.append(
                        {
                            "api": macro_api,
                            "status": "READY",
                            "record_count": len(macro_records),
                        }
                    )
                except Exception as macro_exc:
                    error_msg = str(macro_exc)
                    failures.append(
                        {
                            "api": macro_api,
                            "error": error_msg,
                            "message": _format_data_source_error(error_msg, macro_api),
                        }
                    )
                    api_results.append(
                        {
                            "api": macro_api,
                            "status": "FAILED",
                            "diagnosis": _diagnose_data_source_error(error_msg),
                            "error": error_msg,
                        }
                    )

            latency_ms = int((time.perf_counter() - started) * 1000)
            if failures and not records:
                failed_apis = "/".join(item["api"] for item in failures)
                return {
                    "key": key,
                    "name": cfg.get("name", key),
                    "status": "FAILED",
                    "message": _format_data_source_error(
                        "; ".join(item["error"] for item in failures),
                        failed_apis or api_name,
                    ),
                    "diagnosis": _diagnose_data_source_error("; ".join(item["error"] for item in failures)),
                    "latency_ms": latency_ms,
                    "record_count": 0,
                    "api_results": api_results,
                    "failed_apis": [item["api"] for item in failures],
                }

            return {
                "key": key,
                "name": cfg.get("name", key),
                "status": "READY",
                "message": (
                    f"已分别测试宏观接口 {api_name}，获取 {len(records)} 条记录。"
                    + (f" 其中 {len(failures)} 个接口失败，请查看明细。" if failures else "")
                ),
                "latency_ms": latency_ms,
                "record_count": len(records),
                "api_results": api_results,
                "failed_apis": [item["api"] for item in failures],
            }
        else:
            records = []
            api_results = []
            failures = []
            success_count = 0
            for generic_api in api_names or [api_name]:
                try:
                    result = _call_tushare_http_api_raw(
                        profile,
                        generic_api,
                        api_param_builders.get(
                            generic_api,
                            param_builders.get(key, {"ts_code": ts_code}),
                        ),
                    )
                    api_records = _tushare_records_from_payload(result)
                    records.extend(api_records)
                    success_count += 1
                    api_results.append(
                        {
                            "api": generic_api,
                            "status": "READY",
                            "record_count": len(api_records),
                        }
                    )
                except Exception as generic_exc:
                    error_msg = str(generic_exc)
                    failures.append({"api": generic_api, "error": error_msg})
                    api_results.append(
                        {
                            "api": generic_api,
                            "status": "FAILED",
                            "diagnosis": _diagnose_data_source_error(error_msg),
                            "error": error_msg,
                        }
                    )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if "success_count" in locals() and success_count == 0:
            failed_apis = "/".join(item["api"] for item in failures)
            return {
                "key": key,
                "name": cfg.get("name", key),
                "status": "FAILED",
                "message": _format_data_source_error(
                    "; ".join(item["error"] for item in failures),
                    failed_apis or api_name,
                ),
                "diagnosis": _diagnose_data_source_error("; ".join(item["error"] for item in failures)),
                "latency_ms": latency_ms,
                "record_count": 0,
                "api_results": api_results,
                "failed_apis": [item["api"] for item in failures],
            }
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": "READY",
            "message": (
                f"已按 8000 积分配置测试 tushare {api_name}，获得 {len(records)} 条记录。"
                + (
                    f" 成功 {success_count}/{len(api_results)} 个接口，个股相关接口使用样本标的 {ts_code}，列表类接口使用轻量参数。"
                    if "success_count" in locals()
                    else f" 样本标的 {ts_code}。"
                )
            ),
            "latency_ms": latency_ms,
            "record_count": len(records),
            "test_symbol": ts_code,
            "api_results": api_results if "api_results" in locals() else [],
            "failed_apis": [item["api"] for item in failures] if "failures" in locals() else [],
        }
    except Exception as exc:
        logger.exception("Data source test failed for %s", key)
        error_msg = str(exc)
        user_message = _format_data_source_error(error_msg, api_name)
        return {
            "key": key,
            "name": cfg.get("name", key),
            "status": "FAILED",
            "message": user_message,
            "diagnosis": _diagnose_data_source_error(error_msg),
            "error": error_msg[:300],
        }


@router.get("/agents/market-data/adapters/config")
async def get_market_data_adapters_config():
    return [
        config.model_dump() if hasattr(config, "model_dump") else config.dict()
        for config in get_market_data_adapter_configs()
    ]


@router.put("/agents/market-data/adapters/{adapter_id}/config")
async def put_market_data_adapter_config(
    adapter_id: str,
    request: UpdateMarketDataAdapterConfigRequest,
):
    before = runtime_config_audit_snapshot(include_secret_versions=True)
    try:
        config = update_market_data_adapter_config(adapter_id, request)
        from ..core.market_data_adapter import register_default_market_data_adapters

        register_default_market_data_adapters()
        await _record_runtime_config_audit(
            surface="market_data_adapter_config",
            subject=adapter_id,
            before=before,
            after=runtime_config_audit_snapshot(include_secret_versions=True),
            summary=f"Market data adapter config changed: {adapter_id}.",
        )
        return config.model_dump() if hasattr(config, "model_dump") else config.dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"适配器不存在: {adapter_id}") from exc


@router.get("/agents/market-data/adapters")
async def get_market_data_adapters(live_check: bool = False):
    try:
        from ..core.market_data_adapter import register_default_market_data_adapters

        registry = register_default_market_data_adapters()
        if live_check:
            health_list = await registry.health_check_all()
            return [h.to_public_dict() for h in health_list]

        adapters = []
        for health in registry.list_adapters():
            item = health.to_public_dict()
            item["healthCheckMode"] = "metadata"
            item["message"] = item.get("message") or "Adapter metadata only; run an explicit health check for upstream status."
            adapters.append(item)
        return adapters
    except Exception:
        logger.exception("获取适配器信息失败")
        raise HTTPException(status_code=500, detail="获取适配器信息失败，请稍后重试")


@router.post("/agents/market-data/adapters/{adapter_id}/health")
async def post_adapter_health(adapter_id: str):
    try:
        from ..core.market_data_adapter import register_default_market_data_adapters

        registry = register_default_market_data_adapters()
        health = await registry.health_check_adapter(adapter_id)
        if health is None:
            raise HTTPException(status_code=404, detail=f"适配器不存在: {adapter_id}")
        return health.to_public_dict()
    except HTTPException:
        raise
    except Exception:
        logger.exception("适配器健康检查失败")
        raise HTTPException(status_code=500, detail="适配器健康检查失败，请稍后重试")


@router.get("/agents/market-data/status")
async def get_market_data_status():
    try:
        from ..core.market_data_adapter import register_default_market_data_adapters

        registry = register_default_market_data_adapters()

        matrix = await registry.build_status_matrix()
        return matrix.to_public_dict()
    except Exception as exc:
        logger.exception("获取数据源状态失败")
        raise HTTPException(status_code=500, detail="获取数据源状态失败，请稍后重试")
