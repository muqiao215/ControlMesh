from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlencode

import requests

from .domains import open_platform_domain, resolve_domains
from .models import AppInfo, ScopeGrant, TenantAccessToken


class FeishuAuthKitError(RuntimeError):
    pass


class FeishuApiError(FeishuAuthKitError):
    pass


def build_permission_url(
    app_id: str,
    scopes: Iterable[str],
    brand: str = "feishu",
    token_type: str = "tenant",
    op_from: str = "feishu-auth-kit",
) -> str:
    query = {
        "q": ",".join(scope.strip() for scope in scopes if scope.strip()),
        "op_from": op_from,
        "token_type": token_type,
    }
    return f"{open_platform_domain(brand)}/app/{app_id}/auth?{urlencode(query)}"


class FeishuAuthClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        brand: str = "feishu",
        session: Any | None = None,
        timeout: int = 30,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.brand = brand
        self.timeout = timeout
        self.session = session or requests.Session()
        self.domains = resolve_domains(brand)
        self._tenant_token: TenantAccessToken | None = None
        self._app_info: AppInfo | None = None

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code", 0) not in (0, None):
            message = payload.get("msg") or payload.get("message") or "Unknown Feishu API error"
            raise FeishuApiError(str(message))
        return payload

    def get_tenant_access_token(self, *, force_refresh: bool = False) -> TenantAccessToken:
        if self._tenant_token and not force_refresh:
            return self._tenant_token

        payload = self._request_json(
            "POST",
            self.domains.tenant_token_url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        token = TenantAccessToken(
            token=str(payload["tenant_access_token"]),
            expire=payload.get("expire"),
        )
        self._tenant_token = token
        return token

    @staticmethod
    def parse_app_info(payload: dict[str, Any]) -> AppInfo:
        app = payload.get("data", {}).get("app") or payload.get("app") or payload.get("data") or {}
        owner = app.get("owner") or {}
        owner_type = owner.get("owner_type", owner.get("type"))
        owner_open_id = owner.get("owner_id")
        creator_id = app.get("creator_id")
        if owner_type == 2 and owner_open_id:
            effective_owner_open_id = owner_open_id
        else:
            effective_owner_open_id = creator_id or owner_open_id
        scopes = [
            ScopeGrant(
                scope=str(item["scope"]),
                token_types=[str(value) for value in item.get("token_types", [])],
            )
            for item in app.get("scopes", []) or app.get("online_version", {}).get("scopes", [])
            if item.get("scope")
        ]
        return AppInfo(
            app_id=str(app.get("app_id") or app.get("id") or app.get("cli_app_id") or ""),
            name=app.get("name"),
            creator_id=creator_id,
            owner_open_id=owner_open_id,
            owner_type=owner_type,
            effective_owner_open_id=effective_owner_open_id,
            scopes=scopes,
            raw_app=app,
        )

    def get_app_info(self, app_id: str = "me", *, force_refresh: bool = False) -> AppInfo:
        if self._app_info and not force_refresh and app_id in {"me", self._app_info.app_id}:
            return self._app_info

        tenant_token = self.get_tenant_access_token(force_refresh=force_refresh).token
        payload = self._request_json(
            "GET",
            f"{self.domains.app_info_base}/{app_id}",
            headers={"Authorization": f"Bearer {tenant_token}"},
            params={"lang": "en_us"},
        )
        app_info = self.parse_app_info(payload)
        self._app_info = app_info
        return app_info

    def get_granted_scopes(
        self,
        *,
        token_type: str | None = None,
        app_info: AppInfo | None = None,
    ) -> list[str]:
        current = app_info or self.get_app_info()
        scopes: list[str] = []
        for item in current.scopes:
            if token_type and item.token_types and token_type not in item.token_types:
                continue
            scopes.append(item.scope)
        return scopes

    def build_permission_url(
        self,
        app_id: str,
        *,
        scopes: Iterable[str],
        token_type: str = "tenant",
        op_from: str = "feishu-auth-kit",
    ) -> str:
        return build_permission_url(
            app_id=app_id,
            scopes=scopes,
            brand=self.brand,
            token_type=token_type,
            op_from=op_from,
        )

