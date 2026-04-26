"""Tests for narrow ControlMesh runtime adapters exposed to the agents backend."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from controlmesh.agents_runtime.context import AgentsRuntimeContext
from controlmesh.agents_runtime.manager import AgentsRuntimeManager
from controlmesh.agents_runtime.tools import (
    ask_parent,
    check_parent_updates,
    create_background_task,
    resume_background_task,
    send_async_to_agent,
    tell_background_task,
)
from controlmesh.multiagent.bus import AsyncSendOptions


async def test_create_background_task_uses_task_hub_submit() -> None:
    hub = MagicMock()
    hub.submit.return_value = "task1234"
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=7,
        process_label="main",
        task_hub=hub,
    )

    result = await create_background_task(
        ctx,
        prompt="Investigate the repo",
        name="Repo research",
        provider_override="codex",
        model_override="gpt-5.4",
        thinking_override="high",
    )

    assert result.ok is True
    assert result.operation == "create_background_task"
    assert result.data["task_id"] == "task1234"
    submit = hub.submit.call_args.args[0]
    assert submit.chat_id == 42
    assert submit.thread_id == 7
    assert submit.parent_agent == "main"
    assert submit.name == "Repo research"
    assert submit.provider_override == "codex"
    assert submit.model_override == "gpt-5.4"
    assert submit.thinking_override == "high"


async def test_resume_background_task_uses_task_hub_resume() -> None:
    hub = MagicMock()
    hub.resume.return_value = "task1234"
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="main",
        task_hub=hub,
    )

    result = await resume_background_task(ctx, task_id="task1234", follow_up="Keep going")

    assert result.ok is True
    assert result.data["task_id"] == "task1234"
    hub.resume.assert_called_once_with("task1234", "Keep going", parent_agent="main")


async def test_tell_background_task_uses_task_hub_tell() -> None:
    hub = MagicMock()
    hub.tell.return_value = 3
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="main",
        task_hub=hub,
    )

    result = await tell_background_task(
        ctx,
        task_id="task1234",
        message="Switch to Chinese voiceover",
    )

    assert result.ok is True
    assert result.data["task_id"] == "task1234"
    assert result.data["sequence"] == 3
    hub.tell.assert_called_once_with(
        "task1234",
        "Switch to Chinese voiceover",
        parent_agent="main",
    )


async def test_ask_parent_requires_task_context() -> None:
    hub = MagicMock()
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="main",
        task_hub=hub,
    )

    result = await ask_parent(ctx, question="Need more detail")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "task_context_required"
    hub.forward_question.assert_not_called()


def test_runtime_manager_exposes_task_context_tools_only_inside_tasks() -> None:
    wrapped: list[str] = []

    def fake_function_tool(func):
        wrapped.append(func.__name__)
        return func

    normal_ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="main",
        task_hub=MagicMock(),
    )
    task_ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="task:feedbeef",
        task_hub=MagicMock(),
    )

    AgentsRuntimeManager(normal_ctx).build_sdk_tools(fake_function_tool)
    assert "ask_parent" not in wrapped
    assert "check_parent_updates" not in wrapped
    assert "tell_background_task" in wrapped

    wrapped.clear()
    AgentsRuntimeManager(task_ctx).build_sdk_tools(fake_function_tool)
    assert "ask_parent" in wrapped
    assert "check_parent_updates" in wrapped
    assert "tell_background_task" in wrapped


async def test_ask_parent_forwards_question_from_task_context() -> None:
    hub = MagicMock()
    hub.forward_question = AsyncMock(return_value="Question forwarded to parent agent.")
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="task:feedbeef",
        task_hub=hub,
    )

    result = await ask_parent(ctx, question="Which branch should I use?")

    assert result.ok is True
    assert result.data["task_id"] == "feedbeef"
    hub.forward_question.assert_awaited_once_with("feedbeef", "Which branch should I use?")


async def test_check_parent_updates_reads_updates_from_task_context() -> None:
    hub = MagicMock()
    hub.pull_updates.return_value = [
        {"sequence": 1, "message": "Switch to Chinese"},
        {"sequence": 2, "message": "Only one final file"},
    ]
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=None,
        process_label="task:feedbeef",
        task_hub=hub,
    )

    result = await check_parent_updates(ctx)

    assert result.ok is True
    assert result.data["task_id"] == "feedbeef"
    assert result.data["count"] == 2
    hub.pull_updates.assert_called_once_with("feedbeef", mark_read=True)


async def test_send_async_to_agent_uses_interagent_bus() -> None:
    bus = MagicMock()
    bus.send_async.return_value = "async123"
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id=42,
        topic_id=9,
        process_label="main",
        interagent_bus=bus,
    )

    result = await send_async_to_agent(
        ctx,
        recipient="reviewer",
        message="Check the diff",
        summary="Review request",
        new_session=True,
    )

    assert result.ok is True
    assert result.data["task_id"] == "async123"
    bus.send_async.assert_called_once_with(
        "main",
        "reviewer",
        "Check the diff",
        opts=AsyncSendOptions(
            new_session=True,
            summary="Review request",
            chat_id=42,
            topic_id=9,
        ),
    )


async def test_string_native_refs_flow_through_runtime_tools() -> None:
    hub = MagicMock()
    hub.submit.return_value = "taskqq1"
    bus = MagicMock()
    bus.send_async.return_value = "asyncqq1"
    ctx = AgentsRuntimeContext(
        agent_name="main",
        chat_id="qqbot:c2c:OPENID",
        topic_id="qqbot:channel:THREAD",
        transport="qqbot",
        process_label="main",
        task_hub=hub,
        interagent_bus=bus,
    )

    task_result = await create_background_task(ctx, prompt="Inspect qqbot wiring")
    send_result = await send_async_to_agent(
        ctx,
        recipient="reviewer",
        message="Check qqbot diff",
        summary="QQ review",
    )

    assert task_result.ok is True
    assert send_result.ok is True
    submit = hub.submit.call_args.args[0]
    assert submit.chat_id == "qqbot:c2c:OPENID"
    assert submit.thread_id == "qqbot:channel:THREAD"
    bus.send_async.assert_called_once_with(
        "main",
        "reviewer",
        "Check qqbot diff",
        opts=AsyncSendOptions(
            new_session=False,
            summary="QQ review",
            chat_id="qqbot:c2c:OPENID",
            topic_id="qqbot:channel:THREAD",
        ),
    )
