"""Tests for team worker runtime lifecycle automation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
from controlmesh.team.runtime_attachment import TeamRuntimeAttachmentManager
from controlmesh.team.runtime_control import TeamRuntimeController
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.snapshot import TeamControlSnapshotManager
from controlmesh.workspace.paths import ControlMeshPaths


def _seed_store(tmp_path: Path) -> tuple[Path, TeamStateStore]:
    state_root = tmp_path / "team-state"
    store = TeamStateStore(state_root, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate worker runtime automation",
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


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


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


@pytest.mark.asyncio
async def test_start_worker_runtime_bootstraps_named_session_and_persists_ready(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    orchestrator = _make_orchestrator(named_sessions_path)
    orchestrator.cli_service.execute.return_value = AgentResponse(
        result="WORKER_RUNTIME_READY",
        session_id="sess-worker-1",
    )
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "start-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")
    session = NamedSessionRegistry(named_sessions_path).get(21, "ia-worker-1")

    assert result["ok"] is True
    assert result["operation"] == "start-worker-runtime"
    assert runtime.status == "ready"
    assert runtime.attachment_type == "named_session"
    assert runtime.attachment_name == "ia-worker-1"
    assert runtime.attachment_session_id == "sess-worker-1"
    assert runtime.attachment_chat_id == 21
    assert runtime.heartbeat_at is not None
    assert session is not None
    assert session.status == "idle"
    assert session.session_id == "sess-worker-1"
    request = orchestrator.cli_service.execute.await_args.args[0]
    assert request.chat_id == 21
    assert request.topic_id == 4
    assert request.process_label == "ns:ia-worker-1"
    assert request.provider_override == "codex"
    assert request.model_override == "gpt-5"
    await controller.shutdown()


@pytest.mark.asyncio
async def test_start_worker_runtime_reuses_existing_attachment_without_bootstrap(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-existing",
    )
    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "start-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")

    assert result["ok"] is True
    assert runtime.status == "ready"
    assert runtime.attachment_session_id == "sess-existing"
    orchestrator.cli_service.execute.assert_not_awaited()
    await controller.shutdown()


@pytest.mark.asyncio
async def test_start_worker_runtime_failure_marks_runtime_lost_and_ends_session(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    orchestrator = _make_orchestrator(named_sessions_path)
    orchestrator.cli_service.execute.return_value = AgentResponse(
        result="bootstrap failed",
        is_error=True,
    )
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "start-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")
    session = NamedSessionRegistry(named_sessions_path).get(21, "ia-worker-1")

    assert result["ok"] is False
    assert result["error"]["code"] == "internal_error"
    assert runtime.status == "lost"
    assert "bootstrap failed" in (runtime.health_reason or "")
    assert session is None


@pytest.mark.asyncio
async def test_stop_worker_runtime_ends_named_session_and_persists_stopped(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
            heartbeat_at=now.isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(seconds=5)).isoformat(),
            started_at=(now - timedelta(seconds=5)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "stop-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")
    session = NamedSessionRegistry(named_sessions_path).get(21, "ia-worker-1")

    assert result["ok"] is True
    assert runtime.status == "stopped"
    assert runtime.stopped_at is not None
    assert runtime.attachment_name is None
    assert runtime.lease_id is None
    assert session is None
    orchestrator.end_named_session.assert_awaited_once_with(21, "ia-worker-1")


@pytest.mark.asyncio
async def test_stop_worker_runtime_rejects_busy_runtime(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
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
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(seconds=5)).isoformat(),
            started_at=(now - timedelta(seconds=5)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "stop-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")
    session = NamedSessionRegistry(named_sessions_path).get(21, "ia-worker-1")

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_request"
    assert runtime.status == "busy"
    assert session is not None
    assert session.status == "idle"
    orchestrator.end_named_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_worker_runtime_renews_live_owner_lease(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    original_expiry = now + timedelta(seconds=30)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="busy",
            execution_id="exec-1",
            dispatch_request_id="dispatch-1",
            lease_id="lease-1",
            lease_expires_at=original_expiry.isoformat(),
            heartbeat_at=(now - timedelta(seconds=10)).isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "heartbeat-worker-runtime",
        {
            "team_name": "alpha-team",
            "worker": "worker-1",
            "session_id": "sess-worker-1",
        },
    )

    runtime = store.get_worker_runtime("worker-1")
    assert result["ok"] is True
    assert result["operation"] == "heartbeat-worker-runtime"
    assert result["data"]["action"] == "renewed"
    assert runtime.status == "busy"
    assert runtime.execution_id == "exec-1"
    assert runtime.dispatch_request_id == "dispatch-1"
    assert runtime.heartbeat_at is not None
    assert runtime.heartbeat_at > (now - timedelta(seconds=10)).isoformat()
    assert runtime.lease_expires_at is not None
    assert runtime.lease_expires_at > original_expiry.isoformat()


@pytest.mark.asyncio
async def test_heartbeat_worker_runtime_rejects_stale_owner_session_id(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-live",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
            heartbeat_at=now.isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-live",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "heartbeat-worker-runtime",
        {
            "team_name": "alpha-team",
            "worker": "worker-1",
            "session_id": "sess-stale",
        },
    )

    runtime = store.get_worker_runtime("worker-1")
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_request"
    assert "owned by session 'sess-live'" in result["error"]["message"]
    assert runtime.status == "ready"
    assert runtime.attachment_session_id == "sess-live"


@pytest.mark.asyncio
async def test_start_worker_runtime_arms_idle_keepalive_driver(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(
        orchestrator=orchestrator,
        team_state_root=state_root,
        keepalive_interval_seconds=0.01,
    )

    await controller.execute(
        "start-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )
    attached = store.get_worker_runtime("worker-1")
    initial_heartbeat = attached.heartbeat_at
    initial_expiry = attached.lease_expires_at

    await asyncio.sleep(0.05)

    renewed = store.get_worker_runtime("worker-1")
    assert renewed.status == "ready"
    assert renewed.heartbeat_at is not None
    assert renewed.heartbeat_at > (initial_heartbeat or "")
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > (initial_expiry or "")
    await controller.shutdown()


@pytest.mark.asyncio
async def test_keepalive_driver_renews_busy_runtime_after_start(tmp_path: Path) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(
        orchestrator=orchestrator,
        team_state_root=state_root,
        keepalive_interval_seconds=0.01,
    )

    await controller.execute(
        "start-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )
    ready = store.get_worker_runtime("worker-1")
    busy = store.transition_worker_runtime(
        "worker-1",
        "busy",
        updates={
            "execution_id": "exec-1",
            "dispatch_request_id": "dispatch-1",
        },
    )

    await asyncio.sleep(0.05)

    renewed = store.get_worker_runtime("worker-1")
    assert ready.status == "ready"
    assert busy.status == "busy"
    assert renewed.status == "busy"
    assert renewed.execution_id == "exec-1"
    assert renewed.dispatch_request_id == "dispatch-1"
    assert renewed.heartbeat_at is not None
    assert renewed.heartbeat_at > (busy.heartbeat_at or "")
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > (busy.lease_expires_at or "")
    await controller.shutdown()


@pytest.mark.asyncio
async def test_recover_live_runtimes_rearms_valid_runtime_and_is_idempotent(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    original_expiry = now + timedelta(seconds=30)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=original_expiry.isoformat(),
            heartbeat_at=(now - timedelta(seconds=10)).isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(
        orchestrator=orchestrator,
        team_state_root=state_root,
        keepalive_interval_seconds=0.01,
    )

    recovered = await controller.recover_live_runtimes()
    runtime = store.get_worker_runtime("worker-1")
    keepalive_key = ("alpha-team", "worker-1")
    keepalive_task = controller._keepalive_tasks[keepalive_key]

    assert recovered == [runtime]
    assert runtime.status == "ready"
    assert runtime.lease_expires_at is not None
    assert runtime.lease_expires_at > original_expiry.isoformat()

    await controller.recover_live_runtimes()
    assert controller._keepalive_tasks[keepalive_key] is keepalive_task

    await asyncio.sleep(0.05)

    renewed = store.get_worker_runtime("worker-1")
    assert renewed.heartbeat_at is not None
    assert renewed.heartbeat_at > (runtime.heartbeat_at or "")
    await controller.shutdown()


@pytest.mark.asyncio
async def test_recover_live_runtimes_invalidates_stale_owner_without_keepalive(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-live",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
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
            attachment_session_id="sess-stale",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(
        orchestrator=orchestrator,
        team_state_root=state_root,
        keepalive_interval_seconds=0.01,
    )

    recovered = await controller.recover_live_runtimes()
    runtime = store.get_worker_runtime("worker-1")

    assert recovered == []
    assert runtime.status == "lost"
    assert runtime.health_reason == "runtime owner changed"
    assert controller._keepalive_tasks == {}
    await controller.shutdown()


@pytest.mark.asyncio
async def test_recover_live_runtimes_skips_team_with_fresh_snapshot_and_no_live_runtimes(
    tmp_path: Path,
) -> None:
    state_root, _store = _seed_store(tmp_path)
    paths = _paths(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    TeamControlSnapshotManager(paths, state_root=state_root).write(
        "alpha-team",
        generated_at="2026-04-10T00:00:00+00:00",
    )
    orchestrator = _make_orchestrator(named_sessions_path)

    with (
        patch("controlmesh.team.runtime_control.resolve_paths", return_value=paths),
        patch(
            "controlmesh.team.runtime_control._utc_now",
            return_value=datetime(2026, 4, 10, 0, 0, 30, tzinfo=UTC),
        ),
        patch(
            "controlmesh.team.runtime_control.default_runtime_recovery_snapshot_max_age_seconds",
            return_value=300,
        ),
        patch.object(
            TeamStateStore,
            "read_manifest",
            side_effect=AssertionError("canonical recovery path should be skipped"),
        ),
    ):
        controller = TeamRuntimeController(
            orchestrator=orchestrator,
            team_state_root=state_root,
            keepalive_interval_seconds=0.01,
        )
        with patch.object(
            controller._snapshot_recovery_advisor,
            "refresh_and_evaluate",
            wraps=controller._snapshot_recovery_advisor.refresh_and_evaluate,
        ) as advice_mock:
            recovered = await controller.recover_live_runtimes()

    assert recovered == []
    assert advice_mock.call_args.kwargs["max_age_seconds"] == 300
    await controller.shutdown()


@pytest.mark.asyncio
async def test_recover_live_runtimes_missing_snapshot_refreshes_then_recovers_live_runtime(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    paths = _paths(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            heartbeat_at=(now - timedelta(seconds=10)).isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)

    with (
        patch("controlmesh.team.runtime_control.resolve_paths", return_value=paths),
        patch(
            "controlmesh.team.runtime_control._utc_now",
            return_value=datetime(2026, 4, 10, 0, 1, 30, tzinfo=UTC),
        ),
        patch(
            "controlmesh.team.state.snapshot.utc_now",
            return_value="2026-04-10T00:01:00+00:00",
        ),
    ):
        controller = TeamRuntimeController(
            orchestrator=orchestrator,
            team_state_root=state_root,
            keepalive_interval_seconds=0.01,
        )
        with patch.object(controller, "_recover_runtime", wraps=controller._recover_runtime) as recover_mock:
            recovered = await controller.recover_live_runtimes()

    runtime = store.get_worker_runtime("worker-1")
    snapshot = TeamControlSnapshotManager(paths, state_root=state_root).read("alpha-team")

    assert recovered == [runtime]
    assert recover_mock.call_count == 1
    assert snapshot.runtimes.counts["ready"] == 1
    await controller.shutdown()


@pytest.mark.asyncio
async def test_recover_live_runtimes_stale_snapshot_refreshes_before_canonical_recovery(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    paths = _paths(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    manager = TeamControlSnapshotManager(paths, state_root=state_root)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-worker-1",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            heartbeat_at=(now - timedelta(seconds=10)).isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(minutes=1)).isoformat(),
            started_at=(now - timedelta(minutes=1)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)

    with (
        patch("controlmesh.team.runtime_control.resolve_paths", return_value=paths),
        patch(
            "controlmesh.team.runtime_control._utc_now",
            return_value=datetime(2026, 4, 10, 0, 10, 30, tzinfo=UTC),
        ),
        patch(
            "controlmesh.team.state.snapshot.utc_now",
            return_value="2026-04-10T00:10:00+00:00",
        ),
    ):
        controller = TeamRuntimeController(
            orchestrator=orchestrator,
            team_state_root=state_root,
            keepalive_interval_seconds=0.01,
        )
        with patch.object(controller, "_recover_runtime", wraps=controller._recover_runtime) as recover_mock:
            recovered = await controller.recover_live_runtimes()

    runtime = store.get_worker_runtime("worker-1")
    snapshot = manager.read("alpha-team")

    assert recovered == [runtime]
    assert recover_mock.call_count == 1
    assert snapshot.generated_at == "2026-04-10T00:10:30+00:00"
    assert snapshot.runtimes.counts["ready"] == 1
    await controller.shutdown()


def test_reconcile_runtime_marks_owner_session_id_change_lost(tmp_path: Path) -> None:
    _, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    _seed_named_session(
        named_sessions_path,
        name="ia-worker-1",
        chat_id=21,
        session_id="sess-new",
    )
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
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
            attachment_session_id="sess-old",
            attached_at=(now - timedelta(seconds=5)).isoformat(),
            started_at=(now - timedelta(seconds=5)).isoformat(),
        )
    )
    manager = TeamRuntimeAttachmentManager(named_sessions_path=named_sessions_path)

    runtime = manager.reconcile_runtime_owner(store, store.read_manifest(), "worker-1", now=now)

    assert runtime.status == "lost"
    assert runtime.execution_id == "exec-1"
    assert runtime.dispatch_request_id is None
    assert runtime.health_reason == "runtime owner changed"


def test_reconcile_runtime_marks_missing_owner_lost(tmp_path: Path) -> None:
    _, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=(now + timedelta(minutes=5)).isoformat(),
            heartbeat_at=now.isoformat(),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=21,
            attachment_session_id="sess-worker-1",
            attached_at=(now - timedelta(seconds=5)).isoformat(),
            started_at=(now - timedelta(seconds=5)).isoformat(),
        )
    )
    manager = TeamRuntimeAttachmentManager(named_sessions_path=named_sessions_path)

    runtime = manager.reconcile_runtime_owner(store, store.read_manifest(), "worker-1", now=now)

    assert runtime.status == "lost"
    assert runtime.health_reason == "runtime owner missing"


@pytest.mark.asyncio
async def test_stop_worker_runtime_allows_stale_busy_owner_to_downgrade_then_stop(
    tmp_path: Path,
) -> None:
    state_root, store = _seed_store(tmp_path)
    named_sessions_path = tmp_path / "named_sessions.json"
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
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
            attachment_session_id="sess-stale",
            attached_at=(now - timedelta(seconds=5)).isoformat(),
            started_at=(now - timedelta(seconds=5)).isoformat(),
        )
    )
    orchestrator = _make_orchestrator(named_sessions_path)
    controller = TeamRuntimeController(orchestrator=orchestrator, team_state_root=state_root)

    result = await controller.execute(
        "stop-worker-runtime",
        {"team_name": "alpha-team", "worker": "worker-1"},
    )

    runtime = store.get_worker_runtime("worker-1")

    assert result["ok"] is True
    assert runtime.status == "stopped"
    orchestrator.end_named_session.assert_not_awaited()
