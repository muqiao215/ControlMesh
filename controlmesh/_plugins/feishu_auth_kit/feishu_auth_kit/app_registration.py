from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .domains import resolve_domains

REGISTRATION_PATH = "/oauth/v1/app/registration"
DEFAULT_REGISTRATION_ARCHETYPE = "PersonalAgent"
DEFAULT_REGISTRATION_AUTH_METHOD = "client_secret"
DEFAULT_REGISTRATION_USER_INFO = "open_id"
DEFAULT_QR_FROM = "oc_onboard"
DEFAULT_QR_TP = "ob_cli_app"
DEFAULT_POLL_TP = "ob_app"


class AppRegistrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppRegistrationInitResult:
    nonce: str | None
    supported_auth_methods: list[str]


@dataclass(frozen=True)
class AppRegistrationBeginResult:
    device_code: str
    qr_url: str
    user_code: str
    interval: int
    expires_in: int
    verification_uri: str
    verification_uri_complete: str


@dataclass(frozen=True)
class AppRegistrationResult:
    app_id: str
    app_secret: str
    domain: str
    open_id: str | None = None


@dataclass(frozen=True)
class AppRegistrationPollResult:
    status: str
    result: AppRegistrationResult | None = None
    message: str | None = None


class AppRegistrationClient:
    def __init__(
        self,
        *,
        brand: str = "feishu",
        session: Any | None = None,
        timeout: int = 10,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.brand = brand
        self.session = session or requests.Session()
        self.timeout = timeout
        self.sleeper = sleeper

    def _accounts_base(self, brand: str | None = None) -> str:
        return resolve_domains(brand or self.brand).accounts_base

    def _post_registration(
        self,
        body: dict[str, str],
        *,
        brand: str | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            "POST",
            f"{self._accounts_base(brand)}{REGISTRATION_PATH}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=urlencode(body),
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except Exception as exc:  # pragma: no cover - defensive path
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            raise AppRegistrationError(f"Invalid registration response: {exc}") from exc
        if not isinstance(payload, dict):
            raise AppRegistrationError("Invalid registration response payload")
        return payload

    def init(self) -> AppRegistrationInitResult:
        payload = self._post_registration({"action": "init"})
        _raise_registration_payload_error(payload)
        supported = [str(value) for value in payload.get("supported_auth_methods", [])]
        if DEFAULT_REGISTRATION_AUTH_METHOD not in supported:
            raise AppRegistrationError(
                "Current environment does not support client_secret app registration"
            )
        return AppRegistrationInitResult(
            nonce=payload.get("nonce"),
            supported_auth_methods=supported,
        )

    def begin(self) -> AppRegistrationBeginResult:
        payload = self._post_registration(
            {
                "action": "begin",
                "archetype": DEFAULT_REGISTRATION_ARCHETYPE,
                "auth_method": DEFAULT_REGISTRATION_AUTH_METHOD,
                "request_user_info": DEFAULT_REGISTRATION_USER_INFO,
            }
        )
        _raise_registration_payload_error(payload)
        verification_uri_complete = str(
            payload.get("verification_uri_complete") or payload.get("verification_uri") or ""
        )
        if not verification_uri_complete:
            raise AppRegistrationError("Registration begin response did not include a QR URL")
        qr_url = _with_query_params(
            verification_uri_complete,
            {
                "from": DEFAULT_QR_FROM,
                "tp": DEFAULT_QR_TP,
            },
        )
        return AppRegistrationBeginResult(
            device_code=str(payload["device_code"]),
            qr_url=qr_url,
            user_code=str(payload["user_code"]),
            interval=int(payload.get("interval") or 5),
            expires_in=int(payload.get("expire_in") or payload.get("expires_in") or 600),
            verification_uri=str(payload.get("verification_uri") or verification_uri_complete),
            verification_uri_complete=verification_uri_complete,
        )

    def poll(
        self,
        device_code: str,
        *,
        interval: int = 5,
        expires_in: int = 600,
        tp: str = DEFAULT_POLL_TP,
        poll_timeout: int | None = None,
    ) -> AppRegistrationPollResult:
        current_interval = max(int(interval or 5), 1)
        max_wait = expires_in if poll_timeout is None else min(expires_in, poll_timeout)
        deadline = time.monotonic() + max(max_wait, 0)
        domain = self.brand
        domain_switched = False

        while time.monotonic() <= deadline:
            payload = self._post_registration(
                {
                    "action": "poll",
                    "device_code": device_code,
                    "tp": tp,
                },
                brand=domain,
            )

            user_info = (
                payload.get("user_info") if isinstance(payload.get("user_info"), dict) else {}
            )
            tenant_brand = user_info.get("tenant_brand") if user_info else None
            if tenant_brand == "lark" and domain != "lark" and not domain_switched:
                domain = "lark"
                domain_switched = True
                continue

            app_id = payload.get("client_id")
            app_secret = payload.get("client_secret")
            if app_id and app_secret:
                return AppRegistrationPollResult(
                    status="success",
                    result=AppRegistrationResult(
                        app_id=str(app_id),
                        app_secret=str(app_secret),
                        domain="lark" if tenant_brand == "lark" else domain,
                        open_id=user_info.get("open_id") if user_info else None,
                    ),
                )

            error = payload.get("error")
            if error == "authorization_pending" or not error:
                self.sleeper(current_interval)
                continue
            if error == "slow_down":
                current_interval += 5
                self.sleeper(current_interval)
                continue
            if error == "access_denied":
                return AppRegistrationPollResult(status="access_denied")
            if error == "expired_token":
                return AppRegistrationPollResult(status="expired")

            description = payload.get("error_description") or "unknown"
            return AppRegistrationPollResult(status="error", message=f"{error}: {description}")

        return AppRegistrationPollResult(status="timeout")


def _with_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _raise_registration_payload_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if error:
        description = payload.get("error_description") or error
        raise AppRegistrationError(str(description))
