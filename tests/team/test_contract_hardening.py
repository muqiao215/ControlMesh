"""Focused contract hardening tests for team/task/runtime state reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamDispatchResult,
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamTaskClaim,
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
            task_description="Harden authoritative team state contracts",
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


def test_terminal_task_status_clears_stale_claim_on_reads(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.upsert_task(
        TeamTask(
            task_id="task-1",
            subject="Finish implementation",
            status="completed",
            owner="worker-1",
            claim=TeamTaskClaim(
                worker="worker-1",
                token="lease-1",
                claimed_at=_iso(now - timedelta(minutes=2)),
                lease_expires_at=_iso(now + timedelta(minutes=3)),
            ),
        )
    )

    task = store.get_task("task-1")
    completed = store.list_tasks(status="completed")

    assert task.status == "completed"
    assert task.claim is None
    assert task.owner == "worker-1"
    assert task.completed_at is not None
    assert completed[0].claim is None


def test_dispatch_status_normalization_clears_stale_result_fields(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.paths.team_dir.mkdir(parents=True, exist_ok=True)
    store.paths.dispatch_path.write_text(
        json.dumps(
            {
                "dispatch_requests": [
                    {
                        "request_id": "dispatch-1",
                        "team_name": "alpha-team",
                        "task_id": "task-1",
                        "to_worker": "worker-1",
                        "kind": "task",
                        "status": "failed",
                        "delivered_at": _iso(now - timedelta(minutes=1)),
                        "failed_at": _iso(now),
                        "last_error": "worker crashed",
                        "result": {
                            "outcome": "completed",
                            "summary": "stale result",
                            "reported_by": "worker-1",
                            "task_status": "completed",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    request = store.get_dispatch_request("dispatch-1")

    assert request.status == "failed"
    assert request.failed_at is not None
    assert request.last_error == "worker crashed"
    assert request.delivered_at is None
    assert request.result is None


def test_mailbox_status_normalization_clears_stale_delivery_timestamps(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.paths.team_dir.mkdir(parents=True, exist_ok=True)
    store.paths.mailbox_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "message_id": "msg-1",
                        "team_name": "alpha-team",
                        "to_worker": "worker-2",
                        "from_worker": "worker-1",
                        "subject": "Verify patch",
                        "body": "Please verify the final patch.",
                        "status": "pending",
                        "notified_at": _iso(now - timedelta(minutes=2)),
                        "delivered_at": _iso(now - timedelta(minutes=1)),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    message = store.get_mailbox_message("msg-1")

    assert message.status == "pending"
    assert message.notified_at is None
    assert message.delivered_at is None


def test_ready_runtime_status_clears_stale_execution_ownership_on_reads(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.put_worker_runtime(
        TeamWorkerRuntimeState(
            worker="worker-1",
            status="ready",
            execution_id="exec-stale",
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

    runtime = store.get_worker_runtime("worker-1")
    summary = store.build_summary()

    assert runtime.status == "ready"
    assert runtime.execution_id is None
    assert summary["worker_runtime_states"][0]["execution_id"] is None


def test_record_dispatch_result_rejects_non_owner_reporter(store: TeamStateStore) -> None:
    store.upsert_task(TeamTask(task_id="task-1", subject="Implement feature", status="in_progress"))
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
        )
    )
    store.transition_dispatch_request("dispatch-1", "delivered")

    with pytest.raises(ValueError, match="must be reported by assigned worker 'worker-1'"):
        store.record_dispatch_result(
            "dispatch-1",
            TeamDispatchResult(
                outcome="completed",
                summary="wrong worker replied",
                reported_by="worker-2",
                task_status="completed",
            ),
        )


def test_store_reads_normalize_raw_stale_files_without_rewriting_authority(store: TeamStateStore) -> None:
    now = datetime.now(UTC)
    store.paths.tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "task-1",
                        "subject": "Ship hardening",
                        "status": "failed",
                        "owner": "worker-2",
                        "claim": {
                            "worker": "worker-1",
                            "token": "lease-1",
                            "claimed_at": _iso(now - timedelta(minutes=3)),
                            "lease_expires_at": _iso(now + timedelta(minutes=3)),
                        },
                        "completed_at": _iso(now),
                    }
                ]
            }
        )
    )

    task = store.get_task("task-1")

    assert task.status == "failed"
    assert task.claim is None
    assert task.owner == "worker-1"
    assert task.completed_at is None
