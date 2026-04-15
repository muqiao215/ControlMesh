"""Tests for the Feishu device-flow card auth bridge runner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.auth.card_auth import (
    complete_device_flow_card_auth,
    start_device_flow_card_auth,
)
from controlmesh.messenger.feishu.auth.card_auth_runner import (
    FeishuCardAuthRunner,
    is_card_auth_command,
)
from controlmesh.messenger.feishu.auth.device_flow import DeviceAuthorization, DeviceTokenGrant
from controlmesh.messenger.feishu.auth.feishu_card_sender import FeishuCardHandle
from controlmesh.messenger.feishu.auth.token_store import FeishuTokenStore
from controlmesh.messenger.feishu.bot import FeishuIncomingText


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_app",
            "app_secret": "sec_app",
        },
    )


def _authorization() -> DeviceAuthorization:
    return DeviceAuthorization(
        device_code="device-code",
        user_code="USER-123",
        verification_uri="https://verify.test/device",
        verification_uri_complete="https://verify.test/device?code=abc",
        expires_in=600,
        interval=5,
    )


def _message(text: str = "/feishu_auth") -> FeishuIncomingText:
    return FeishuIncomingText(
        sender_id="ou_sender",
        chat_id="oc_chat_1",
        message_id="om_1",
        text=text,
        thread_id="omt_1",
    )


class _FakeCardSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any], str | None]] = []
        self.updated: list[tuple[FeishuCardHandle, dict[str, Any]]] = []

    async def send_card(self, context: Any, card: dict[str, Any]) -> FeishuCardHandle:
        self.sent.append((context.chat_id, card, context.trigger_message_id))
        return FeishuCardHandle(chat_id=context.chat_id, message_id="om-card-1")

    async def update_card(self, handle: FeishuCardHandle, card: dict[str, Any]) -> None:
        self.updated.append((handle, card))


def test_is_card_auth_command_accepts_supported_explicit_triggers() -> None:
    assert is_card_auth_command("/feishu_auth") is True
    assert is_card_auth_command(" /feishu_auth ") is True
    assert is_card_auth_command("feishu auth") is True
    assert is_card_auth_command("授权飞书") is True
    assert is_card_auth_command("登录飞书") is True
    assert is_card_auth_command("ping") is False


@pytest.mark.asyncio
async def test_runner_starts_auth_updates_same_handle_on_success_and_stores_token(
    tmp_path: Path,
) -> None:
    sender = _FakeCardSender()
    duplicate_replies: list[tuple[str, str, str | None]] = []

    async def _request_authorization(
        session: object,
        *,
        app_id: str,
        app_secret: str,
        brand: str,
        scope: str | None,
    ) -> DeviceAuthorization:
        del session, app_id, app_secret, brand, scope
        return _authorization()

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
            scope="offline_access",
        )

    async def _verify_identity(*, session: object, brand: str, access_token: str) -> str:
        del session, brand
        assert access_token == "access-token"
        return "ou_sender"

    async def _start_auth(session: object, **kwargs: Any) -> Any:
        return await start_device_flow_card_auth(
            session,
            request_authorization=_request_authorization,
            **kwargs,
        )

    async def _complete_auth(session: object, **kwargs: Any) -> Any:
        return await complete_device_flow_card_auth(
            session,
            poll_token=_poll_token,
            **kwargs,
        )

    runner = FeishuCardAuthRunner(
        _config(tmp_path),
        session_factory=lambda: _return(object()),
        sender=sender,
        text_reply=lambda chat_id, text, reply_to: _record_reply(
            duplicate_replies,
            chat_id,
            text,
            reply_to,
        ),
        start_auth=_start_auth,
        complete_auth=_complete_auth,
        identity_verifier=_verify_identity,
        now_ms=lambda: 1_000_000,
    )

    handled = await runner.handle_message(_message())
    await asyncio.gather(*runner._tasks.values(), return_exceptions=True)

    assert handled is True
    assert duplicate_replies == []
    assert sender.sent[0][0] == "oc_chat_1"
    assert sender.sent[0][2] == "om_1"
    assert sender.updated[0][0] == FeishuCardHandle(chat_id="oc_chat_1", message_id="om-card-1")
    assert "authorization complete" in sender.updated[0][1]["elements"][0]["content"].lower()
    stored = FeishuTokenStore(tmp_path).load_token("cli_app", "ou_sender")
    assert stored is not None
    assert stored.access_token == "access-token"


@pytest.mark.asyncio
async def test_runner_duplicate_trigger_does_not_start_second_flow(tmp_path: Path) -> None:
    sender = _FakeCardSender()
    duplicate_replies: list[tuple[str, str, str | None]] = []
    started_calls = 0
    release = asyncio.Event()

    async def _start_auth(session: object, **kwargs: Any) -> Any:
        nonlocal started_calls
        del session
        started_calls += 1
        await kwargs["send_card"](
            sender_open_id=kwargs["sender_open_id"],
            card={"elements": [{"content": "pending"}]},
        )
        return type(
            "StartResult",
            (),
            {"authorization": _authorization(), "card": {"elements": [{"content": "pending"}]}},
        )()

    async def _complete_auth(session: object, **kwargs: Any) -> Any:
        del session, kwargs
        await release.wait()
        return type(
            "CompleteResult",
            (),
            {
                "status": "authorized",
                "actual_user_open_id": "ou_sender",
                "stored_token": None,
                "card": {"elements": [{"content": "done"}]},
            },
        )()

    runner = FeishuCardAuthRunner(
        _config(tmp_path),
        session_factory=lambda: _return(object()),
        sender=sender,
        text_reply=lambda chat_id, text, reply_to: _record_reply(
            duplicate_replies,
            chat_id,
            text,
            reply_to,
        ),
        start_auth=_start_auth,
        complete_auth=_complete_auth,
    )

    first_handled = await runner.handle_message(_message())
    second_handled = await runner.handle_message(_message())
    release.set()
    await asyncio.gather(*runner._tasks.values(), return_exceptions=True)

    assert first_handled is True
    assert second_handled is True
    assert started_calls == 1
    assert duplicate_replies == [
        ("oc_chat_1", "已有进行中的飞书授权, 请先完成当前授权。", "om_1")
    ]


@pytest.mark.asyncio
async def test_runner_updates_same_handle_on_identity_mismatch_without_storing(
    tmp_path: Path,
) -> None:
    sender = _FakeCardSender()

    async def _request_authorization(
        session: object,
        *,
        app_id: str,
        app_secret: str,
        brand: str,
        scope: str | None,
    ) -> DeviceAuthorization:
        del session, app_id, app_secret, brand, scope
        return _authorization()

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
            scope="offline_access",
        )

    async def _verify_identity(*, session: object, brand: str, access_token: str) -> str:
        del session, brand
        assert access_token == "access-token"
        return "ou_other_user"

    async def _start_auth(session: object, **kwargs: Any) -> Any:
        return await start_device_flow_card_auth(
            session,
            request_authorization=_request_authorization,
            **kwargs,
        )

    async def _complete_auth(session: object, **kwargs: Any) -> Any:
        return await complete_device_flow_card_auth(
            session,
            poll_token=_poll_token,
            **kwargs,
        )

    runner = FeishuCardAuthRunner(
        _config(tmp_path),
        session_factory=lambda: _return(object()),
        sender=sender,
        text_reply=lambda *_args: _return(None),
        start_auth=_start_auth,
        complete_auth=_complete_auth,
        identity_verifier=_verify_identity,
        now_ms=lambda: 1_000_000,
    )

    await runner.handle_message(_message())
    await asyncio.gather(*runner._tasks.values(), return_exceptions=True)

    assert sender.updated[0][0] == FeishuCardHandle(chat_id="oc_chat_1", message_id="om-card-1")
    assert "different feishu account" in sender.updated[0][1]["elements"][0]["content"].lower()
    assert FeishuTokenStore(tmp_path).load_token("cli_app", "ou_sender") is None


@pytest.mark.asyncio
async def test_runner_shutdown_cancels_inflight_tasks(tmp_path: Path) -> None:
    sender = _FakeCardSender()
    cancelled = asyncio.Event()

    async def _start_auth(session: object, **kwargs: Any) -> Any:
        del session
        await kwargs["send_card"](
            sender_open_id=kwargs["sender_open_id"],
            card={"elements": [{"content": "pending"}]},
        )
        return type(
            "StartResult",
            (),
            {"authorization": _authorization(), "card": {"elements": [{"content": "pending"}]}},
        )()

    async def _complete_auth(session: object, **kwargs: Any) -> Any:
        del session, kwargs
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runner = FeishuCardAuthRunner(
        _config(tmp_path),
        session_factory=lambda: _return(object()),
        sender=sender,
        text_reply=lambda *_args: _return(None),
        start_auth=_start_auth,
        complete_auth=_complete_auth,
    )

    await runner.handle_message(_message())
    await asyncio.sleep(0)
    await runner.shutdown()

    assert cancelled.is_set()
    assert runner._tasks == {}


async def _record_reply(
    sink: list[tuple[str, str, str | None]],
    chat_id: str,
    text: str,
    reply_to_message_id: str | None,
) -> None:
    sink.append((chat_id, text, reply_to_message_id))


async def _return(value: Any) -> Any:
    return value
