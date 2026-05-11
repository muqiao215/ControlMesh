"""Red-contract tests for a dedicated runtime event substrate."""

from __future__ import annotations

from pathlib import Path

from controlmesh.history import TranscriptStore
from controlmesh.runtime import AgentInboxItem, AgentInboxStore, RuntimeEvent, RuntimeEventStore
from controlmesh.session import SessionKey
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def test_runtime_event_model_is_distinct_from_transcript_turn_shape() -> None:
    runtime_fields = set(RuntimeEvent.model_fields)
    assert "visible_content" not in runtime_fields
    assert {"event_type", "payload", "session_key", "transport", "chat_id"} <= runtime_fields


def test_runtime_event_store_path_for_session_uses_dedicated_runtime_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123, 9)
    runtime_store = RuntimeEventStore(paths)
    transcript_store = TranscriptStore(paths)

    assert runtime_store.path_for(key) == (
        tmp_path / ".controlmesh" / "runtime-events" / "tg" / "123" / "9.jsonl"
    )
    assert runtime_store.path_for(key) != transcript_store.path_for(key)


def test_runtime_event_store_append_and_read_recent_stay_out_of_transcripts(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123, 9)
    runtime_store = RuntimeEventStore(paths)
    transcript_store = TranscriptStore(paths)

    runtime_store.append_event(
        RuntimeEvent(
            session_key=key.storage_key,
            event_type="worker.started",
            payload={"lease_id": "lease-1"},
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    events = runtime_store.read_recent(key, limit=10)
    assert [event.event_type for event in events] == ["worker.started"]
    assert transcript_store.read_recent(key, limit=10) == []
    assert not transcript_store.path_for(key).exists()


def test_runtime_event_accepts_string_native_refs() -> None:
    event = RuntimeEvent(
        session_key="v2:qqbot:s:qqbot%3Ac2c%3AOPENID",
        event_type="task.lifecycle.created",
        payload={"task_id": "qq1"},
        transport="qqbot",
        chat_id="qqbot:c2c:OPENID",
        topic_id="qqbot:channel:THREAD",
    )

    assert event.chat_id == "qqbot:c2c:OPENID"
    assert event.topic_id == "qqbot:channel:THREAD"


def test_agent_inbox_store_uses_dedicated_runtime_root(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    inbox = AgentInboxStore(paths)
    assert inbox.path_for("main") == tmp_path / ".controlmesh" / "agent-inbox" / "main.jsonl"
    assert inbox.agent_dir("main") == tmp_path / ".controlmesh" / "agent-inbox" / "main"
    assert inbox.status_dir("main", "pending") == tmp_path / ".controlmesh" / "agent-inbox" / "main" / "pending"


def test_agent_inbox_store_append_and_read_recent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    inbox = AgentInboxStore(paths)
    inbox.append(
        AgentInboxItem(
            to_agent="main",
            kind="task.final",
            summary="Background review completed",
            from_task="abc123",
            result_ref="task:abc123/result",
        )
    )
    items = inbox.read_recent("main", limit=10)
    assert len(items) == 1
    assert items[0].to_agent == "main"
    assert items[0].summary == "Background review completed"
    assert items[0].status == "pending"


def test_agent_inbox_store_mark_delivered_and_consumed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    inbox = AgentInboxStore(paths)
    inbox.append(
        AgentInboxItem(
            to_agent="main",
            kind="task.done",
            summary="Completed",
            task_id="t1",
            tool_use_id="toolu_t1",
            tool_result_ref="task://t1/TOOL_RESULT.json",
        )
    )

    delivered = inbox.mark_delivered("main", tool_use_id="toolu_t1")
    assert delivered is not None
    assert delivered.status == "delivered_to_parent"
    assert delivered.delivered_at is not None

    consumed = inbox.mark_consumed(
        "main",
        tool_use_id="toolu_t1",
        consumed_by="main",
        next_action="responded_to_user",
    )
    assert consumed is not None
    assert consumed.status == "consumed"
    assert consumed.consumed_at is not None
    assert consumed.next_action == "responded_to_user"
