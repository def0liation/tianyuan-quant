from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse


STRICT_MODES = {"on", "enabled", "required", "strict", "production", "prod"}
DISABLED_MODES = {"off", "disabled", "none", "dev", "development", "local", "bypass"}
PRODUCTION_ENVIRONMENTS = {"prod", "production", "staging", "strict"}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ALLOWLIST_ENV_NAMES = (
    "LLM_BASE_URL_ALLOWLIST",
    "LLM_EGRESS_ALLOWLIST",
    "LLM_ALLOWED_HOSTS",
)
OFFICIAL_PROVIDER_HOSTS = {
    "openai": {"api.openai.com"},
    "openai_compatible": {"api.openai.com"},
    "anthropic": {"api.anthropic.com"},
    "deepseek": {"api.deepseek.com"},
    "qwen": {"dashscope.aliyuncs.com"},
    "moonshot": {"api.moonshot.ai"},
    "mistral": {"api.mistral.ai"},
    "xai": {"api.x.ai"},
    "openrouter": {"openrouter.ai"},
    "gemini": {"generativelanguage.googleapis.com"},
}


@dataclass(frozen=True)
class LLMEgressDecision:
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


class LLMEgressBlockedError(RuntimeError):
    def __init__(self, decision: LLMEgressDecision):
        super().__init__(decision.message)
        self.decision = decision


def llm_egress_strict_enabled() -> bool:
    mode = _normalized_env("LLM_EGRESS_MODE")
    if mode in STRICT_MODES:
        return True
    if mode in DISABLED_MODES:
        return False

    if _normalized_env("API_AUTH_MODE") == "strict":
        return True
    app_env = _normalized_env("APP_ENV") or _normalized_env("ENVIRONMENT")
    return app_env in PRODUCTION_ENVIRONMENTS


def validate_llm_egress(profile: Any) -> LLMEgressDecision:
    base_url = str(getattr(profile, "base_url", "") or "").strip()
    provider = str(getattr(profile, "provider", "") or "").strip().lower()
    has_key = bool(str(getattr(profile, "api_key", "") or "").strip())
    strict_mode = llm_egress_strict_enabled()

    if not base_url:
        return LLMEgressDecision(
            allowed=True,
            code="BASE_URL_MISSING",
            message="LLM base_url is empty; no outbound LLM request will be made.",
            strict_mode=strict_mode,
        )

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()

    if not strict_mode:
        return LLMEgressDecision(
            allowed=True,
            code="DEV_MODE_ALLOWED",
            message="LLM egress policy is not in strict mode.",
            strict_mode=False,
            host=host,
            reason="dev_mode",
        )

    if not host or scheme not in {"http", "https"}:
        return _blocked(
            host=host,
            reason="invalid_base_url",
            message=(
                "LLM outbound request blocked: base_url must be an absolute http(s) URL "
                "before a live request can be sent."
            ),
        )

    if _is_local_host(host):
        return LLMEgressDecision(
            allowed=True,
            code="LOCALHOST_ALLOWED",
            message="LLM base_url points to a local debugging endpoint.",
            strict_mode=True,
            host=host,
            reason="localhost",
        )

    if _is_official_provider_host(provider, host) and scheme == "https":
        return LLMEgressDecision(
            allowed=True,
            code="OFFICIAL_HOST_ALLOWED",
            message="LLM base_url matches the official provider API host.",
            strict_mode=True,
            host=host,
            reason="official_provider_host",
        )

    if _host_matches_allowlist(host, configured_allowlist_hosts()):
        return LLMEgressDecision(
            allowed=True,
            code="ALLOWLIST_ALLOWED",
            message="LLM base_url host is present in the configured allowlist.",
            strict_mode=True,
            host=host,
            reason="allowlist",
        )

    if not has_key:
        return _blocked(
            host=host,
            reason="custom_base_url_requires_allowlist",
            message=(
                "LLM outbound request blocked: strict mode requires this custom or non-official "
                "base_url to be added to LLM_BASE_URL_ALLOWLIST before a live request is sent. "
                "No API key is configured, but remote LLM egress still requires server-side approval."
            ),
        )

    return _blocked(
        host=host,
        reason="custom_base_url_requires_allowlist",
        message=(
            "LLM outbound request blocked: strict mode requires this custom or non-official "
            "base_url to be added to LLM_BASE_URL_ALLOWLIST before a key-bearing request is sent. "
            "Request-level egress_confirmed cannot approve key-bearing custom LLM egress."
        ),
    )


def assert_llm_egress_allowed(profile: Any) -> LLMEgressDecision:
    decision = validate_llm_egress(profile)
    if not decision.allowed:
        raise LLMEgressBlockedError(decision)
    return decision


def configured_allowlist_hosts() -> list[str]:
    hosts: list[str] = []
    for name in ALLOWLIST_ENV_NAMES:
        hosts.extend(_split_allowlist(os.getenv(name, "")))
    return _dedupe(hosts)


def _blocked(host: str, reason: str, message: str) -> LLMEgressDecision:
    return LLMEgressDecision(
        allowed=False,
        code="LLM_EGRESS_BLOCKED",
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


def _is_local_host(host: str) -> bool:
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_official_provider_host(provider: str, host: str) -> bool:
    return host in OFFICIAL_PROVIDER_HOSTS.get(provider, set())


def _host_matches_allowlist(host: str, allowlist_hosts: Iterable[str]) -> bool:
    for allowed in allowlist_hosts:
        if allowed.startswith("*.") and host.endswith(allowed[1:]):
            return True
        if host == allowed:
            return True
    return False
