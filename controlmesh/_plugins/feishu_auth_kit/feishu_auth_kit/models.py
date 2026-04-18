from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ScopeGrant:
    scope: str
    token_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AppInfo:
    app_id: str
    name: str | None = None
    creator_id: str | None = None
    owner_open_id: str | None = None
    owner_type: int | None = None
    effective_owner_open_id: str | None = None
    scopes: list[ScopeGrant] = field(default_factory=list)
    raw_app: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantAccessToken:
    token: str
    expire: int | None = None


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


@dataclass(frozen=True)
class DeviceToken:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    refresh_expires_in: int | None = None
    scope: str | None = None

