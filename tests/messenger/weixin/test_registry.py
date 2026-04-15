"""Tests for Weixin transport registration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from controlmesh.messenger.registry import create_bot


def test_weixin_transport() -> None:
    config = MagicMock()
    config.transport = "weixin"
    config.is_multi_transport = False
    fake_bot = MagicMock()
    with patch("controlmesh.messenger.weixin.bot.WeixinBot", return_value=fake_bot):
        bot = create_bot(config, agent_name="test")
    assert bot is fake_bot
