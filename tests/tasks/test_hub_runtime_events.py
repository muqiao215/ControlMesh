"""Red contract for TaskHub lifecycle writes into the runtime event substrate."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from controlmesh.history import TranscriptStore
from controlmesh.runtime import RuntimeEventStore
from controlmesh.session import SessionKey
from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
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
    result: str = "done", session_id: str = "sess-1", num_turns: int = 3
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


def _submit(*, thread_id: int = 9, name: str = "Runtime Event Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="verify runtime lifecycle contract",
        message_id=1,
        thread_id=thread_id,
        parent_agent="main",
        name=name,
    )


def _lifecycle_shape(paths: ControlMeshPaths, key: SessionKey) -> list[tuple[str, str | None, str | None]]:
    store = RuntimeEventStore(paths)
    return [
        (event.event_type, event.payload.get("status"), event.payload.get("task_id"))
        for event in store.read_recent(key, limit=10)
    ]


async def test_taskhub_success_lifecycle_writes_land_in_runtime_events_not_transcripts(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    submit = _submit()
    key = SessionKey.telegram(submit.chat_id, submit.thread_id)
    transcript_store = TranscriptStore(paths)

    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("task output"),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    task_id = hub.submit(submit)
    await asyncio.sleep(0.1)

    assert _lifecycle_shape(paths, key) == [
        ("task.lifecycle.created", None, task_id),
        ("task.lifecycle.started", None, task_id),
        ("task.lifecycle.terminal", "done", task_id),
    ]
    assert transcript_store.read_recent(key, limit=10) == []
    assert not transcript_store.path_for(key).exists()

    await hub.shutdown()


async def test_taskhub_cancelled_lifecycle_writes_land_in_runtime_events_not_transcripts(
    tmp_path: Path,
) -> None:
    async def _hang(_: object) -> MagicMock:
        await asyncio.sleep(999)
        return MagicMock()

    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    submit = _submit(thread_id=17, name="Cancelled Runtime Event Task")
    key = SessionKey.telegram(submit.chat_id, submit.thread_id)
    transcript_store = TranscriptStore(paths)

    cli = _make_cli_service()
    cli.execute = AsyncMock(side_effect=_hang)

    hub = TaskHub(
        registry,
        paths,
        cli_service=cli,
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    task_id = hub.submit(submit)
    await asyncio.sleep(0.05)
    assert await hub.cancel(task_id)
    await asyncio.sleep(0.05)

    assert _lifecycle_shape(paths, key) == [
        ("task.lifecycle.created", None, task_id),
        ("task.lifecycle.started", None, task_id),
        ("task.lifecycle.terminal", "cancelled", task_id),
    ]
    assert transcript_store.read_recent(key, limit=10) == []
    assert not transcript_store.path_for(key).exists()


async def test_taskhub_waiting_lifecycle_writes_question_pause_not_transcripts(
    tmp_path: Path,
) -> None:
    async def _hang(_: object) -> MagicMock:
        await asyncio.sleep(999)
        return MagicMock()

    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    submit = _submit(thread_id=21, name="Waiting Runtime Event Task")
    key = SessionKey.telegram(submit.chat_id, submit.thread_id)
    transcript_store = TranscriptStore(paths)

    cli = _make_cli_service("task output")
    cli.execute = AsyncMock(side_effect=_hang)
    hub = TaskHub(
        registry,
        paths,
        cli_service=cli,
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())
    hub.set_question_handler("main", AsyncMock())

    task_id = hub.submit(submit)
    await asyncio.sleep(0.05)
    await hub.forward_question(task_id, "Need a preference?")
    await asyncio.sleep(0.05)

    assert _lifecycle_shape(paths, key) == [
        ("task.lifecycle.created", None, task_id),
        ("task.lifecycle.started", None, task_id),
        ("task.lifecycle.waiting", "waiting", task_id),
    ]
    assert transcript_store.read_recent(key, limit=10) == []
    assert not transcript_store.path_for(key).exists()

    assert await hub.cancel(task_id)
    await hub.shutdown()


async def test_taskhub_resume_writes_resumed_event_before_next_run(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    submit = _submit(thread_id=25, name="Resumed Runtime Event Task")
    key = SessionKey.telegram(submit.chat_id, submit.thread_id)

    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("task output"),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    task_id = hub.submit(submit)
    await asyncio.sleep(0.1)
    resumed_id = hub.resume(task_id, "Continue with the approved option")
    assert resumed_id == task_id
    await asyncio.sleep(0.1)

    assert _lifecycle_shape(paths, key) == [
        ("task.lifecycle.created", None, task_id),
        ("task.lifecycle.started", None, task_id),
        ("task.lifecycle.terminal", "done", task_id),
        ("task.lifecycle.resumed", None, task_id),
        ("task.lifecycle.started", None, task_id),
        ("task.lifecycle.terminal", "done", task_id),
    ]

    await hub.shutdown()
