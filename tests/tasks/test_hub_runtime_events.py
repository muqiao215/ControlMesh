"""Red contract for TaskHub lifecycle writes into the runtime event substrate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from controlmesh.history import TranscriptStore
from controlmesh.runtime import AgentInboxStore, RuntimeEventStore
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
        for event in store.read_recent(key, limit=30)
    ]


def _inbox_summaries(paths: ControlMeshPaths, agent_name: str = "main") -> list[str]:
    store = AgentInboxStore(paths)
    return [item.summary for item in store.read_recent(agent_name, limit=20)]


def _assert_subsequence(
    actual: list[tuple[str, str | None, str | None]],
    expected: list[tuple[str, str | None, str | None]],
) -> None:
    cursor = 0
    for item in actual:
        if cursor < len(expected) and item == expected[cursor]:
            cursor += 1
    assert cursor == len(expected), f"expected ordered subsequence missing: {expected!r} from {actual!r}"


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

    lifecycle = _lifecycle_shape(paths, key)
    _assert_subsequence(
        lifecycle,
        [
            ("task.lifecycle.created", None, task_id),
            ("task.lifecycle.started", None, task_id),
            ("task.lifecycle.terminal", "done", task_id),
        ],
    )
    assert ("task.lifecycle.tool_result_created", "tool_result_created", task_id) in lifecycle
    assert ("task.lifecycle.inbox_enqueued", "inbox_enqueued", task_id) in lifecycle
    assert ("task.lifecycle.delivered_to_parent", "delivered_to_parent", task_id) in lifecycle
    inbox = _inbox_summaries(paths)
    assert any("Task id:" in item for item in inbox)
    assert transcript_store.read_recent(key, limit=10) == []
    assert not transcript_store.path_for(key).exists()

    await hub.shutdown()


async def test_taskhub_writes_tool_use_and_tool_result_artifacts_and_consumes_once(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("task output"),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())

    submit = _submit()
    submit.tool_use_id = "toolu_bg_task_1"
    submit.repo_root = "/root/.controlmesh/dev/ControlMesh"
    task_id = hub.submit(submit)
    await asyncio.sleep(0.1)

    entry = registry.get(task_id)
    assert entry is not None
    task_dir = registry.task_folder(task_id)
    tool_use = json.loads((task_dir / "TOOL_USE.json").read_text(encoding="utf-8"))
    assert tool_use["tool_use_id"] == "toolu_bg_task_1"
    assert tool_use["task_id"] == task_id

    tool_result_path = task_dir / "TOOL_RESULT.json"
    tool_result = json.loads(tool_result_path.read_text(encoding="utf-8"))
    assert tool_result["role"] == "user"
    assert tool_result["consumed"] is False
    block = tool_result["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "toolu_bg_task_1"

    inbox = AgentInboxStore(paths).read_recent("main", limit=5)
    assert inbox
    assert inbox[0].status in {"pending", "delivered_to_parent"}
    assert inbox[0].payload["tool_result_path"] == str(tool_result_path)
    assert inbox[0].payload["tool_use_id"] == "toolu_bg_task_1"
    assert inbox[0].payload["repo_root"] == "/root/.controlmesh/dev/ControlMesh"

    unread = hub.consume_tool_results("main", limit=5)
    assert len(unread) == 1
    assert unread[0]["content"][0]["tool_use_id"] == "toolu_bg_task_1"
    payload = json.loads(unread[0]["content"][0]["content"][0]["text"])
    assert f"artifact://tasks/{task_id}/TOOL_RESULT.json" in payload["artifact_refs"]
    assert payload["evaluation"] is None

    persisted = json.loads(tool_result_path.read_text(encoding="utf-8"))
    assert persisted["consumed"] is True
    entry = registry.get(task_id)
    assert entry is not None
    assert entry.tool_result_created_at > 0
    assert entry.tool_result_enqueued_at > 0
    assert entry.tool_result_delivered_at > 0
    assert entry.tool_result_consumed_at > 0
    lifecycle = _lifecycle_shape(paths, SessionKey.telegram(submit.chat_id, submit.thread_id))
    assert ("task.lifecycle.consumed_by_parent", "consumed_by_parent", task_id) in lifecycle
    consumed_inbox = AgentInboxStore(paths).read_recent("main", limit=5)
    assert consumed_inbox[0].status == "consumed"
    assert consumed_inbox[0].consumed_at is not None
    assert hub.consume_tool_results("main", limit=5) == []

    await hub.shutdown()


async def test_record_route_candidate_persists_worker_permission_posture(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    hub = TaskHub(
        registry,
        paths,
        cli_service=_make_cli_service("task output"),
        config=_make_config(),
    )

    entry = registry.create(_submit(name="Route Candidate"), "claude", "opus")
    entry.status = "candidate"
    entry.route = "auto"
    entry.workunit_kind = "code_review"
    entry.route_slot = "claude_code.codex_plugin_review"
    entry.route_reason = "policy=review_background; selected topology=fanout_merge"
    entry.route_candidate_summary = "candidate summary"
    entry.worker_runtime_writeback = True
    entry.worker_business_permissions = ["repo_write"]
    registry.update_status(
        entry.task_id,
        "candidate",
        route=entry.route,
        workunit_kind=entry.workunit_kind,
        route_slot=entry.route_slot,
        route_reason=entry.route_reason,
        route_candidate_summary=entry.route_candidate_summary,
        worker_runtime_writeback=entry.worker_runtime_writeback,
        worker_business_permissions=entry.worker_business_permissions,
    )

    hub.record_route_candidate(entry)
    inbox_items = AgentInboxStore(paths).read_recent("main", limit=5)
    assert inbox_items
    assert inbox_items[0].payload["worker_runtime_writeback"] is True
    assert inbox_items[0].payload["worker_business_permissions"] == ["repo_write"]
    assert inbox_items[0].payload["plan_id"] == ""
    assert inbox_items[0].payload["chat_id"] == entry.chat_id
    assert inbox_items[0].payload["topic_id"] == entry.thread_id

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

    lifecycle = _lifecycle_shape(paths, key)
    _assert_subsequence(
        lifecycle,
        [
            ("task.lifecycle.created", None, task_id),
            ("task.lifecycle.started", None, task_id),
            ("task.lifecycle.terminal", "cancelled", task_id),
        ],
    )
    assert ("task.lifecycle.tool_result_created", "tool_result_created", task_id) in lifecycle
    assert ("task.lifecycle.inbox_enqueued", "inbox_enqueued", task_id) in lifecycle
    assert ("task.lifecycle.delivered_to_parent", "delivered_to_parent", task_id) in lifecycle
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

    _assert_subsequence(
        _lifecycle_shape(paths, key),
        [
            ("task.lifecycle.created", None, task_id),
            ("task.lifecycle.started", None, task_id),
            ("task.lifecycle.terminal", "done", task_id),
            ("task.lifecycle.resumed", None, task_id),
            ("task.lifecycle.started", None, task_id),
            ("task.lifecycle.terminal", "done", task_id),
        ],
    )

    await hub.shutdown()
