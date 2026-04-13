"""Red-contract tests for a dedicated runtime event substrate."""

from __future__ import annotations

from pathlib import Path

from ductor_bot.history import TranscriptStore
from ductor_bot.runtime import RuntimeEvent, RuntimeEventStore
from ductor_bot.session import SessionKey
from ductor_bot.workspace.paths import DuctorPaths


def _paths(tmp_path: Path) -> DuctorPaths:
    return DuctorPaths(
        ductor_home=tmp_path / ".ductor",
        home_defaults=Path("/opt/ductor/workspace"),
        framework_root=Path("/opt/ductor"),
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
        tmp_path / ".ductor" / "runtime-events" / "tg" / "123" / "9.jsonl"
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
