from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from controlmesh.cli.types import AgentResponse
from controlmesh.session.named import NamedSession, NamedSessionRegistry
from controlmesh.team.models import (
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamWorker,
    TeamWorkerRuntimeState,
)
from controlmesh.team.state import TeamStateStore
from controlmesh_runtime import (
    ControlMeshWorkerController,
    FailureClass,
    WorkerControllerError,
    WorkerControllerErrorCode,
    WorkerStatus,
)


def _seed_store(tmp_path: Path) -> tuple[Path, TeamStateStore]:
    state_root = tmp_path / "team-state"
    store = TeamStateStore(state_root, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Drive one worker runtime",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7, topic_id=12),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(
                    name="worker-1",
                    role="executor",
                    provider="codex",
                    runtime=TeamRuntimeContext(
                        session_name="ia-worker-1",
                        routable_session=TeamSessionRef(transport="tg", chat_id=21, topic_id=4),
                    ),
                )
            ],
        )
    )
    return state_root, store


def _make_orchestrator(path: Path) -> SimpleNamespace:
    registry = NamedSessionRegistry(path)
    orchestrator = SimpleNamespace()
    orchestrator.named_sessions = registry
    orchestrator.cli_service = SimpleNamespace(execute=AsyncMock())
    orchestrator.config = SimpleNamespace(provider="claude", model="sonnet")
    orchestrator.default_model_for_provider = lambda provider: {
        "codex": "gpt-5",
        "claude": "sonnet",
    }.get(provider, "gpt-5")

    async def _end_named_session(chat_id: int, name: str) -> bool:
        return registry.end_session(chat_id, name)

    orchestrator.end_named_session = AsyncMock(side_effect=_end_named_session)
    return orchestrator


def _seed_named_session(
    path: Path,
    *,
    name: str,
    chat_id: int,
    session_id: str,
    status: str = "idle",
) -> None:
    registry = NamedSessionRegistry(path)
    registry.add(
        NamedSession(
            name=name,
            chat_id=chat_id,
            provider="codex",
            model="gpt-5",
            session_id=session_id,
            prompt_preview="bootstrap",
            status=status,
            created_at=1.0,
            transport="tg",
        )
    )


def _ready_runtime(*, session_id: str) -> TeamWorkerRuntimeState:
    now = datetime.now(UTC)
    return TeamWorkerRuntimeState(
        worker="worker-1",
        status="ready",
        lease_id="lease-1",
        lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
        heartbeat_at=now.isoformat(),
        attachment_type="named_session",
        attachment_name="ia-worker-1",
        attachment_transport="tg",
        attachment_chat_id=21,
        attachment_session_id=session_id,
        attached_at=(now - timedelta(seconds=5)).isoformat(),
        started_at=(now - timedelta(seconds=5)).isoformat(),
    )


def _busy_runtime(*, session_id: str) -> TeamWorkerRuntimeState:
    now = datetime.now(UTC)
    return TeamWorkerRuntimeState(
        worker="worker-1",
        status="busy",
        execution_id="exec-1",
        dispatch_request_id="dispatch-1",
        lease_id="lease-1",
        lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
        heartbeat_at=now.isoformat(),
        attachment_type="named_session",
        attachment_name="ia-worker-1",
        attachment_transport="tg",
        attachment_chat_id=21,
        attachment_session_id=session_id,
        attached_at=(now - timedelta(seconds=5)).isoformat(),
        started_at=(now - timedelta(seconds=5)).isoformat(),
    )


