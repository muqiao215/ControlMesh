"""Tests for the derived transcript/runtime history index."""

from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path

from controlmesh.history import TranscriptStore, TranscriptTurn
from controlmesh.history.index import HistoryIndex
from controlmesh.runtime import RuntimeEvent, RuntimeEventStore
from controlmesh.session import SessionKey
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.models import (
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamSessionRef,
    TeamTask,
    TeamWorker,
)
from controlmesh.team.state import TeamStateStore
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def test_history_index_sync_handles_empty_source_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    transcript_path = TranscriptStore(paths).path_for(SessionKey.telegram(123))
    runtime_path = RuntimeEventStore(paths).path_for(SessionKey.telegram(456))
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("", encoding="utf-8")
    runtime_path.write_text("", encoding="utf-8")

    index = HistoryIndex(paths)
    result = index.sync()

    assert result.indexed_sources == 2
    assert result.inserted_sources == 2
    assert result.deleted_sources == 0
    assert index.list_transcript_turns() == []
    assert index.list_runtime_events() == []
    assert [(source.source_kind, source.row_count) for source in index.list_sources()] == [
        ("runtime", 0),
        ("transcript", 0),
    ]


def test_history_index_sync_indexes_transcript_rows_from_jsonl(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123, 9)
    store = TranscriptStore(paths)
    store.append_turn(
        TranscriptTurn(
            turn_id="turn-1",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content="hello",
            source="normal_chat",
            created_at="2026-04-10T12:00:00+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    store.append_turn(
        TranscriptTurn(
            turn_id="turn-2",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="world",
            source="normal_chat",
            created_at="2026-04-10T12:00:01+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    index = HistoryIndex(paths)
    result = index.sync()
    turns = index.list_transcript_turns()

    assert result.transcript_rows == 2
    assert result.runtime_rows == 0
    assert [turn.turn_id for turn in turns] == ["turn-1", "turn-2"]
    assert [turn.visible_content for turn in turns] == ["hello", "world"]
    assert {turn.source_kind for turn in turns} == {"transcript"}
    assert index.list_runtime_events() == []


def test_history_index_sync_indexes_runtime_rows_from_jsonl(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123, 9)
    store = RuntimeEventStore(paths)
    store.append_event(
        RuntimeEvent(
            event_id="event-1",
            session_key=key.storage_key,
            event_type="worker.started",
            payload={"lease_id": "lease-1"},
            created_at="2026-04-10T12:01:00+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    index = HistoryIndex(paths)
    result = index.sync()
    events = index.list_runtime_events()

    assert result.transcript_rows == 0
    assert result.runtime_rows == 1
    assert [event.event_id for event in events] == ["event-1"]
    assert [event.event_type for event in events] == ["worker.started"]
    assert events[0].payload_json == '{"lease_id":"lease-1"}'
    assert {event.source_kind for event in events} == {"runtime"}
    assert index.list_transcript_turns() == []


def test_history_index_sync_indexes_task_registry_rows(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    entry = registry.create(
        TaskSubmit(
            chat_id=42,
            prompt="investigate failure",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Investigate",
        ),
        "codex",
        "gpt-5.2",
    )
    registry.update_status(
        entry.task_id,
        "done",
        session_id="ia-main",
        result_preview="fixed",
        last_question="where are the logs?",
    )

    index = HistoryIndex(paths)
    result = index.sync()
    rows = index.list_task_catalog_rows()

    assert result.task_rows == 1
    assert result.team_entity_rows == 0
    assert [row.task_id for row in rows] == [entry.task_id]
    assert rows[0].status == "done"
    assert rows[0].source_kind == "task_registry"
    assert rows[0].chat_id == 42
    assert rows[0].session_id == "ia-main"
    assert rows[0].result_preview == "fixed"
    assert rows[0].last_question == "where are the logs?"
    assert index.list_team_entities() == []


def test_history_index_sync_indexes_team_state_rows(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
            ),
            workers=[TeamWorker(name="worker-1", role="executor", provider="codex")],
        )
    )
    store.upsert_task(
        TeamTask(task_id="team-task-1", subject="Implement feature", owner="worker-1")
    )
    store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-1",
            subject="Need review",
            body="Please review the patch",
        )
    )
    store.write_phase(TeamPhaseState(current_phase="execute"))

    index = HistoryIndex(paths)
    result = index.sync()
    rows = index.list_team_entities()

    assert result.task_rows == 0
    assert result.team_entity_rows == 4
    assert {(row.entity_kind, row.entity_id) for row in rows} == {
        ("mailbox_message", "msg-1"),
        ("manifest", "alpha-team"),
        ("phase", "alpha-team"),
        ("task", "team-task-1"),
    }
    assert {row.source_kind for row in rows} == {"team_state"}
    assert {row.team_name for row in rows} == {"alpha-team"}
    task_row = next(row for row in rows if row.entity_kind == "task")
    assert task_row.status == "pending"
    assert task_row.owner == "worker-1"
    assert index.list_task_catalog_rows() == []


def test_history_index_rebuild_matches_source_snapshot(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123)
    TranscriptStore(paths).append_turn(
        TranscriptTurn(
            turn_id="turn-1",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="hello",
            source="normal_chat",
            created_at="2026-04-10T12:02:00+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    RuntimeEventStore(paths).append_event(
        RuntimeEvent(
            event_id="event-1",
            session_key=key.storage_key,
            event_type="worker.finished",
            payload={"status": "ok"},
            created_at="2026-04-10T12:02:01+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    task_registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    task_entry = task_registry.create(
        TaskSubmit(
            chat_id=99,
            prompt="summarize findings",
            message_id=2,
            thread_id=None,
            parent_agent="main",
            name="Summary",
        ),
        "claude",
        "opus",
    )
    task_registry.update_status(task_entry.task_id, "waiting", question_count=1)
    team_store = TeamStateStore(paths.team_state_dir, "alpha-team")
    team_store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
            ),
        )
    )
    team_store.upsert_task(TeamTask(task_id="team-task-1", subject="Implement feature"))

    index = HistoryIndex(paths)
    index.sync()
    snapshot_before = index.snapshot()

    rebuild_result = index.rebuild()
    snapshot_after = index.snapshot()

    assert rebuild_result.indexed_sources == 5
    assert snapshot_after == snapshot_before


def test_history_index_sync_cleans_stale_rows_for_replaced_deleted_task_and_team_sources(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    transcript_store = TranscriptStore(paths)
    runtime_store = RuntimeEventStore(paths)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    team_store = TeamStateStore(paths.team_state_dir, "alpha-team")
    key = SessionKey.telegram(123)

    transcript_store.append_turn(
        TranscriptTurn(
            turn_id="turn-old",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="old text",
            source="normal_chat",
            created_at="2026-04-10T12:03:00+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    runtime_store.append_event(
        RuntimeEvent(
            event_id="event-old",
            session_key=key.storage_key,
            event_type="worker.started",
            payload={"attempt": 1},
            created_at="2026-04-10T12:03:01+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    task_entry = registry.create(
        TaskSubmit(
            chat_id=42,
            prompt="old task prompt",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Old",
        ),
        "codex",
        "gpt-5.2",
    )
    registry.update_status(task_entry.task_id, "done", result_preview="old result")
    team_store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
            ),
        )
    )
    team_store.upsert_task(TeamTask(task_id="team-task-1", subject="Implement feature"))
    team_store.write_phase(TeamPhaseState(current_phase="execute"))

    index = HistoryIndex(paths)
    first_result = index.sync()
    assert first_result.transcript_rows == 1
    assert first_result.runtime_rows == 1
    assert first_result.task_rows == 1
    assert first_result.team_entity_rows == 3

    transcript_path = transcript_store.path_for(key)
    transcript_path.write_text(
        TranscriptTurn(
            turn_id="turn-new",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="new text",
            source="normal_chat",
            created_at="2026-04-10T12:03:02+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    runtime_store.path_for(key).unlink()
    paths.tasks_registry_path.write_text(
        '{"tasks":[{"task_id":"task-new","chat_id":42,"parent_agent":"main","name":"New","prompt_preview":"new","provider":"codex","model":"gpt-5.2","status":"waiting","session_id":"","created_at":1.0,"completed_at":0.0,"elapsed_seconds":0.0,"error":"","result_preview":"","question_count":0,"num_turns":0,"last_question":"what next?","thinking":"","tasks_dir":""}]}',
        encoding="utf-8",
    )
    (paths.team_state_dir / "alpha-team" / "phase.json").unlink()

    result = index.sync()

    assert result.deleted_sources == 2
    assert [turn.turn_id for turn in index.list_transcript_turns()] == ["turn-new"]
    assert [turn.visible_content for turn in index.list_transcript_turns()] == ["new text"]
    assert index.list_runtime_events() == []
    assert [row.task_id for row in index.list_task_catalog_rows()] == ["task-new"]
    assert [row.last_question for row in index.list_task_catalog_rows()] == ["what next?"]
    assert {(row.entity_kind, row.entity_id) for row in index.list_team_entities()} == {
        ("manifest", "alpha-team"),
        ("task", "team-task-1"),
    }
    assert {source.source_kind for source in index.list_sources()} == {
        "task_registry",
        "team_state",
        "transcript",
    }


def test_history_index_keeps_catalog_kinds_logically_separate(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(55)
    TranscriptStore(paths).append_turn(
        TranscriptTurn(
            turn_id="turn-1",
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="visible",
            source="normal_chat",
            created_at="2026-04-10T12:04:00+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    RuntimeEventStore(paths).append_event(
        RuntimeEvent(
            event_id="event-1",
            session_key=key.storage_key,
            event_type="worker.started",
            payload={"ok": True},
            created_at="2026-04-10T12:04:01+00:00",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    registry.create(
        TaskSubmit(
            chat_id=55,
            prompt="prompt",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Task",
        ),
        "codex",
        "gpt-5.2",
    )
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
            ),
        )
    )

    index = HistoryIndex(paths)
    index.sync()

    assert len(index.list_transcript_turns()) == 1
    assert len(index.list_runtime_events()) == 1
    assert len(index.list_task_catalog_rows()) == 1
    assert len(index.list_team_entities()) == 1
    assert {source.source_kind for source in index.list_sources()} == {
        "runtime",
        "task_registry",
        "team_state",
        "transcript",
    }


def test_history_index_sync_serializes_concurrent_sync_calls(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    index = HistoryIndex(paths)
    entered = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    call_count = 0
    counter_lock = threading.Lock()

    def fake_sync(*, force_reindex: bool):
        nonlocal active, max_active, call_count
        assert force_reindex is False
        with counter_lock:
            call_count += 1
            active += 1
            max_active = max(max_active, active)
            if call_count == 1:
                entered.set()
        if call_count == 1:
            assert release.wait(timeout=1.0)
        else:
            time.sleep(0.01)
        with counter_lock:
            active -= 1
        return "ok"

    monkeypatch.setattr(index, "_sync", fake_sync)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(index.sync)
        assert entered.wait(timeout=1.0)
        second = executor.submit(index.sync)
        time.sleep(0.05)
        release.set()

    assert first.result() == "ok"
    assert second.result() == "ok"
    assert max_active == 1
