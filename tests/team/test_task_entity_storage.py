"""Tests for migration-safe per-task entity storage."""

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
    TeamTask,
    TeamTaskClaim,
)
from controlmesh.team.state import TeamStateStore


@pytest.fixture
def store(tmp_path: Path) -> TeamStateStore:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Task entity storage seam",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
        )
    )
    return store


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def test_upsert_task_writes_per_task_entity_file_and_snapshot(store: TeamStateStore) -> None:
    task = store.upsert_task(TeamTask(task_id="task-1", subject="Implement seam"))

    entity_path = store.paths.team_dir / "tasks" / "task-1.json"

    assert task.task_id == "task-1"
    assert entity_path.exists()
    entity_payload = json.loads(entity_path.read_text())
    snapshot_payload = json.loads(store.paths.tasks_path.read_text())
    assert entity_payload["task_id"] == "task-1"
    assert snapshot_payload["tasks"][0]["task_id"] == "task-1"


def test_reads_prefer_per_task_entity_over_stale_aggregate_snapshot(store: TeamStateStore) -> None:
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement seam", status="pending"))

    store.paths.tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-1",
                        "subject": "Implement seam",
                        "status": "failed",
                        "updated_at": _iso(datetime.now(UTC) - timedelta(minutes=5)),
                    }
                ]
            }
        )
    )

    task = store.get_task("task-1")
    listed = store.list_tasks()

    assert task.status == "pending"
    assert listed[0].status == "pending"


def test_upsert_task_rejects_stale_updated_at_for_existing_task(store: TeamStateStore) -> None:
    persisted = store.upsert_task(TeamTask(task_id="task-1", subject="Implement seam", status="pending"))
    assert persisted.updated_at is not None

    stale_task = TeamTask(
        task_id="task-1",
        subject="Implement seam",
        status="completed",
        owner="worker-1",
        claim=TeamTaskClaim(
            worker="worker-1",
            token="lease-1",
            claimed_at=_iso(datetime.now(UTC) - timedelta(minutes=2)),
            lease_expires_at=_iso(datetime.now(UTC) + timedelta(minutes=2)),
        ),
        updated_at=_iso(datetime.fromisoformat(persisted.updated_at) - timedelta(seconds=1)),
    )

    with pytest.raises(ValueError, match="stale task update"):
        store.upsert_task(stale_task)


def test_reads_legacy_aggregate_tasks_when_no_entity_files_exist(store: TeamStateStore) -> None:
    store.paths.tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-legacy",
                        "subject": "Legacy task",
                        "status": "in_progress",
                    }
                ]
            }
        )
    )

    task = store.get_task("task-legacy")

    assert task.task_id == "task-legacy"
    assert task.status == "in_progress"
