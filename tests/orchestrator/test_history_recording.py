"""Focused tests for frontstage history recording in the orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from controlmesh.bus.bus import MessageBus
from controlmesh.bus.envelope import Envelope, Origin
from controlmesh.orchestrator.core import Orchestrator, _MessageDispatch
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.session import SessionKey


class _DummyProcessRegistry:
    def clear_abort(self, _chat_id: int) -> None:
        return None


@pytest.mark.asyncio
async def test_handle_message_impl_records_user_and_assistant_turns() -> None:
    turns: list[tuple[str, str]] = []

    async def record_user(_key: SessionKey, text: str) -> None:
        turns.append(("user", text))

    async def record_assistant(_key: SessionKey, result: OrchestratorResult) -> None:
        turns.append(("assistant", result.text))

    dummy = Mock()
    dummy._process_registry = _DummyProcessRegistry()
    dummy._route_message = AsyncMock(return_value=OrchestratorResult(text="pong"))
    dummy._record_frontstage_user_turn = record_user
    dummy._record_frontstage_assistant_turn = record_assistant

    dispatch = _MessageDispatch(key=SessionKey.telegram(1), text="ping", cmd="ping")
    result = await Orchestrator._handle_message_impl(dummy, dispatch)

    assert result.text == "pong"
    assert turns == [("user", "ping"), ("assistant", "pong")]


@pytest.mark.asyncio
async def test_handle_message_impl_skips_blank_assistant_turn() -> None:
    turns: list[tuple[str, str]] = []

    async def record_user(_key: SessionKey, text: str) -> None:
        turns.append(("user", text))

    async def record_assistant(_key: SessionKey, result: OrchestratorResult) -> None:
        if result.text.strip():
            turns.append(("assistant", result.text))

    dummy = Mock()
    dummy._process_registry = _DummyProcessRegistry()
    dummy._route_message = AsyncMock(return_value=OrchestratorResult(text=""))
    dummy._record_frontstage_user_turn = record_user
    dummy._record_frontstage_assistant_turn = record_assistant

    dispatch = _MessageDispatch(key=SessionKey.telegram(1), text="/stop", cmd="/stop")
    result = await Orchestrator._handle_message_impl(dummy, dispatch)

    assert result.text == ""
    assert turns == [("user", "/stop")]


@pytest.mark.asyncio
async def test_handle_message_impl_skips_history_command_recording() -> None:
    turns: list[tuple[str, str]] = []

    async def record_user(_key: SessionKey, text: str) -> None:
        turns.append(("user", text))

    async def record_assistant(_key: SessionKey, result: OrchestratorResult) -> None:
        turns.append(("assistant", result.text))

    dummy = Mock()
    dummy._process_registry = _DummyProcessRegistry()
    dummy._route_message = AsyncMock(return_value=OrchestratorResult(text="history output"))
    dummy._record_frontstage_user_turn = record_user
    dummy._record_frontstage_assistant_turn = record_assistant

    dispatch = _MessageDispatch(key=SessionKey.telegram(1), text="/history 5", cmd="/history 5")
    result = await Orchestrator._handle_message_impl(dummy, dispatch)

    assert result.text == "history output"
    assert turns == []


@pytest.mark.asyncio
async def test_handle_message_impl_skips_history_command_recording_with_bot_mention() -> None:
    turns: list[tuple[str, str]] = []

    async def record_user(_key: SessionKey, text: str) -> None:
        turns.append(("user", text))

    async def record_assistant(_key: SessionKey, result: OrchestratorResult) -> None:
        turns.append(("assistant", result.text))

    dummy = Mock()
    dummy._process_registry = _DummyProcessRegistry()
    dummy._route_message = AsyncMock(return_value=OrchestratorResult(text="history output"))
    dummy._record_frontstage_user_turn = record_user
    dummy._record_frontstage_assistant_turn = record_assistant

    dispatch = _MessageDispatch(
        key=SessionKey.telegram(1),
        text="/history@mybot 5",
        cmd="/history@mybot 5",
    )
    result = await Orchestrator._handle_message_impl(dummy, dispatch)

    assert result.text == "history output"
    assert turns == []


@pytest.mark.asyncio
async def test_record_frontstage_assistant_turn_extracts_file_attachments(
    orch: Orchestrator,
    tmp_path: object,
) -> None:
    report_path = tmp_path / "report.txt"  # type: ignore[operator]
    report_path.write_text("result artifact", encoding="utf-8")
    key = SessionKey.telegram(77, 5)

    await orch._record_frontstage_assistant_turn(
        key,
        OrchestratorResult(text=f"Report ready <file:{report_path}>"),
    )

    turns = orch._transcripts.read_recent(key, limit=10)
    assert len(turns) == 1
    assert turns[0].visible_content == "Report ready"
    assert [(a.kind, a.label, a.path) for a in turns[0].attachments] == [
        ("document", "report.txt", str(report_path)),
    ]


@pytest.mark.asyncio
async def test_record_frontstage_assistant_turn_tolerates_missing_attachment_path(
    orch: Orchestrator,
    tmp_path: object,
) -> None:
    missing_path = tmp_path / "missing.txt"  # type: ignore[operator]
    key = SessionKey.telegram(78, 6)

    await orch._record_frontstage_assistant_turn(
        key,
        OrchestratorResult(text=f"Missing artifact <file:{missing_path}>"),
    )

    turns = orch._transcripts.read_recent(key, limit=10)
    assert len(turns) == 1
    assert turns[0].visible_content == "Missing artifact"
    assert [a.label for a in turns[0].attachments] == ["missing.txt"]


@pytest.mark.asyncio
async def test_record_frontstage_delivery_records_injected_task_result(
    orch: Orchestrator,
    tmp_path: object,
) -> None:
    artifact_path = tmp_path / "task.md"  # type: ignore[operator]
    artifact_path.write_text("task artifact", encoding="utf-8")
    key = SessionKey.telegram(88, 11)
    envelope = Envelope(
        origin=Origin.TASK_RESULT,
        chat_id=key.chat_id,
        topic_id=key.topic_id,
        transport=key.transport,
        result_text=f"Task summary\n<file:{artifact_path}>",
        status="done",
    )

    await orch.record_frontstage_delivery(envelope)

    turns = orch._transcripts.read_recent(key, limit=10)
    assert len(turns) == 1
    assert turns[0].role == "assistant"
    assert turns[0].source == "foreground_task_result"
    assert turns[0].visible_content == "Task summary"
    assert [a.label for a in turns[0].attachments] == ["task.md"]


@pytest.mark.asyncio
async def test_record_frontstage_delivery_prefers_delivery_text_for_task_result(
    orch: Orchestrator,
) -> None:
    key = SessionKey.telegram(188, 21)
    envelope = Envelope(
        origin=Origin.TASK_RESULT,
        chat_id=key.chat_id,
        topic_id=key.topic_id,
        transport=key.transport,
        result_text="raw payload that should stay internal",
        delivery_text="checked frontstage summary",
        status="done",
    )

    await orch.record_frontstage_delivery(envelope)

    turns = orch._transcripts.read_recent(key, limit=10)
    assert len(turns) == 1
    assert turns[0].visible_content == "checked frontstage summary"


@pytest.mark.asyncio
async def test_record_frontstage_delivery_ignores_runtime_only_origins(
    orch: Orchestrator,
) -> None:
    key = SessionKey.telegram(99, 12)

    for origin in (Origin.HEARTBEAT, Origin.CRON, Origin.TASK_QUESTION):
        await orch.record_frontstage_delivery(
            Envelope(
                origin=origin,
                chat_id=key.chat_id,
                topic_id=key.topic_id,
                transport=key.transport,
                result_text=f"visible runtime note from {origin.value}",
                status="success",
            )
        )

    assert orch._transcripts.read_recent(key, limit=10) == []


@pytest.mark.asyncio
async def test_bus_pre_deliver_hook_records_visible_task_delivery(
    orch: Orchestrator,
) -> None:
    key = SessionKey.telegram(111, 13)
    bus = MessageBus()
    orch.wire_observers_to_bus(bus)

    await bus.submit(
        Envelope(
            origin=Origin.TASK_RESULT,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
            transport=key.transport,
            result_text="Injected task response",
            status="done",
        )
    )

    turns = orch._transcripts.read_recent(key, limit=10)
    assert [(turn.role, turn.source, turn.visible_content) for turn in turns] == [
        ("assistant", "foreground_task_result", "Injected task response"),
    ]
