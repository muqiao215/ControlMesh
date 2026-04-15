"""Tests for derived compact team control-plane snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamEvent,
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamWorker,
    TeamWorkerRuntimeState,
)
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.snapshot import (
    TeamControlSnapshotManager,
    TeamControlSnapshotReadStatus,
)
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _seed_manifest(store: TeamStateStore) -> None:
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate snapshot cut",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7, topic_id=12),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(name="worker-1", role="executor", provider="codex"),
                TeamWorker(name="worker-2", role="verifier", provider="codex"),
            ],
        )
    )


def test_build_snapshot_from_minimal_canonical_state(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)

    snapshot = TeamControlSnapshotManager(paths).build(
        "alpha-team",
        generated_at="2026-04-10T00:00:00+00:00",
    )

    assert snapshot.schema_version == 1
    assert snapshot.generated_at == "2026-04-10T00:00:00+00:00"
    assert snapshot.team_name == "alpha-team"
    assert snapshot.manifest.leader_agent_name == "main"
    assert snapshot.manifest.leader_session_key == "tg:7:12"
    assert snapshot.manifest.worker_ids == ["worker-1", "worker-2"]
    assert snapshot.phase.current_phase == "plan"
    assert snapshot.tasks.active_task_ids == []
    assert snapshot.runtimes.busy_workers == []
    assert snapshot.dispatch.pending_request_ids == []
    assert snapshot.mailbox.pending_message_ids == []
    assert snapshot.latest_event_id is None


def test_build_snapshot_from_populated_team_state(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    now = datetime.now(UTC)

    store.write_phase(
        TeamPhaseState(current_phase="verify", active=True, current_repair_attempt=1, max_repair_attempts=3)
    )
    store.upsert_task(TeamTask(task_id="task-active", subject="Implement feature", status="in_progress"))
    store.upsert_task(TeamTask(task_id="task-blocked", subject="Fix regression", status="blocked"))
    store.upsert_task(TeamTask(task_id="task-done", subject="Document change", status="completed"))
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="busy",
            execution_id="exec-1",
            dispatch_request_id="dispatch-2",
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
    store.put_worker_runtime(
        TeamWorkerRuntimeState(worker="worker-2", status="lost", health_reason="runtime owner missing")
    )
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-active",
            to_worker="worker-1",
            kind="task",
        )
    )
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-2",
            team_name="alpha-team",
            task_id="task-active",
            to_worker="worker-1",
            kind="task",
        )
    )
    store.transition_dispatch_request("dispatch-2", "delivered")
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-3",
            team_name="alpha-team",
            task_id="task-blocked",
            to_worker="worker-2",
            kind="task",
        )
    )
    store.transition_dispatch_request("dispatch-3", "failed", error="worker failed")
    store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-1",
            from_worker="main",
            subject="Need review",
            body="Please review.",
        )
    )
    store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-2",
            team_name="alpha-team",
            to_worker="worker-2",
            from_worker="worker-1",
            subject="Need verify",
            body="Please verify.",
        )
    )
    store.mark_mailbox_message_notified("msg-2")
    store.append_event(TeamEvent(event_id="evt-1", team_name="alpha-team", event_type="task_claimed"))
    store.append_event(TeamEvent(event_id="evt-2", team_name="alpha-team", event_type="summary_generated"))

    snapshot = TeamControlSnapshotManager(paths).build(
        "alpha-team",
        generated_at="2026-04-10T00:00:00+00:00",
    )

    assert snapshot.phase.current_phase == "verify"
    assert snapshot.tasks.counts["in_progress"] == 1
    assert snapshot.tasks.counts["blocked"] == 1
    assert snapshot.tasks.counts["completed"] == 1
    assert snapshot.tasks.active_task_ids == ["task-active", "task-blocked"]
    assert snapshot.runtimes.counts["busy"] == 1
    assert snapshot.runtimes.counts["lost"] == 1
    assert snapshot.runtimes.busy_workers == ["worker-1"]
    assert snapshot.runtimes.lost_workers == ["worker-2"]
    assert snapshot.dispatch.counts["pending"] == 1
    assert snapshot.dispatch.counts["delivered"] == 1
    assert snapshot.dispatch.counts["failed"] == 1
    assert snapshot.dispatch.pending_request_ids == ["dispatch-1"]
    assert snapshot.dispatch.active_request_ids == ["dispatch-1", "dispatch-2"]
    assert snapshot.mailbox.counts["pending"] == 1
    assert snapshot.mailbox.counts["notified"] == 1
    assert snapshot.mailbox.pending_message_ids == ["msg-1"]
    assert snapshot.latest_event_id == "evt-2"


def test_snapshot_rebuild_equivalence_from_same_canonical_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="pending"))
    manager = TeamControlSnapshotManager(paths)

    first = manager.build("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    second = manager.build("alpha-team", generated_at="2026-04-10T00:00:00+00:00")

    assert second == first


def test_snapshot_write_overwrites_atomically_and_canonical_files_remain_authoritative(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="pending"))
    manager = TeamControlSnapshotManager(paths)

    first = manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    snapshot_path = manager.path_for("alpha-team")
    first_payload = json.loads(snapshot_path.read_text())

    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="completed"))
    second = manager.write("alpha-team", generated_at="2026-04-10T00:01:00+00:00")
    second_payload = json.loads(snapshot_path.read_text())
    read_back = manager.read("alpha-team")

    assert snapshot_path == paths.team_control_snapshots_dir / "alpha-team.json"
    assert first.tasks.counts["pending"] == 1
    assert first.tasks.counts["completed"] == 0
    assert first_payload["tasks"]["counts"]["pending"] == 1
    assert second_payload["tasks"]["counts"]["pending"] == 0
    assert second_payload["tasks"]["counts"]["completed"] == 1
    assert second.tasks.counts["completed"] == 1
    assert read_back == second


def test_read_status_marks_recent_snapshot_fresh(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")

    status = manager.read_status(
        "alpha-team",
        max_age_seconds=300,
        now=datetime(2026, 4, 10, 0, 4, 59, tzinfo=UTC),
    )

    assert status == TeamControlSnapshotReadStatus(
        snapshot=manager.read("alpha-team"),
        stale=False,
    )


def test_read_status_marks_old_snapshot_stale(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")

    status = manager.read_status(
        "alpha-team",
        max_age_seconds=300,
        now=datetime(2026, 4, 10, 0, 5, 1, tzinfo=UTC),
    )

    assert status.stale is True


def test_read_status_missing_snapshot_raises_not_found(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    manager = TeamControlSnapshotManager(paths)

    with pytest.raises(FileNotFoundError, match="team control snapshot not found"):
        manager.read_status("alpha-team", max_age_seconds=60)


def test_read_status_rejects_invalid_generated_at_deterministically(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    manager = TeamControlSnapshotManager(paths)
    snapshot = manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    snapshot_path = manager.path_for("alpha-team")
    payload = snapshot.model_dump(mode="json")
    payload["generated_at"] = "2026-04-10T00:00:00"
    snapshot_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="generated_at must be a timezone-aware ISO-8601 timestamp"):
        manager.read_status(
            "alpha-team",
            max_age_seconds=60,
            now=datetime(2026, 4, 10, 0, 1, 0, tzinfo=UTC),
        )


def test_read_status_does_not_mutate_canonical_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    store = TeamStateStore(paths.team_state_dir, "alpha-team")
    _seed_manifest(store)
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="pending"))
    manager = TeamControlSnapshotManager(paths)
    manager.write("alpha-team", generated_at="2026-04-10T00:00:00+00:00")
    tasks_before = store.paths.tasks_path.read_text(encoding="utf-8")

    status = manager.read_status(
        "alpha-team",
        max_age_seconds=60,
        now=datetime(2026, 4, 10, 0, 0, 30, tzinfo=UTC),
    )
    tasks_after = store.paths.tasks_path.read_text(encoding="utf-8")

    assert status.stale is False
    assert tasks_after == tasks_before
