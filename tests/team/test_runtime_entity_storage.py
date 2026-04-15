"""Tests for migration-safe per-runtime entity storage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
            task_description="Runtime entity storage seam",
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


def test_put_worker_runtime_writes_per_worker_entity_file_and_snapshot(store: TeamStateStore) -> None:
    runtime = store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))

    entity_path = store.paths.team_dir / "worker-runtimes" / "worker-1.json"

    assert runtime.worker == "worker-1"
    assert entity_path.exists()
    entity_payload = json.loads(entity_path.read_text())
    snapshot_payload = json.loads(store.paths.worker_runtimes_path.read_text())
    assert entity_payload["worker"] == "worker-1"
    assert snapshot_payload["worker_runtimes"][0]["worker"] == "worker-1"


def test_reads_prefer_per_worker_entity_over_stale_aggregate_snapshot(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            lease_id="lease-1",
            lease_expires_at=_iso(now + timedelta(minutes=5)),
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

    store.paths.worker_runtimes_path.write_text(
        json.dumps(
            {
                "worker_runtimes": [
                    {
                        "worker": "worker-1",
                        "status": "lost",
                        "health_reason": "stale aggregate row",
                        "updated_at": _iso(now - timedelta(minutes=5)),
                    }
                ]
            }
        )
    )

    runtime = store.get_worker_runtime("worker-1")
    listed = store.list_worker_runtimes()

    assert runtime.status == "ready"
    assert listed[0].status == "ready"


def test_put_worker_runtime_rejects_stale_updated_at_for_existing_worker(store: TeamStateStore) -> None:
    persisted = store.put_worker_runtime(TeamWorkerRuntimeState(worker="worker-1"))
    assert persisted.updated_at is not None

    stale_runtime = TeamWorkerRuntimeState(
        worker="worker-1",
        updated_at=_iso(datetime.fromisoformat(persisted.updated_at) - timedelta(seconds=1)),
    )

    with pytest.raises(ValueError, match="stale worker runtime update"):
        store.put_worker_runtime(stale_runtime)


def test_reads_legacy_aggregate_runtime_when_no_entity_files_exist(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.paths.worker_runtimes_path.write_text(
        json.dumps(
            {
                "worker_runtimes": [
                    {
                        "worker": "worker-legacy",
                        "status": "ready",
                        "lease_id": "lease-legacy",
                        "lease_expires_at": _iso(now + timedelta(minutes=5)),
                        "heartbeat_at": _iso(now),
                        "attachment_type": "named_session",
                        "attachment_name": "ia-worker-legacy",
                        "attachment_transport": "tg",
                        "attachment_chat_id": 7,
                        "attachment_session_id": "sess-legacy",
                        "attached_at": _iso(now - timedelta(minutes=1)),
                        "started_at": _iso(now - timedelta(minutes=1)),
                    }
                ]
            }
        )
    )

    runtime = store.get_worker_runtime("worker-legacy")

    assert runtime.worker == "worker-legacy"
    assert runtime.status == "ready"
