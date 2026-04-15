"""Tests for persisted worker runtime lifecycle state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from controlmesh.team.models import (
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamWorker,
    TeamWorkerRuntimeState,
)
from controlmesh.team.state import TeamStateStore


@pytest.fixture
def store(tmp_path: Path) -> TeamStateStore:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate runtime state",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(name="worker-1", role="executor", provider="codex"),
                TeamWorker(name="worker-2", role="verifier"),
            ],
        )
    )
    return store


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def test_worker_runtime_lifecycle_enforces_hard_state_boundaries(store: TeamStateStore) -> None:
    created = store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    assert created.status == "created"

    with pytest.raises(ValueError, match="invalid worker runtime transition: created -> ready"):
        store.transition_worker_runtime("worker-1", "ready")


def test_worker_runtime_persists_execution_lease_and_heartbeat(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(minutes=5)
    heartbeat_at = now + timedelta(seconds=20)

    store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    starting = store.transition_worker_runtime(
        "worker-1",
        "starting",
        updates={
            "attachment_type": "named_session",
            "attachment_name": "ia-worker-1",
            "attachment_transport": "tg",
            "attachment_chat_id": 7,
            "attachment_session_id": "sess-worker-1",
            "lease_id": "lease-1",
            "lease_expires_at": _iso(lease_expires_at),
            "attached_at": _iso(now),
        },
    )
    store.record_worker_runtime_heartbeat(
        "worker-1",
        lease_id="lease-1",
        heartbeat_at=_iso(heartbeat_at),
        lease_expires_at=_iso(lease_expires_at + timedelta(minutes=1)),
    )
    ready = store.transition_worker_runtime("worker-1", "ready")
    busy = store.transition_worker_runtime(
        "worker-1",
        "busy",
        updates={
            "execution_id": "exec-1",
            "dispatch_request_id": "dispatch-1",
        },
    )

    persisted = store.get_worker_runtime("worker-1")

    assert starting.status == "starting"
    assert ready.status == "ready"
    assert busy.status == "busy"
    assert persisted.execution_id == "exec-1"
    assert persisted.dispatch_request_id == "dispatch-1"
    assert persisted.lease_id == "lease-1"
    assert persisted.heartbeat_at == _iso(heartbeat_at)
    assert persisted.lease_expires_at == _iso(lease_expires_at + timedelta(minutes=1))
    assert persisted.attachment_type == "named_session"
    assert persisted.attachment_name == "ia-worker-1"
    assert persisted.attachment_session_id == "sess-worker-1"


def test_reconcile_worker_runtime_marks_expired_lease_lost(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    expired_at = now - timedelta(minutes=1)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="busy",
            execution_id="exec-1",
            dispatch_request_id="dispatch-1",
            lease_id="lease-1",
            lease_expires_at=_iso(expired_at),
            heartbeat_at=_iso(expired_at - timedelta(seconds=10)),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=7,
            attachment_session_id="sess-worker-1",
            attached_at=_iso(expired_at - timedelta(minutes=3)),
            started_at=_iso(expired_at - timedelta(minutes=2)),
        )
    )

    reconciled = store.reconcile_worker_runtime("worker-1", now=now)

    assert reconciled.status == "lost"
    assert reconciled.execution_id == "exec-1"
    assert reconciled.lease_id == "lease-1"
    assert reconciled.dispatch_request_id is None
    assert reconciled.health_reason == "runtime lease expired"


def test_worker_runtime_summary_exposes_dynamic_runtime_truth(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="busy",
            execution_id="exec-9",
            dispatch_request_id="dispatch-9",
            lease_id="lease-9",
            lease_expires_at=_iso(now + timedelta(minutes=2)),
            heartbeat_at=_iso(now),
            attachment_type="named_session",
            attachment_name="ia-worker-1",
            attachment_transport="tg",
            attachment_chat_id=7,
            attachment_session_id="sess-worker-1",
            attached_at=_iso(now - timedelta(minutes=1)),
            started_at=_iso(now - timedelta(minutes=1)),
        )
    )

    summary = store.build_summary()
    runtime_counts = cast("dict[str, int]", summary["worker_runtime_counts"])
    runtime_states = cast("list[dict[str, Any]]", summary["worker_runtime_states"])

    assert runtime_counts["busy"] == 1
    assert runtime_counts["created"] == 0
    assert runtime_states[0]["worker"] == "worker-1"
    assert runtime_states[0]["status"] == "busy"
    assert runtime_states[0]["execution_id"] == "exec-9"
    assert runtime_states[0]["dispatch_request_id"] == "dispatch-9"
    assert runtime_states[0]["attachment_type"] == "named_session"
