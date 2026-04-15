"""Structured errors and error-code helpers for the Feishu auth core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class _LarkErrorCodes:
    APP_SCOPE_MISSING = 99991672
    USER_SCOPE_INSUFFICIENT = 99991679
    TOKEN_INVALID = 99991668
    TOKEN_EXPIRED = 99991677
    REFRESH_TOKEN_INVALID = 20026
    REFRESH_TOKEN_EXPIRED = 20037
    REFRESH_TOKEN_REVOKED = 20064
    REFRESH_TOKEN_ALREADY_USED = 20073
    REFRESH_SERVER_ERROR = 20050


LARK_ERROR = _LarkErrorCodes()

REFRESH_TOKEN_RETRYABLE: frozenset[int] = frozenset({LARK_ERROR.REFRESH_SERVER_ERROR})
TOKEN_RETRY_CODES: frozenset[int] = frozenset(
    {LARK_ERROR.TOKEN_INVALID, LARK_ERROR.TOKEN_EXPIRED}
)


class FeishuAuthError(Exception):
    """Base auth-core error with attached Feishu error metadata."""

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        status: int | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.payload = dict(payload) if payload is not None else None


class NeedAuthorizationError(FeishuAuthError):
    """Raised when no valid user token is available and OAuth must run later."""

    def __init__(self, user_open_id: str, message: str = "need_user_authorization") -> None:
        super().__init__(message)
        self.user_open_id = user_open_id


class DeviceAuthorizationError(FeishuAuthError):
    """Base error for OAuth device-flow request and poll failures."""


class DeviceAuthorizationPendingError(DeviceAuthorizationError):
    """Raised internally for non-terminal pending poll states."""


class DeviceAccessDeniedError(DeviceAuthorizationError):
    """Raised when the user rejects the device authorization request."""


class DeviceCodeExpiredError(DeviceAuthorizationError):
    """Raised when the device code has expired or become invalid."""


class TokenRefreshError(FeishuAuthError):
    """Raised when a token refresh response is malformed or unusable."""


class AppInfoAccessError(FeishuAuthError):
    """Raised when app metadata cannot be queried."""


def extract_feishu_error_code(err: BaseException) -> int | str | None:
    """Best-effort extraction of a Feishu server error code from an exception."""
    direct = getattr(err, "code", None)
    if isinstance(direct, int | str):
        return direct

    response = getattr(err, "response", None)
    if response is not None:
        data = getattr(response, "data", None)
        if isinstance(data, Mapping):
            code = data.get("code")
            if isinstance(code, int | str):
                return code

    return None
