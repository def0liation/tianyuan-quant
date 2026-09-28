import os
import secrets
from typing import Iterable

from fastapi import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .operator_context import (
    OperatorContext,
    resolve_operator_from_request,
    reset_current_operator,
    role_allows,
    set_current_operator,
    token_operator_profile,
)


WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
TOKEN_ENV_NAMES = ("API_WRITE_TOKEN", "SUPER_API_WRITE_TOKEN")
ROLE_TOKEN_ENV_NAMES = {
    "admin": ("API_ADMIN_TOKEN", "SUPER_API_ADMIN_TOKEN", *TOKEN_ENV_NAMES),
    "operator": ("API_OPERATOR_TOKEN", "SUPER_API_OPERATOR_TOKEN"),
    "researcher": ("API_RESEARCHER_TOKEN", "SUPER_API_RESEARCHER_TOKEN"),
    "viewer": ("API_VIEWER_TOKEN", "SUPER_API_VIEWER_TOKEN"),
}
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/ready",
    "/api/startup/status",
}

ENABLED_AUTH_MODES = {"on", "enabled", "required", "strict", "write", "write_protect"}
FULL_API_AUTH_MODES = {"on", "enabled", "required", "strict"}
WRITE_ONLY_AUTH_MODES = {"write", "write_protect"}
DISABLED_AUTH_MODES = {"off", "disabled", "none", "dev", "development", "local", "bypass"}
PRODUCTION_ENVIRONMENTS = {"prod", "production", "staging", "strict"}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _normalized_env(name: str) -> str:
    return _env(name).lower()


def write_auth_enabled() -> bool:
    mode = _normalized_env("API_AUTH_MODE")
    if mode in ENABLED_AUTH_MODES:
        return True
    if mode in DISABLED_AUTH_MODES:
        return False

    app_env = _normalized_env("APP_ENV") or _normalized_env("ENVIRONMENT")
    return app_env in PRODUCTION_ENVIRONMENTS


def full_api_auth_enabled() -> bool:
    mode = _normalized_env("API_AUTH_MODE")
    if mode in FULL_API_AUTH_MODES:
        return True
    if mode in WRITE_ONLY_AUTH_MODES or mode in DISABLED_AUTH_MODES:
        return False

    app_env = _normalized_env("APP_ENV") or _normalized_env("ENVIRONMENT")
    return app_env in PRODUCTION_ENVIRONMENTS


def configured_write_tokens() -> list[str]:
    tokens: list[str] = []
    for name in TOKEN_ENV_NAMES:
        token = _env(name)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def configured_role_tokens() -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    seen: set[str] = set()
    for role, names in ROLE_TOKEN_ENV_NAMES.items():
        for name in names:
            token = _env(name)
            if token and token not in seen:
                tokens.append((token, role))
                seen.add(token)
    return tokens


def configured_api_tokens() -> list[str]:
    return [token for token, _role in configured_role_tokens()]


def protected_write_request(request: Request) -> bool:
    path = request.url.path
    return (path == "/api" or path.startswith("/api/")) and request.method.upper() in WRITE_METHODS


def public_api_request_path(path: str, method: str) -> bool:
    clean_path = path.rstrip("/") or path
    return method.upper() == "OPTIONS" or clean_path in PUBLIC_API_PATHS


def protected_api_request(request: Request) -> bool:
    path = request.url.path
    if not (path == "/api" or path.startswith("/api/")):
        return False
    return not public_api_request_path(path, request.method)


def eventsource_stream_request_path(path: str, method: str) -> bool:
    clean_path = path.rstrip("/") or path
    return method.upper() == "GET" and clean_path.startswith("/api/analysis/runs/") and clean_path.endswith("/stream")


def extract_write_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()

    for header_name in ("x-api-key", "x-super-api-key"):
        token = request.headers.get(header_name, "").strip()
        if token:
            return token

    if eventsource_stream_request_path(request.url.path, request.method):
        query_token = extract_token_from_query(request.query_params)
        if query_token:
            return query_token

    return ""


def extract_token_from_headers(headers: object) -> str:
    get_header = getattr(headers, "get", None)
    if not callable(get_header):
        return ""
    authorization = str(get_header("authorization", "") or "").strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    for header_name in ("x-api-key", "x-super-api-key"):
        token = str(get_header(header_name, "") or "").strip()
        if token:
            return token
    return ""


def extract_token_from_query(query_params: object) -> str:
    get_param = getattr(query_params, "get", None)
    if not callable(get_param):
        return ""
    for key in ("token", "api_key", "apiKey", "super_api_key", "superApiKey"):
        token = str(get_param(key, "") or "").strip()
        if token:
            return token
    return ""


def token_matches(provided_token: str, expected_tokens: Iterable[str]) -> bool:
    return any(secrets.compare_digest(provided_token, expected_token) for expected_token in expected_tokens)


