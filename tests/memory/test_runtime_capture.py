"""Runtime capture integration tests for memory daily notes."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from controlmesh.history import TranscriptStore, TranscriptTurn
from controlmesh.memory import runtime_capture
from controlmesh.memory.runtime_capture import event_from_transcript_turn
from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.models import TeamEvent
from controlmesh.team.state import TeamStateStore
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )


def _make_config(**overrides: object) -> MagicMock:
    config = MagicMock()
    config.enabled = True
    config.max_parallel = 5
    config.timeout_seconds = 60.0
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_cli_service(
    result: str = "done",
    *,
    session_id: str = "sess-1",
    num_turns: int = 3,
) -> MagicMock:
    cli = MagicMock()
    response = MagicMock()
    response.result = result
    response.session_id = session_id
    response.is_error = False
    response.timed_out = False
    response.num_turns = num_turns
    cli.execute = AsyncMock(return_value=response)
    cli.resolve_provider = MagicMock(return_value=("claude", "opus"))
    return cli


def _submit(*, name: str) -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="capture this runtime event",
        message_id=1,
        thread_id=9,
        parent_agent="main",
        name=name,
    )


def _current_note(paths: ControlMeshPaths) -> Path:
    return paths.memory_v2_daily_dir / f"{datetime.now(UTC).date().isoformat()}.md"


def test_transcript_turn_append_writes_daily_note_and_stays_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TranscriptStore(paths)
    turn = TranscriptTurn(
        turn_id="feedfacefeedfacefeedfacefeedface",
        session_key="tg:42:9",
        surface_session_id="tg:42:9",
        role="user",
        visible_content="Can you summarize the build status?",
        created_at="2026-04-25T10:30:00+00:00",
        source="normal_chat",
        transport="tg",
        chat_id=42,
        topic_id=9,
    )

    store.append_turn(turn)
    store.append_turn(turn)

    note_path = paths.memory_v2_daily_dir / "2026-04-25.md"
    content = note_path.read_text(encoding="utf-8")
    assert "[chat-turn]" in content
    assert "user turn: Can you summarize the build status?" in content
    assert content.count(f"[evt:{event_from_transcript_turn(turn).id}]") == 1


async def test_task_question_writes_daily_note(tmp_path: Path) -> None:
    async def _hang(_: object) -> MagicMock:
        await asyncio.sleep(999)
        return MagicMock()

    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    cli = _make_cli_service()
    cli.execute = AsyncMock(side_effect=_hang)

    hub = TaskHub(
        registry,
        paths,
        cli_service=cli,
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())
    hub.set_question_handler("main", AsyncMock())

    task_id = hub.submit(_submit(name="Waiting Task"))
    await asyncio.sleep(0.05)
    await hub.forward_question(task_id, "Need a parent preference for deployment region?")

    content = _current_note(paths).read_text(encoding="utf-8")
    assert "[ask-parent]" in content
    assert "Waiting Task" in content
    assert "Need a parent preference for deployment region?" in content

    assert await hub.cancel(task_id)
    await hub.shutdown()


async def test_task_resume_follow_up_writes_daily_note(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("initial task output"),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    task_id = hub.submit(_submit(name="Resume Task"))
    await asyncio.sleep(0.1)
    hub.resume(task_id, "Use the approved blue rollout plan.")
    await asyncio.sleep(0.1)

    content = _current_note(paths).read_text(encoding="utf-8")
    assert "[resume]" in content
    assert "Resume Task" in content
    assert "Use the approved blue rollout plan." in content

    await hub.shutdown()


async def test_task_resume_after_question_retains_parent_question_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured_parent_questions: list[str | None] = []
    original_event_from_task_resume = runtime_capture.event_from_task_resume

    def _capture_resume_event(*args, **kwargs):
        event = original_event_from_task_resume(*args, **kwargs)
        captured_parent_questions.append(event.parent_question)
        return event

    async def _delayed_response(_: object) -> MagicMock:
        await asyncio.sleep(0.05)
        response = MagicMock()
        response.result = "Task paused after asking a question."
        response.session_id = "sess-waiting"
        response.is_error = False
        response.timed_out = False
        response.num_turns = 2
        return response

    monkeypatch.setattr(runtime_capture, "event_from_task_resume", _capture_resume_event)

    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    cli = _make_cli_service("unused")
    cli.execute = AsyncMock(side_effect=_delayed_response)

    hub = TaskHub(
        registry,
        paths,
        cli_service=cli,
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())
    hub.set_question_handler("main", AsyncMock())

    task_id = hub.submit(_submit(name="Resume Context Task"))
    await asyncio.sleep(0.01)
    question = "Should I use the EU or US deployment target?"
    await hub.forward_question(task_id, question)
    await asyncio.sleep(0.1)

    entry = registry.get(task_id)
    assert entry is not None
    assert entry.status == "waiting"
    assert entry.last_question == question

    hub.resume(task_id, "Use the EU deployment target.")
    await asyncio.sleep(0.1)

    assert captured_parent_questions[-1] == question
    content = _current_note(paths).read_text(encoding="utf-8")
    assert "[resume]" in content
    assert "Resume Context Task" in content
    assert "Use the EU deployment target." in content

    await hub.shutdown()


async def test_task_terminal_result_writes_daily_note(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("Task finished with a concise result."),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    hub.submit(_submit(name="Result Task"))
    await asyncio.sleep(0.1)

    content = _current_note(paths).read_text(encoding="utf-8")
    assert "[task-result]" in content
    assert "Result Task done" in content
    assert "Task finished with a concise result." in content

    await hub.shutdown()


def test_team_event_append_writes_daily_note(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")

    store.append_event(
        TeamEvent(
            event_id="evt-team-001",
            team_name="alpha-team",
            event_type="task_status_changed",
            created_at="2026-04-25T13:00:00+00:00",
            phase="plan",
            worker="worker-1",
            task_id="task-7",
            payload={"kind": "research"},
        )
    )

    content = (paths.memory_v2_daily_dir / f"{date(2026, 4, 25).isoformat()}.md").read_text(
        encoding="utf-8"
    )
    assert "[team-event]" in content
    assert "Team alpha-team task_status_changed" in content
    assert "team=alpha-team" in content
