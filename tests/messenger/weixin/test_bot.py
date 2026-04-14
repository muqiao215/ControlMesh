"""Tests for Weixin bot resilience seams."""

from __future__ import annotations

from pathlib import Path

import pytest

from ductor_bot.config import AgentConfig
from ductor_bot.messenger.weixin.auth_state import WeixinAuthStateStore
from ductor_bot.messenger.weixin.auth_store import StoredWeixinCredentials
from ductor_bot.messenger.weixin.bot import WeixinBot
from ductor_bot.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinReauthRequiredError,
)


def _make_bot(tmp_path: Path) -> WeixinBot:
    config = AgentConfig(
        ductor_home=str(tmp_path),
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
        from ductor_bot.__main__ import _is_configured
        from ductor_bot.workspace.paths import DuctorPaths

        bot = _make_bot(tmp_path)
        _save_credentials(bot)
        bot._runtime = _ExpiredRuntime()  # type: ignore[assignment]

        await bot._poll_loop()

        paths = DuctorPaths(
            ductor_home=tmp_path,
            home_defaults=tmp_path / "fw" / "workspace",
            framework_root=tmp_path / "fw",
        )
        paths.config_path.parent.mkdir(parents=True, exist_ok=True)
        config_json = f"""
            {{
              "transport": "weixin",
              "ductor_home": "{tmp_path}",
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

        with patch("ductor_bot.__main__.resolve_paths", return_value=paths):
            assert _is_configured() is False
