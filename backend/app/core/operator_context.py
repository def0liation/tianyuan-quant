from __future__ import annotations

import os
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from typing import Any

from fastapi import Request


OPERATOR_ROLES = ("viewer", "researcher", "operator", "admin")
ROLE_LEVELS = {role: index for index, role in enumerate(OPERATOR_ROLES)}

OPERATOR_ID_HEADERS = ("x-operator-id", "x-super-operator-id")
OPERATOR_ROLE_HEADERS = ("x-operator-role", "x-super-operator-role")
OPERATOR_ID_ENV_NAMES = ("LOCAL_OPERATOR_ID", "SUPER_OPERATOR_ID")
OPERATOR_ROLE_ENV_NAMES = ("LOCAL_OPERATOR_ROLE", "SUPER_OPERATOR_ROLE")

DEFAULT_OPERATOR_ID = "local_workbench"
DEFAULT_OPERATOR_ROLE = "admin"

_current_operator: ContextVar["OperatorContext | None"] = ContextVar("current_operator", default=None)


@dataclass(frozen=True)
class OperatorContext:
    id: str = DEFAULT_OPERATOR_ID
    role: str = DEFAULT_OPERATOR_ROLE
    source: str = "default"

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def normalize_operator_id(value: str | None, *, default: str = DEFAULT_OPERATOR_ID) -> str:
    cleaned = str(value or "").strip()
    return (cleaned or default)[:64]


def normalize_operator_role(value: str | None, *, default: str = DEFAULT_OPERATOR_ROLE) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return default
    if cleaned in ROLE_LEVELS:
        return cleaned
    return "viewer"


def local_operator_profile() -> OperatorContext:
    return OperatorContext(
        id=normalize_operator_id(_first_env(OPERATOR_ID_ENV_NAMES)),
        role=normalize_operator_role(_first_env(OPERATOR_ROLE_ENV_NAMES)),
        source="env" if _first_env(OPERATOR_ID_ENV_NAMES + OPERATOR_ROLE_ENV_NAMES) else "default",
    )


def token_operator_profile(role: str) -> OperatorContext:
    normalized_role = normalize_operator_role(role, default="viewer")
    return OperatorContext(
        id=f"api_{normalized_role}",
        role=normalized_role,
        source="api_token",
    )


def resolve_operator_from_request(request: Request) -> OperatorContext:
    profile = local_operator_profile()
    operator_id = next((request.headers.get(name) for name in OPERATOR_ID_HEADERS if request.headers.get(name)), "")
    operator_role = next((request.headers.get(name) for name in OPERATOR_ROLE_HEADERS if request.headers.get(name)), "")
    if operator_id or operator_role:
        return OperatorContext(
            id=normalize_operator_id(operator_id, default=profile.id),
            role=normalize_operator_role(operator_role, default=profile.role),
            source="header",
        )
    return profile


def set_current_operator(operator: OperatorContext) -> Token[OperatorContext | None]:
    return _current_operator.set(operator)


def reset_current_operator(token: Token[OperatorContext | None]) -> None:
    _current_operator.reset(token)


def current_operator() -> OperatorContext:
    return _current_operator.get() or local_operator_profile()


def role_allows(role: str, required_role: str) -> bool:
    return ROLE_LEVELS.get(role, -1) >= ROLE_LEVELS[required_role]
