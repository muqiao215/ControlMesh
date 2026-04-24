from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.notifications import CompositeNotificationService
from controlmesh.multiagent.supervisor import AgentSupervisor
from controlmesh.qq_bridge import relay as relay_mod
from controlmesh.qq_bridge.relay import attach_qq_bridge_relay, get_qq_bridge_relay
from controlmesh.tasks.models import TaskEntry, TaskResult


class _BaseNotificationService:
    def __init__(self) -> None:
        self.notify = AsyncMock()
        self.notify_all = AsyncMock()


def test_attach_qq_bridge_relay_wraps_notification_service(monkeypatch) -> None:
    monkeypatch.setenv("CONTROLMESH_QQBOT_HOOK_URL", "http://127.0.0.1:3187")
    monkeypatch.setenv("CONTROLMESH_QQBOT_HOOK_TOKEN", "secret")

    bot = SimpleNamespace(_notification_service=_BaseNotificationService())

    relay = attach_qq_bridge_relay(bot)

    assert relay is not None
    assert get_qq_bridge_relay(bot) is relay
    assert isinstance(bot._notification_service, CompositeNotificationService)


@pytest.mark.asyncio
async def test_attach_qq_bridge_relay_keeps_base_notifications_working_on_relay_failure(
    monkeypatch,
) -> None:
    class _FailingRelay:
        async def notify(self, chat_id: int, text: str) -> None:
            raise RuntimeError(f"down:{chat_id}:{text}")

        async def notify_all(self, text: str) -> None:
            raise RuntimeError(f"down:all:{text}")

    monkeypatch.setattr(
        relay_mod.QqBridgeNotificationService,
        "from_env",
        classmethod(lambda cls: _FailingRelay()),
    )

    base = _BaseNotificationService()
    bot = SimpleNamespace(_notification_service=base)

    relay = attach_qq_bridge_relay(bot)

    assert relay is not None
    await bot._notification_service.notify(123, "hello")
    await bot._notification_service.notify_all("global")

    base.notify.assert_awaited_once_with(123, "hello")
    base.notify_all.assert_awaited_once_with("global")


@pytest.mark.asyncio
async def test_supervisor_task_hub_prefers_qq_relay_for_qq_tasks(tmp_path) -> None:
    config = AgentConfig(
        controlmesh_home=str(tmp_path),
        telegram_token="main-token",
        allowed_user_ids=[1],
    )
    supervisor = AgentSupervisor(config)

    qq_relay = SimpleNamespace(
        deliver_task_result=AsyncMock(),
        deliver_task_question=AsyncMock(),
    )
    bot = SimpleNamespace(
        orchestrator=SimpleNamespace(set_task_hub=MagicMock(), cli_service=MagicMock()),
        on_task_result=AsyncMock(),
        on_task_question=AsyncMock(),
        _qq_bridge_relay=qq_relay,
    )
    stack = SimpleNamespace(
        name="main",
        bot=bot,
        paths=MagicMock(),
        config=config,
    )
    entry = TaskEntry(
        task_id="t1",
        chat_id=54321,
        parent_agent="main",
        name="qq task",
        prompt_preview="preview",
        provider="codex",
        model="gpt-5",
        status="running",
        transport="qq",
        thread_id=12345,
    )
    hub = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _task_id: entry),
        set_cli_service=MagicMock(),
        set_agent_paths=MagicMock(),
        set_result_handler=MagicMock(),
        set_question_handler=MagicMock(),
        set_agent_chat_id=MagicMock(),
    )
    supervisor._task_hub = hub

    supervisor._wire_task_hub(stack)

    result_handler = hub.set_result_handler.call_args.args[1]
    question_handler = hub.set_question_handler.call_args.args[1]

    await result_handler(
        TaskResult(
            task_id="t1",
            chat_id=54321,
            parent_agent="main",
            name="qq task",
            prompt_preview="preview",
            result_text="done",
            status="done",
            elapsed_seconds=3.0,
            provider="codex",
            model="gpt-5",
            transport="qq",
            thread_id=12345,
        )
    )
    await question_handler("t1", "Need a date", "preview", 54321, 12345)

    qq_relay.deliver_task_result.assert_awaited_once()
    qq_relay.deliver_task_question.assert_awaited_once_with(
        task_id="t1",
        question="Need a date",
        prompt_preview="preview",
        chat_id=54321,
        thread_id=12345,
    )
    bot.on_task_result.assert_not_awaited()
    bot.on_task_question.assert_not_awaited()
