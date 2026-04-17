"""Minimal Feishu native OAPI HTTP seam."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from controlmesh.messenger.feishu.auth.errors import FeishuAuthError


class FeishuOAPIError(FeishuAuthError):
    """Raised when a Feishu OpenAPI response is non-OK."""


class FeishuNativeOAPIClient:
    """Small JSON client used by native tools before a larger SDK seam exists."""

    def __init__(self, session: Any, *, domain: str) -> None:
        self._session = session
        self._domain = domain.rstrip("/")

    async def get_json(
        self,
        path: str,
        *,
        access_token: str,
        params: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self.request_json(
            "GET",
            path,
            access_token=access_token,
            params=params,
        )

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        access_token: str,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._domain}{path}"
        async with self._session.request(
            method,
            url,
            params=dict(params or {}),
            json=dict(json_body or {}) if json_body is not None else None,
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            payload = await response.json(content_type=None)
            if not isinstance(payload, dict):
                raise FeishuOAPIError(
                    "Feishu OAPI response was not a JSON object",
                    status=response.status,
                )
            code = payload.get("code", 0)
            if response.status >= 400 or code not in (0, None):
                raise FeishuOAPIError(
                    "Feishu OAPI request failed",
                    code=code,
                    status=response.status,
                    payload=payload,
                )
            return payload
