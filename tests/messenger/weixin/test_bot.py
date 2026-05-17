"""Tests for Weixin bot resilience seams."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.infra.restart import EXIT_RESTART
from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials
from controlmesh.messenger.weixin.api import WeixinIlinkApiError
from controlmesh.messenger.weixin.bot import WeixinBot
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinPollResult,
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


class _RecoverableFailRuntime:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.cursor = "cursor-before-error"

    async def poll_once(self) -> WeixinPollResult:
        raise self._exc


class _StallRuntime:
    def __init__(self) -> None:
        self.cursor = "cursor-before-stall"

    async def poll_once(self) -> WeixinPollResult:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


class _SuccessfulPollRuntime:
    def __init__(self, cursor: str = "cursor-after-rebuild") -> None:
        self.cursor = cursor
        self.poll_calls = 0

    async def poll_once(self) -> WeixinPollResult:
        self.poll_calls += 1
        return WeixinPollResult(
            cursor=self.cursor,
            message_count=0,
            delivered_text_count=0,
        )


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

    async def test_poll_loop_marks_recoverable_http_error_dirty_and_rebuilds_transport(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bot = _make_bot(tmp_path)
        _save_credentials(bot)
        bot._runtime = _RecoverableFailRuntime(
            WeixinIlinkApiError("conflict", status=409, code=409),
        )  # type: ignore[assignment]
        bot._stop_event = MagicMock()
        bot._stop_event.is_set.side_effect = [False, False, True]
        bot._wait_for_retry_delay = AsyncMock()  # type: ignore[method-assign]
        rebuilt_runtime = _SuccessfulPollRuntime()
        bot._build_runtime = MagicMock(return_value=rebuilt_runtime)  # type: ignore[method-assign]
        bot._close_transport_session = AsyncMock()  # type: ignore[method-assign]
        bot._ensure_session = MagicMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await bot._poll_loop()

        assert bot._build_runtime.call_count == 1
        assert rebuilt_runtime.poll_calls == 1
        assert bot._poll_diagnostics.transport_dirty is False
        assert bot._poll_diagnostics.consecutive_failures == 0
        assert bot._poll_diagnostics.last_poll_cursor == "cursor-after-rebuild"
        assert bot._runtime is rebuilt_runtime
        assert bot._close_transport_session.await_count == 1
        assert "marked transport dirty reason=poll_conflict_409" in caplog.text

    async def test_poll_loop_treats_timeout_as_stall_and_rebuilds_transport(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        bot = _make_bot(tmp_path)
        _save_credentials(bot)
        bot._runtime = _StallRuntime()  # type: ignore[assignment]
        bot._stop_event = MagicMock()
        bot._stop_event.is_set.side_effect = [False, False, True]
        bot._wait_for_retry_delay = AsyncMock()  # type: ignore[method-assign]
        bot._poll_stall_timeout_seconds = 0.01
        rebuilt_runtime = _SuccessfulPollRuntime(cursor="cursor-after-stall")
        bot._build_runtime = MagicMock(return_value=rebuilt_runtime)  # type: ignore[method-assign]
        bot._close_transport_session = AsyncMock()  # type: ignore[method-assign]
        bot._ensure_session = MagicMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING):
            await bot._poll_loop()

        assert bot._build_runtime.call_count == 1
        assert rebuilt_runtime.poll_calls == 1
        assert bot._runtime is rebuilt_runtime
        assert bot._poll_diagnostics.last_poll_cursor == "cursor-after-stall"
        assert "marked transport dirty reason=poll_stall" in caplog.text

    async def test_watch_restart_marker_requests_restart(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        with (
            patch.object(asyncio, "sleep", new_callable=AsyncMock),
            patch.object(asyncio, "to_thread", new_callable=AsyncMock) as mock_to_thread,
        ):
            mock_to_thread.return_value = True
            await bot._watch_restart_marker()

        assert bot._exit_code == EXIT_RESTART
        assert bot._stop_event.is_set() is True

    async def test_watch_restart_marker_handles_cancellation(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        with patch.object(
            asyncio, "sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError
        ):
            await bot._watch_restart_marker()

        assert bot._exit_code == 0
        assert bot._stop_event.is_set() is False

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
