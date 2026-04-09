"""Tests for Feishu bot routing on async/task return paths."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ductor_bot.config import AgentConfig
from ductor_bot.messenger.feishu.bot import FeishuBot


@dataclass
class _FakeTaskResult:
    task_id: str = "t1"
    chat_id: int = 123
    parent_agent: str = "main"
    name: str = "research"
    prompt_preview: str = "find info"
    result_text: str = "found it"
    status: str = "done"
    elapsed_seconds: float = 5.0
    provider: str = "claude"
    model: str = "sonnet"
    session_id: str = "tsid1"
    error: str = ""
    task_folder: str = "/tmp/tasks/t1"
    original_prompt: str = "find info about X"
    thread_id: int | None = None


def _make_bot(tmp_path: Path) -> FeishuBot:
    config = AgentConfig(
        transport="feishu",
        transports=["feishu"],
        ductor_home=str(tmp_path),
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
        },
    )
    bot = FeishuBot(config)
    bot.send_text = AsyncMock()  # type: ignore[method-assign]
    bot.broadcast_text = AsyncMock()  # type: ignore[method-assign]
    return bot


class TestFeishuBotRouting:
    async def test_on_task_result_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_result(_FakeTaskResult())

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_task_question_routes_to_fs_and_delivers(self, tmp_path: Path) -> None:
        bot = _make_bot(tmp_path)

        await bot.on_task_question("t1", "what color?", "what co...", 123)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()

    async def test_on_async_interagent_result_routes_to_fs_and_delivers(
        self,
        tmp_path: Path,
    ) -> None:
        bot = _make_bot(tmp_path)
        result = SimpleNamespace(
            task_id="ia1",
            sender="agent-a",
            recipient="agent-b",
            message_preview="please do X",
            result_text="done",
            success=True,
            error=None,
            elapsed_seconds=2.0,
            session_name="ia-agent-a",
            provider_switch_notice="",
            original_message="full message",
            chat_id=123,
            topic_id=None,
        )

        await bot.on_async_interagent_result(result)

        bot.send_text.assert_awaited()
        bot.broadcast_text.assert_not_awaited()
