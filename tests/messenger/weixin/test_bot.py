"""Tests for Weixin bot resilience seams."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.bot import WeixinBot
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinReauthRequiredError,
)


def _make_bot(tmp_path: Path) -> WeixinBot:
    config = AgentConfig(
        controlmesh_home=str(tmp_path),
        transport="weixin",
        transports=["weixin"],
        weixin={
            "mode": "ilink",
            "enabled": True,
            "credentials_path": "weixin_store/credentials.json",
        },
    )
    return WeixinBot(config)


def _save_credentials(bot: WeixinBot) -> None:
    bot._credential_store.save_credentials(
        StoredWeixinCredentials(
            token="bot-token",
            base_url="https://ilinkai.weixin.qq.com",
            account_id="bot-account",
            user_id="wx-user",
        )
    )


class _ExpiredRuntime:
    async def poll_once(self) -> None:
        raise WeixinReauthRequiredError("Weixin iLink session expired")


class _RecordingRuntime:
    def __init__(self, *, fail_reply: bool = False, fail_send: bool = False) -> None:
        self.reply_calls: list[tuple[WeixinIncomingText, str]] = []
        self.send_calls: list[tuple[str, str]] = []
        self.fail_reply = fail_reply
        self.fail_send = fail_send

    async def reply(self, message: WeixinIncomingText, text: str) -> None:
        if self.fail_reply:
            raise RuntimeError("reply failed")
        self.reply_calls.append((message, text))

    async def send_text(self, user_id: str, text: str) -> None:
        if self.fail_send:
            raise RuntimeError("send failed")
        self.send_calls.append((user_id, text))


class _FakeOrchestrator:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[object, str]] = []

    async def handle_message_streaming(self, key: object, text: str) -> object:
        self.calls.append((key, text))
        return type("Result", (), {"text": self.text})()


class TestWeixinBotResilience:
    async def test_poll_loop_clears_credentials_when_runtime_requires_reauth(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        _save_credentials(bot)
        bot._runtime = _ExpiredRuntime()  # type: ignore[assignment]

        await bot._poll_loop()

        assert bot._credential_store.load_credentials() is None
        assert WeixinAuthStateStore(tmp_path).load_state() == "reauth_required"
        assert bot._runtime is None
        assert bot._stop_event.is_set() is True

    async def test_proactive_send_unknown_chat_fails_explicitly(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        with pytest.raises(WeixinContextTokenRequiredError, match="No Weixin user mapping"):
            await bot.send_text(123, "proactive")

    async def test_task_result_send_unknown_chat_fails_explicitly(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)
        result = type("TaskResult", (), {"chat_id": 123, "result_text": "done"})()

        with pytest.raises(WeixinContextTokenRequiredError, match="No Weixin user mapping"):
            await bot.on_task_result(result)

    async def test_config_check_downgrades_after_expiry_clears_store(self, tmp_path: Path) -> None:
        from controlmesh.__main__ import _is_configured
        from controlmesh.workspace.paths import ControlMeshPaths

        bot = _make_bot(tmp_path)
        _save_credentials(bot)
        bot._runtime = _ExpiredRuntime()  # type: ignore[assignment]

        await bot._poll_loop()

        paths = ControlMeshPaths(
            controlmesh_home=tmp_path,
            home_defaults=tmp_path / "fw" / "workspace",
            framework_root=tmp_path / "fw",
        )
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        config_json = f"""
            {{
              "transport": "weixin",
              "controlmesh_home": "{tmp_path}",
              "weixin": {{
                "mode": "ilink",
                "enabled": true,
                "credentials_path": "weixin_store/credentials.json"
              }}
            }}
            """
        paths.config_path.write_text(
            config_json,
            encoding="utf-8",
        )

        from unittest.mock import patch

        with patch("controlmesh.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False

    async def test_handle_incoming_text_logs_reply_success(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bot = _make_bot(tmp_path)
        runtime = _RecordingRuntime()
        bot._runtime = runtime  # type: ignore[assignment]
        bot._orchestrator = _FakeOrchestrator("OK")  # type: ignore[assignment]
        message = WeixinIncomingText(
            user_id="wx-user",
            text="ping",
            context_token="ctx-1",
            message_id=7,
            raw={"message_id": 7},
        )

        with caplog.at_level(logging.INFO):
            await bot.handle_incoming_text(message)

        assert runtime.reply_calls == [(message, "OK")]
        assert "Accepted Weixin message" in caplog.text
        assert "Weixin reply start" in caplog.text
        assert "Weixin reply success" in caplog.text

    async def test_handle_incoming_text_logs_reply_failure(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bot = _make_bot(tmp_path)
        runtime = _RecordingRuntime(fail_reply=True)
        bot._runtime = runtime  # type: ignore[assignment]
        bot._orchestrator = _FakeOrchestrator("OK")  # type: ignore[assignment]
        message = WeixinIncomingText(
            user_id="wx-user",
            text="ping",
            context_token="ctx-1",
            message_id=8,
            raw={"message_id": 8},
        )

        with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match="reply failed"):
            await bot.handle_incoming_text(message)

        assert "Weixin reply failed" in caplog.text

    async def test_send_text_logs_success(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bot = _make_bot(tmp_path)
        runtime = _RecordingRuntime()
        bot._runtime = runtime  # type: ignore[assignment]
        bot._id_map.user_to_int("wx-user")

        with caplog.at_level(logging.INFO):
            await bot.send_text(bot._id_map.user_to_int("wx-user"), "hello")

        assert runtime.send_calls == [("wx-user", "hello")]
        assert "Weixin send_text start" in caplog.text
        assert "Weixin send_text success" in caplog.text
