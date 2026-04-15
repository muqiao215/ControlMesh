"""Helpers for cached Feishu app metadata, scopes, and owner derivation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from controlmesh.messenger.feishu.auth.brand import FeishuBrand, open_platform_domain
from controlmesh.messenger.feishu.auth.errors import AppInfoAccessError

TokenType = Literal["user", "tenant"]
ScopeNeedType = Literal["one", "all"]


@dataclass(frozen=True, slots=True)
class GrantedScope:
    scope: str
    token_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeishuAppInfo:
    app_id: str
    creator_id: str | None
    owner_open_id: str | None
    owner_type: int | None
    effective_owner_open_id: str | None
    scopes: tuple[GrantedScope, ...]


@dataclass(slots=True)
class _CacheEntry:
    fetched_at_ms: int
    app_info: FeishuAppInfo


def intersect_scopes(app_granted: list[str], api_required: list[str]) -> list[str]:
    granted_set = set(app_granted)
    return [scope for scope in api_required if scope in granted_set]


def missing_scopes(app_granted: list[str], api_required: list[str]) -> list[str]:
    granted_set = set(app_granted)
    return [scope for scope in api_required if scope not in granted_set]


def is_app_scope_satisfied(
    app_scopes: list[str],
    required_scopes: list[str],
    scope_need_type: ScopeNeedType = "one",
) -> bool:
    if not required_scopes:
        return True
    if not app_scopes:
        return False
    if scope_need_type == "all":
        return not missing_scopes(app_scopes, required_scopes)
    return bool(intersect_scopes(app_scopes, required_scopes))


class FeishuAppInfoCache:
    """Small in-memory cache around app metadata inspection."""

    def __init__(
        self,
        *,
        ttl_ms: int = 30_000,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._ttl_ms = ttl_ms
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, _CacheEntry] = {}

    def invalidate(self, app_id: str) -> None:
        self._cache.pop(app_id, None)

    async def get_granted_scopes(
        self,
        session: Any,
        *,
        brand: FeishuBrand,
        tenant_access_token: str,
        app_id: str,
        token_type: TokenType | None = None,
    ) -> list[str]:
        app_info = await self.get_app_info(
            session,
            brand=brand,
            tenant_access_token=tenant_access_token,
            app_id=app_id,
        )
        scopes = list(app_info.scopes)
        if token_type is not None:
            scopes = [
                scope
                for scope in scopes
                if not scope.token_types or token_type in scope.token_types
            ]
        return [scope.scope for scope in scopes]

    async def get_app_info(
        self,
        session: Any,
        *,
        brand: FeishuBrand,
        tenant_access_token: str,
        app_id: str,
    ) -> FeishuAppInfo:
        cached = self._cache.get(app_id)
        now_ms = self._now_ms()
        if cached and now_ms - cached.fetched_at_ms < self._ttl_ms:
            return cached.app_info

        url = f"{open_platform_domain(brand)}/open-apis/application/v6/applications/{app_id}"
        async with session.get(
            url,
            params={"lang": "zh_cn"},
            headers={"Authorization": f"Bearer {tenant_access_token}"},
        ) as response:
            payload = await response.json(content_type=None)
            if response.status in {400, 403}:
                raise AppInfoAccessError(
                    "unable to inspect Feishu app info",
                    status=response.status,
                    payload=payload,
                )
            if response.status >= 400:
                raise AppInfoAccessError(
                    f"app info request failed with HTTP {response.status}",
                    status=response.status,
                    payload=payload,
                )
            if payload.get("code", 0) != 0:
                raise AppInfoAccessError(
                    "unable to inspect Feishu app info",
                    code=payload.get("code"),
                    payload=payload,
                )

        raw_app = payload.get("data", {}).get("app", {})
        if not isinstance(raw_app, dict):
            raw_app = {}
        raw_owner = raw_app.get("owner", {})
        if not isinstance(raw_owner, dict):
            raw_owner = {}
        owner_type = raw_owner.get("owner_type", raw_owner.get("type"))
        owner_open_id = raw_owner.get("owner_id")
        creator_id = raw_app.get("creator_id")
        effective_owner = (
            owner_open_id if owner_type == 2 and owner_open_id else creator_id or owner_open_id
        )
        raw_scopes = raw_app.get("scopes", [])
        scopes: list[GrantedScope] = []
        if isinstance(raw_scopes, list):
            for scope in raw_scopes:
                if not isinstance(scope, dict) or not scope.get("scope"):
                    continue
                token_types = scope.get("token_types", [])
                normalized = tuple(token for token in token_types if isinstance(token, str))
                scopes.append(GrantedScope(scope=str(scope["scope"]), token_types=normalized))

        app_info = FeishuAppInfo(
            app_id=app_id,
            creator_id=str(creator_id) if creator_id else None,
            owner_open_id=str(owner_open_id) if owner_open_id else None,
            owner_type=int(owner_type) if owner_type is not None else None,
            effective_owner_open_id=str(effective_owner) if effective_owner else None,
            scopes=tuple(scopes),
        )
        self._cache[app_id] = _CacheEntry(fetched_at_ms=now_ms, app_info=app_info)
        return app_info