def operator_from_token(provided_token: str) -> OperatorContext | None:
    if not provided_token:
        return None
    for expected_token, role in configured_role_tokens():
        if secrets.compare_digest(provided_token, expected_token):
            return token_operator_profile(role)
    return None


def required_operator_role(request: Request) -> tuple[str, str]:
    raw_path = request.url.path
    path = raw_path.rstrip("/") or raw_path
    method = request.method.upper()

    if method == "DELETE":
        return "admin", "delete"
    if method == "PATCH" and path == "/api/config/runtime":
        return "admin", "config_runtime"
    if method == "POST" and path == "/api/config/drafts":
        return "admin", "config_draft"
    if method == "POST" and path.startswith("/api/config/drafts/") and path.endswith("/apply"):
        return "admin", "config_apply"
    if method == "POST" and path == "/api/config/rollback":
        return "admin", "config_rollback"
    if method == "POST" and path == "/api/config/external-restore":
        return "admin", "config_external_restore"
    if method == "POST" and path == "/api/ops/alerts/dispatch":
        return "admin", "ops_alert_dispatch"
    if method == "POST" and path == "/api/ops/alerts/export/handoff":
        return "admin", "ops_alert_export_handoff"
    if method == "POST" and path == "/api/ops/logs/export/handoff":
        return "admin", "ops_log_export_handoff"
    if method in WRITE_METHODS and (
        path == "/api/agents/runtime"
        or path.startswith("/api/agents/runtime/")
        or (path.startswith("/api/agents/") and path.endswith("/llm"))
    ):
        return "admin", "agents_runtime"
    if method in WRITE_METHODS and (path == "/api/plugins" or path.startswith("/api/plugins/")):
        return "admin", "plugins"
    if (method == "PUT" and path == "/api/technical-kline/governance") or (
        method == "POST" and path == "/api/technical-kline/governance/rollback"
    ):
        return "admin", "technical_kline_governance"
    if (
        method == "POST"
        and path.startswith("/api/case-library/knowledge-versions/")
        and path.endswith("/rollback")
    ):
        return "admin", "knowledge_version_rollback"
    if method == "PATCH" and path == "/api/signalops/auto-paper/config":
        return "admin", "signalops_config"
    if method == "POST" and path in {
        "/api/signalops/auto-paper/tick",
        "/api/signalops/auto-paper/daily-review",
        "/api/signalops/auto-paper/command",
        "/api/signalops/auto-paper/review-decisions",
        "/api/signalops/auto-paper/review-decision-events/verify",
        "/api/signalops/auto-paper/review-decision-events/handoff",
    }:
        return "operator", "signalops_command"
    if method in WRITE_METHODS and path.startswith("/api/signals/") and (
        path.endswith("/conditions") or path.endswith("/transition") or path.endswith("/review")
    ):
        return "operator", "signalops_lifecycle"
    if method in WRITE_METHODS and path.startswith("/api/signalops/") and "/paper-" in path:
        return "operator", "signalops_paper_trading"
    if method == "POST" and path in {
        "/api/data-reliability/adapters/check",
        "/api/data-reliability/symbol-check",
        "/api/data-reliability/symbol-arbitration",
    }:
        return "operator", "data_reliability_active_check"
    return "researcher", "api_write"


def _operator_for_response(operator: OperatorContext) -> dict[str, str]:
    return {
        "id": operator.id,
        "role": operator.role,
        "source": operator.source,
    }


def operator_role_response(operator: OperatorContext, required_role: str, policy_scope: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "detail": {
                "message": "Operator role is not allowed for this write.",
                "required_role": required_role,
                "scope": policy_scope,
                "operator": _operator_for_response(operator),
            }
        },
    )


class APIWriteAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        operator = resolve_operator_from_request(request)
        auth_required = protected_api_request(request) and (
            full_api_auth_enabled() or (protected_write_request(request) and write_auth_enabled())
        )
        if auth_required:
            expected_tokens = configured_api_tokens()
            if not expected_tokens:
                response = JSONResponse(
                    status_code=403,
                    content={"detail": "API authentication token is not configured."},
                )
                await response(scope, receive, send)
                return

            provided_token = extract_write_token(request)
            if not provided_token:
                response = JSONResponse(
                    status_code=401,
                    content={
                        "detail": (
                            "API write authentication required."
                            if protected_write_request(request)
                            else "API authentication required."
                        )
                    },
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return

            token_operator = operator_from_token(provided_token)
            if token_operator is None:
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Invalid API write token."
                            if protected_write_request(request)
                            else "Invalid API token."
                        )
                    },
                )
                await response(scope, receive, send)
                return
            operator = token_operator

        scope.setdefault("state", {})["operator"] = operator
        operator_token = set_current_operator(operator)
        try:
            if protected_write_request(request):
                required_role, policy_scope = required_operator_role(request)
                if not role_allows(operator.role, required_role):
                    response = operator_role_response(operator, required_role, policy_scope)
                    await response(scope, receive, send)
                    return

            await self.app(scope, receive, send)
        finally:
            reset_current_operator(operator_token)
