"""Tests for team worker runtime start/stop automation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ductor_bot.cli.types import AgentResponse
from ductor_bot.session.named import NamedSession, NamedSessionRegistry
from ductor_bot.team.models import (
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamWorker,
    TeamWorkerRuntimeState,
)
from ductor_bot.team.runtime_control import TeamRuntimeController
from ductor_bot.team.state import TeamStateStore


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
