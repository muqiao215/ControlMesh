"""Tests for the Feishu device-flow card auth interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from controlmesh.messenger.feishu.auth.card_auth import (
    complete_device_flow_card_auth,
    start_device_flow_card_auth,
)
from controlmesh.messenger.feishu.auth.device_flow import DeviceAuthorization, DeviceTokenGrant
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore


def _authorization(**overrides: object) -> DeviceAuthorization:
    data: dict[str, object] = {
        "device_code": "device-code",
        "user_code": "USER-123",
        "verification_uri": "https://verify.test/device",
        "verification_uri_complete": "https://verify.test/device?code=abc",
        "expires_in": 600,
        "interval": 5,
    }
    data.update(overrides)
    return DeviceAuthorization(**data)


@pytest.mark.asyncio
async def test_start_device_flow_card_auth_requests_authorization_and_returns_card_payload() -> None:
    seen: dict[str, Any] = {}
    sent_cards: list[tuple[str, dict[str, Any]]] = []

    async def _request_authorization(
        session: object,
        *,
        app_id: str,
        app_secret: str,
        brand: str,
        scope: str | None,
    ) -> DeviceAuthorization:
        seen.update(
            {
                "session": session,
                "app_id": app_id,
                "app_secret": app_secret,
                "brand": brand,
                "scope": scope,
            }
        )
        return _authorization()

    async def _send_card(*, sender_open_id: str, card: dict[str, Any]) -> None:
        sent_cards.append((sender_open_id, card))

    session = object()
    result = await start_device_flow_card_auth(
        session,
        app_id="cli_app",
        app_secret="sec_app",
        sender_open_id="ou_sender",
        scope="im:message",
        request_authorization=_request_authorization,
        send_card=_send_card,
    )

    assert seen == {
        "session": session,
        "app_id": "cli_app",
        "app_secret": "sec_app",
        "brand": "feishu",
        "scope": "im:message",
    }
    assert result.authorization == _authorization()
    assert sent_cards == [("ou_sender", result.card)]
    assert (
        result.card["elements"][1]["actions"][0]["multi_url"]["url"]
        == "https://verify.test/device?code=abc"
    )


@pytest.mark.asyncio
async def test_complete_device_flow_card_auth_polls_verifies_identity_and_stores_token(
    tmp_path: Path,
) -> None:
    store = FeishuTokenStore(tmp_path)
    polled: dict[str, Any] = {}

    async def _poll_token(
        session: object,
        *,
        app_id: str,
        app_secret: str,
        brand: str,
        device_code: str,
        interval: int,
        expires_in: int,
    ) -> DeviceTokenGrant:
        polled.update(
            {
                "session": session,
                "app_id": app_id,
                "app_secret": app_secret,
                "brand": brand,
                "device_code": device_code,
                "interval": interval,
                "expires_in": expires_in,
            }
        )
        return DeviceTokenGrant(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=7200,
            refresh_token_expires_in=86400,
            scope="offline_access im:message",
        )

    async def _verify_identity(*, access_token: str) -> str:
        assert access_token == "access-token"
        return "ou_sender"

    session = object()
    result = await complete_device_flow_card_auth(
        session,
        app_id="cli_app",
        app_secret="sec_app",
        sender_open_id="ou_sender",
        authorization=_authorization(),
        token_store=store,
        identity_verifier=_verify_identity,
        poll_token=_poll_token,
        now_ms=lambda: 1_000_000,
    )

    assert polled == {
        "session": session,
        "app_id": "cli_app",
        "app_secret": "sec_app",
        "brand": "feishu",
        "device_code": "device-code",
        "interval": 5,
        "expires_in": 600,
    }
    assert result.status == "authorized"
    assert result.actual_user_open_id == "ou_sender"
    stored = store.load_token("cli_app", "ou_sender")
    assert stored == result.stored_token
    assert stored is not None
    assert stored.access_token == "access-token"
    assert stored.refresh_token == "refresh-token"
    assert stored.expires_at == 8_200_000
    assert stored.refresh_expires_at == 87_400_000
    assert stored.scope == "offline_access im:message"
    assert stored.granted_at == 1_000_000


@pytest.mark.asyncio
async def test_complete_device_flow_card_auth_rejects_identity_mismatch_without_storing(
    tmp_path: Path,
) -> None:
    store = FeishuTokenStore(tmp_path)

    async def _poll_token(
        session: object,
        *,
        app_id: str,
        app_secret: str,
        brand: str,
        device_code: str,
        interval: int,
        expires_in: int,
    ) -> DeviceTokenGrant:
        del session, app_id, app_secret, brand, device_code, interval, expires_in
        return DeviceTokenGrant(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=7200,
            refresh_token_expires_in=86400,
            scope="offline_access im:message",
        )

    async def _verify_identity(*, access_token: str) -> str:
        assert access_token == "access-token"
        return "ou_other_user"

    result = await complete_device_flow_card_auth(
        object(),
        app_id="cli_app",
        app_secret="sec_app",
        sender_open_id="ou_sender",
        authorization=_authorization(),
        token_store=store,
        identity_verifier=_verify_identity,
        poll_token=_poll_token,
        now_ms=lambda: 1_000_000,
    )

    assert result.status == "identity_mismatch"
    assert result.actual_user_open_id == "ou_other_user"
    assert result.stored_token is None
    assert store.load_token("cli_app", "ou_sender") is None
    assert "ou_sender" in result.card["elements"][0]["content"]
    assert "ou_other_user" in result.card["elements"][0]["content"]
