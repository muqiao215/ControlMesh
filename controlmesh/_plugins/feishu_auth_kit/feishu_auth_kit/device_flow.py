from __future__ import annotations

import base64
import time
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlencode

import requests

from .domains import resolve_domains
from .models import DeviceAuthorization, DeviceToken


class DeviceFlowError(RuntimeError):
    pass


class DeviceFlowClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        brand: str = "feishu",
        session: Any | None = None,
        timeout: int = 30,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.brand = brand
        self.domains = resolve_domains(brand)
        self.session = session or requests.Session()
        self.timeout = timeout
        self.sleeper = sleeper

    @staticmethod
    def _scope_string(scopes: Iterable[str]) -> str:
        items: list[str] = []
        seen: set[str] = set()
        for scope in scopes:
            normalized = scope.strip()
            if normalized and normalized not in seen:
                items.append(normalized)
                seen.add(normalized)
        if "offline_access" not in seen:
            items.append("offline_access")
        return " ".join(items)

    def request_authorization(self, scopes: Iterable[str]) -> DeviceAuthorization:
        scope_string = self._scope_string(scopes)
        basic = base64.b64encode(f"{self.app_id}:{self.app_secret}".encode()).decode("ascii")
        response = self.session.request(
            "POST",
            self.domains.device_authorization_url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=urlencode({"client_id": self.app_id, "scope": scope_string}),
            timeout=self.timeout,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        payload = response.json()
        error = payload.get("error")
        if error:
            detail = payload.get("error_description") or error
            raise DeviceFlowError(str(detail))
        return DeviceAuthorization(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            verification_uri_complete=str(
                payload.get("verification_uri_complete", payload["verification_uri"])
            ),
            expires_in=int(payload.get("expires_in", 240)),
            interval=int(payload.get("interval", 5)),
        )

    def poll_for_token(
        self,
        device_code: str,
        *,
        interval: int = 5,
        expires_in: int = 240,
    ) -> DeviceToken:
        deadline = time.time() + expires_in
        current_interval = max(interval, 1)
        while time.time() < deadline:
            self.sleeper(current_interval)
            response = self.session.request(
                "POST",
                self.domains.oauth_token_url,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data=urlencode(
                    {
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code,
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                    }
                ),
                timeout=self.timeout,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = response.json()
            error = payload.get("error")
            if not error and payload.get("access_token"):
                return DeviceToken(
                    access_token=str(payload["access_token"]),
                    refresh_token=payload.get("refresh_token"),
                    expires_in=payload.get("expires_in"),
                    refresh_expires_in=payload.get("refresh_expires_in"),
                    scope=payload.get("scope"),
                )
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                current_interval += 5
                continue
            detail = payload.get("error_description") or error or "Device flow failed"
            raise DeviceFlowError(str(detail))
        raise DeviceFlowError("Device code expired before authorization completed")

