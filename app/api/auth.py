from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, status

from app.core.config import get_settings
from app.core.errors import ApiError

ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}


@dataclass(frozen=True)
class ApiPrincipal:
    role: str
    key_name: str


def resolve_api_key(api_key: str | None) -> ApiPrincipal:
    settings = get_settings()
    key_map = {
        settings.api_key_admin: ApiPrincipal(role="admin", key_name="admin"),
        settings.api_key_operator: ApiPrincipal(role="operator", key_name="operator"),
        settings.api_key_viewer: ApiPrincipal(role="viewer", key_name="viewer"),
    }
    if not api_key or api_key not in key_map:
        raise ApiError(
            code="UNAUTHORIZED",
            message="Valid API key is required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return key_map[api_key]


def require_roles(*allowed_roles: str) -> Callable[..., Awaitable[ApiPrincipal]]:
    min_level = min(ROLE_LEVELS[role] for role in allowed_roles)

    async def dependency(x_api_key: Annotated[str | None, Header()] = None) -> ApiPrincipal:
        principal = resolve_api_key(x_api_key)
        if ROLE_LEVELS[principal.role] < min_level:
            raise ApiError(
                code="FORBIDDEN",
                message="Insufficient role for this operation.",
                status_code=status.HTTP_403_FORBIDDEN,
                details={"required_roles": list(allowed_roles), "role": principal.role},
            )
        return principal

    return dependency
