from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse


STRICT_MODES = {"on", "enabled", "required", "strict", "production", "prod"}
DISABLED_MODES = {"off", "disabled", "none", "dev", "development", "local", "bypass"}
PRODUCTION_ENVIRONMENTS = {"prod", "production", "staging", "strict"}

ALLOWLIST_ENV_NAMES = (
    "MARKET_DATA_BASE_URL_ALLOWLIST",
    "MARKET_DATA_EGRESS_ALLOWLIST",
    "MARKET_DATA_ALLOWED_HOSTS",
)
TUSHARE_HTTP_ENDPOINT = "https://api.tushare.pro"
OFFICIAL_PROVIDER_HOSTS = {
    "tushare": {"api.tushare.pro"},
    "sina": {"hq.sinajs.cn", "finance.sina.com.cn", "vip.stock.finance.sina.com.cn"},
    "tencent_finance": {"zxgstock.com", "proxy.finance.qq.com", "qt.gtimg.cn", "web.ifzq.gtimg.cn"},
    "tongdaxin": {"www.tdx.com.cn", "tdx.com.cn"},
    "ifind": {"partners.51ifind.com", "www.51ifind.com", "51ifind.com"},
    "alpha_vantage": {"www.alphavantage.co", "alphavantage.co"},
    "finnhub": {"finnhub.io"},
}


@dataclass(frozen=True)
class MarketDataEgressDecision:
    allowed: bool
    code: str
    message: str
    strict_mode: bool = False
    host: str = ""
    reason: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "message": self.message,
            "strict_mode": self.strict_mode,
            "host": self.host,
            "reason": self.reason,
        }


class MarketDataEgressBlockedError(RuntimeError):
    def __init__(self, decision: MarketDataEgressDecision):
        super().__init__(decision.message)
        self.decision = decision


def market_data_egress_strict_enabled() -> bool:
    mode = _normalized_env("MARKET_DATA_EGRESS_MODE")
    if mode in STRICT_MODES:
        return True
    if mode in DISABLED_MODES:
        return False

    if _normalized_env("API_AUTH_MODE") == "strict":
        return True
    app_env = _normalized_env("APP_ENV") or _normalized_env("ENVIRONMENT")
    return app_env in PRODUCTION_ENVIRONMENTS


def validate_market_data_egress(profile: Any, *, endpoint: str | None = None) -> MarketDataEgressDecision:
    endpoint = _profile_endpoint(profile) if endpoint is None else str(endpoint)
    provider = str(getattr(profile, "provider", "") or "").strip().lower()
    has_key = bool(str(getattr(profile, "api_key", "") or "").strip())
    strict_mode = market_data_egress_strict_enabled()

    if not endpoint:
        return MarketDataEgressDecision(
            allowed=True,
            code="BASE_URL_MISSING",
            message="Market data base_url is empty; no outbound market-data request will be made.",
            strict_mode=strict_mode,
        )

    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        scheme = (parsed.scheme or "").lower()
    except ValueError:
        return _blocked(host="", reason="invalid_base_url", message="Market data outbound request blocked: invalid URL.")

    if not strict_mode:
        return MarketDataEgressDecision(
            allowed=True,
            code="DEV_MODE_ALLOWED",
            message="Market data egress policy is not in strict mode.",
            strict_mode=False,
            host=host,
            reason="dev_mode",
        )

    if not host or scheme not in {"http", "https"}:
        return _blocked(
            host=host,
            reason="invalid_base_url",
            message=(
                "Market data outbound request blocked: base_url must be an absolute "
                "http(s) URL before a live request can be sent."
            ),
        )

    if provider == "tushare" and _is_official_provider_host(provider, host) and has_key and scheme != "https":
        return _blocked(
            host=host,
            reason="tushare_requires_https",
            message="Market data outbound request blocked: strict mode requires HTTPS for Tushare token-bearing requests.",
        )

    if _is_official_provider_host(provider, host):
        return MarketDataEgressDecision(
            allowed=True,
            code="OFFICIAL_HOST_ALLOWED",
            message="Market data base_url matches a built-in provider API host.",
            strict_mode=True,
            host=host,
            reason="official_provider_host",
        )

    if _host_matches_allowlist(host, configured_market_data_allowlist_hosts()):
        return MarketDataEgressDecision(
            allowed=True,
            code="ALLOWLIST_ALLOWED",
            message="Market data base_url host is present in the configured allowlist.",
            strict_mode=True,
            host=host,
            reason="allowlist",
        )

    return _blocked(
        host=host,
        reason="custom_base_url_requires_allowlist_or_confirmation",
        message=(
            "Market data outbound request blocked: strict mode requires this custom "
            "or non-official base_url to be added to MARKET_DATA_BASE_URL_ALLOWLIST, "
            "MARKET_DATA_EGRESS_ALLOWLIST, or MARKET_DATA_ALLOWED_HOSTS before a "
            "live request is sent."
        ),
    )


def assert_market_data_egress_allowed(profile: Any, *, endpoint: str | None = None) -> MarketDataEgressDecision:
    decision = validate_market_data_egress(profile, endpoint=endpoint)
    if not decision.allowed:
        raise MarketDataEgressBlockedError(decision)
    return decision


def configured_market_data_allowlist_hosts() -> list[str]:
    hosts: list[str] = []
    for name in ALLOWLIST_ENV_NAMES:
        hosts.extend(_split_allowlist(os.getenv(name, "")))
    return _dedupe(hosts)


def _profile_endpoint(profile: Any) -> str:
    provider = str(getattr(profile, "provider", "") or "").strip().lower()
    base_url = str(getattr(profile, "base_url", "") or "").strip()
    quote_path = str(getattr(profile, "quote_path", "") or "").strip()
    if quote_path.startswith(("http://", "https://")):
        return quote_path
    if provider == "tushare" and not base_url:
        return TUSHARE_HTTP_ENDPOINT
    return base_url


def _blocked(host: str, reason: str, message: str) -> MarketDataEgressDecision:
    return MarketDataEgressDecision(
        allowed=False,
        code="MARKET_DATA_EGRESS_BLOCKED",
        message=message,
        strict_mode=True,
        host=host,
        reason=reason,
    )


def _normalized_env(name: str) -> str:
    return os.getenv(name, "").strip().lower()


def _split_allowlist(raw: str) -> list[str]:
    hosts: list[str] = []
    for item in raw.replace(";", ",").replace("\n", ",").split(","):
        host = _allowlist_item_to_host(item)
        if host:
            hosts.append(host)
    return hosts


def _allowlist_item_to_host(item: str) -> str:
    clean = item.strip().lower()
    if not clean or clean == "*":
        return ""
    if clean.startswith("*."):
        return clean
    parsed = urlparse(clean if "://" in clean else f"//{clean}")
    return (parsed.hostname or "").lower()


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _is_official_provider_host(provider: str, host: str) -> bool:
    return host in OFFICIAL_PROVIDER_HOSTS.get(provider, set())


def _host_matches_allowlist(host: str, allowlist_hosts: Iterable[str]) -> bool:
    for allowed in allowlist_hosts:
        if allowed.startswith("*.") and host.endswith(allowed[1:]):
            return True
        if host == allowed:
            return True
    return False