@pytest.mark.asyncio
async def test_create_and_await_ready_bootstrap_named_session_runtime(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    orchestrator = _make_orchestrator(named_sessions_path)
    orchestrator.cli_service.execute.return_value = AgentResponse(
        result="WORKER_RUNTIME_READY",
        session_id="sess-worker-1",
    )
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=orchestrator,
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    created = await controller.create("worker-1")
    awaited = await controller.await_ready("worker-1", timeout_seconds=0.01)
    fetched = await controller.fetch_state("worker-1")

    runtime = store.get_worker_runtime("worker-1")
    assert created.status is WorkerStatus.READY
    assert awaited.status is WorkerStatus.READY
    assert fetched.status is WorkerStatus.READY
    assert runtime.status == "ready"
    assert runtime.attachment_session_id == "sess-worker-1"


@pytest.mark.asyncio
async def test_fetch_state_maps_busy_runtime_to_running(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    store.put_worker_runtime(_busy_runtime(session_id="sess-busy"))
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=_make_orchestrator(named_sessions_path),
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    state = await controller.fetch_state("worker-1")

    assert state.status is WorkerStatus.RUNNING
    assert state.status_reason is None


@pytest.mark.asyncio
async def test_restart_recycles_runtime_and_rebinds_session(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-old",
    )
    store.put_worker_runtime(_ready_runtime(session_id="sess-old"))
    orchestrator = _make_orchestrator(named_sessions_path)
    orchestrator.cli_service.execute.return_value = AgentResponse(
        result="WORKER_RUNTIME_READY",
        session_id="sess-new",
    )
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=orchestrator,
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    state = await controller.restart("worker-1")

    runtime = store.get_worker_runtime("worker-1")
    assert state.status is WorkerStatus.READY
    assert runtime.status == "ready"
    assert runtime.attachment_session_id == "sess-new"
    orchestrator.end_named_session.assert_awaited_once_with(21, "ia-worker-1")


@pytest.mark.asyncio
async def test_terminate_maps_stopped_runtime_to_finished(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-ready",
    )
    store.put_worker_runtime(_ready_runtime(session_id="sess-ready"))
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=orchestrator,
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    state = await controller.terminate("worker-1")

    runtime = store.get_worker_runtime("worker-1")
    assert state.status is WorkerStatus.FINISHED
    assert runtime.status == "stopped"
    assert runtime.stopped_at is not None


@pytest.mark.asyncio
async def test_fetch_state_classifies_unknown_worker_as_contract_error(tmp_path: Path) -> None:
    state_root, _store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=_make_orchestrator(named_sessions_path),
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    with pytest.raises(WorkerControllerError) as exc_info:
        await controller.fetch_state("missing-worker")

    assert exc_info.value.code is WorkerControllerErrorCode.NOT_FOUND
    assert exc_info.value.failure_class is FailureClass.CONTRACT


@pytest.mark.asyncio
async def test_create_classifies_bootstrap_failure_as_tool_runtime(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    orchestrator = _make_orchestrator(named_sessions_path)
    orchestrator.cli_service.execute.return_value = AgentResponse(
        result="bootstrap failed",
        is_error=True,
    )
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=orchestrator,
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    with pytest.raises(WorkerControllerError) as exc_info:
        await controller.create("worker-1")

    runtime = store.get_worker_runtime("worker-1")
    assert exc_info.value.code is WorkerControllerErrorCode.INTERNAL
    assert exc_info.value.failure_class is FailureClass.TOOL_RUNTIME
    assert runtime.status == "lost"
    assert "bootstrap failed" in (runtime.health_reason or "")


@pytest.mark.asyncio
async def test_await_ready_times_out_when_runtime_never_reaches_ready(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    controller = ControlMeshWorkerController(
        team_name="alpha-team",
        orchestrator=_make_orchestrator(named_sessions_path),
        team_state_root=state_root,
        named_sessions_path=named_sessions_path,
        keepalive_interval_seconds=None,
    )

    with pytest.raises(WorkerControllerError) as exc_info:
        await controller.await_ready(
            "worker-1",
            timeout_seconds=0.01,
            poll_interval_seconds=0.001,
        )

    assert exc_info.value.code is WorkerControllerErrorCode.TIMEOUT
    assert exc_info.value.failure_class is FailureClass.INFRA
