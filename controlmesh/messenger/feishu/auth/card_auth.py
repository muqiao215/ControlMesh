"""Additive Feishu device-flow card auth orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from controlmesh.messenger.feishu.auth.auth_cards import (
    build_auth_card,
    build_auth_success_card,
    build_identity_mismatch_card,
)
from controlmesh.messenger.feishu.auth.device_flow import (
    DeviceAuthorization,
    DeviceTokenGrant,
    poll_device_token,
    request_device_authorization,
)
from controlmesh.messenger.feishu.auth.token_store import (
    FeishuTokenStore,
    StoredFeishuToken,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass(frozen=True, slots=True)
class DeviceFlowCardAuthStart:
    sender_open_id: str
    authorization: DeviceAuthorization
    card: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeviceFlowCardAuthResult:
    status: Literal["authorized", "identity_mismatch"]
    sender_open_id: str
    actual_user_open_id: str
    stored_token: StoredFeishuToken | None
    card: dict[str, Any]


def _scope_with_offline_access(scope: str | None) -> str:
    parts = [part for part in (scope or "").split() if part]
    if "offline_access" not in parts:
        parts.append("offline_access")
    return " ".join(parts)


async def start_device_flow_card_auth(  # noqa: PLR0913
    session: Any,
    *,
    app_id: str,
    app_secret: str,
    sender_open_id: str,
    brand: str = "feishu",
    scope: str | None = None,
    request_authorization: Callable[..., Awaitable[DeviceAuthorization]] = request_device_authorization,
    card_builder: Callable[..., dict[str, Any]] = build_auth_card,
    send_card: Callable[..., Awaitable[None]] | None = None,
) -> DeviceFlowCardAuthStart:
    """Start a device-flow auth request and return the auth card payload."""
    authorization = await request_authorization(
        session,
        app_id=app_id,
        app_secret=app_secret,
        brand=brand,
        scope=scope,
    )
    card = card_builder(
        verification_uri_complete=authorization.verification_uri_complete,
        expires_in=authorization.expires_in,
        scope=_scope_with_offline_access(scope),
        user_code=authorization.user_code,
    )
    if send_card is not None:
        await send_card(sender_open_id=sender_open_id, card=card)
    return DeviceFlowCardAuthStart(
        sender_open_id=sender_open_id,
        authorization=authorization,
        card=card,
    )


async def complete_device_flow_card_auth(  # noqa: PLR0913
    session: Any,
    *,
    app_id: str,
    app_secret: str,
    sender_open_id: str,
    authorization: DeviceAuthorization,
    token_store: FeishuTokenStore,
    identity_verifier: Callable[..., Awaitable[str]],
    brand: str = "feishu",
    poll_token: Callable[..., Awaitable[DeviceTokenGrant]] = poll_device_token,
    now_ms: Callable[[], int] | None = None,
    send_result_card: Callable[..., Awaitable[None]] | None = None,
) -> DeviceFlowCardAuthResult:
    """Poll device-flow completion, verify identity, and persist the user token."""
    grant = await poll_token(
        session,
        app_id=app_id,
        app_secret=app_secret,
        brand=brand,
        device_code=authorization.device_code,
        interval=authorization.interval,
        expires_in=authorization.expires_in,
    )
    actual_user_open_id = await identity_verifier(access_token=grant.access_token)
    if actual_user_open_id != sender_open_id:
        card = build_identity_mismatch_card(
            expected_open_id=sender_open_id,
            actual_open_id=actual_user_open_id,
        )
        if send_result_card is not None:
            await send_result_card(sender_open_id=sender_open_id, card=card)
        return DeviceFlowCardAuthResult(
            status="identity_mismatch",
            sender_open_id=sender_open_id,
            actual_user_open_id=actual_user_open_id,
            stored_token=None,
            card=card,
        )

    current_ms = now_ms() if now_ms is not None else int(time.time() * 1000)
    stored_token = StoredFeishuToken(
        user_open_id=sender_open_id,
        app_id=app_id,
        access_token=grant.access_token,
        refresh_token=grant.refresh_token,
        expires_at=current_ms + grant.expires_in * 1000,
        refresh_expires_at=current_ms + grant.refresh_token_expires_in * 1000,
        scope=grant.scope,
        granted_at=current_ms,
    )
    token_store.save_token(stored_token)
    card = build_auth_success_card(scope=grant.scope)
    if send_result_card is not None:
        await send_result_card(sender_open_id=sender_open_id, card=card)
    return DeviceFlowCardAuthResult(
        status="authorized",
        sender_open_id=sender_open_id,
        actual_user_open_id=actual_user_open_id,
        stored_token=stored_token,
        card=card,
    )
