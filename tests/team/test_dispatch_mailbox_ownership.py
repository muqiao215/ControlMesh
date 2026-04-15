"""Focused write-boundary tests for dispatch and mailbox ownership."""

from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamDispatchResult,
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamWorker,
)
from controlmesh.team.state import TeamStateStore


@pytest.fixture
def store(tmp_path: Path) -> TeamStateStore:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Dispatch mailbox ownership hardening",
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


def _delivered_dispatch(store: TeamStateStore) -> None:
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


def test_record_dispatch_result_rejects_missing_reported_by(store: TeamStateStore) -> None:
    _delivered_dispatch(store)

    with pytest.raises(ValueError, match="reported_by is required"):
        store.record_dispatch_result(
            "dispatch-1",
            TeamDispatchResult(
                outcome="completed",
                summary="missing reporter",
                task_status="completed",
            ),
        )


def test_record_dispatch_result_accepts_only_assigned_worker(store: TeamStateStore) -> None:
    _delivered_dispatch(store)

    with pytest.raises(ValueError, match="must be reported by assigned worker 'worker-1'"):
        store.record_dispatch_result(
            "dispatch-1",
            TeamDispatchResult(
                outcome="completed",
                summary="wrong worker",
                reported_by="worker-2",
                task_status="completed",
            ),
        )

    updated = store.record_dispatch_result(
        "dispatch-1",
        TeamDispatchResult(
            outcome="completed",
            summary="right worker",
            reported_by="worker-1",
            task_status="completed",
        ),
    )

    assert updated.result is not None
    assert updated.result.reported_by == "worker-1"


def test_transition_dispatch_request_rejects_lifecycle_owned_metadata(store: TeamStateStore) -> None:
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            to_worker="worker-1",
            kind="task",
        )
    )

    with pytest.raises(ValueError, match="metadata field 'delivered_at' is lifecycle-owned"):
        store.transition_dispatch_request(
            "dispatch-1",
            "notified",
            metadata={"delivered_at": "2026-04-10T00:00:00+00:00"},
        )


def test_transition_dispatch_request_allows_route_runtime_metadata_only(store: TeamStateStore) -> None:
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            to_worker="worker-1",
            kind="task",
        )
    )

    updated = store.transition_dispatch_request(
        "dispatch-1",
        "notified",
        metadata={
            "live_route": "worker_session",
            "live_target_session": "tg:9:3",
            "execution_id": "exec-1",
            "runtime_lease_id": "lease-1",
            "runtime_lease_expires_at": "2026-04-10T00:05:00+00:00",
            "runtime_attachment_type": "named_session",
            "runtime_attachment_name": "ia-worker-1",
        },
    )

    assert updated.live_route == "worker_session"
    assert updated.execution_id == "exec-1"


def test_create_dispatch_request_rejects_non_pending_initial_status(store: TeamStateStore) -> None:
    with pytest.raises(ValueError, match="dispatch requests must be created in pending status"):
        store.create_dispatch_request(
            TeamDispatchRequest(
                request_id="dispatch-1",
                team_name="alpha-team",
                to_worker="worker-1",
                kind="task",
                status="failed",
            )
        )


def test_create_mailbox_message_rejects_non_pending_initial_status(store: TeamStateStore) -> None:
    with pytest.raises(ValueError, match="mailbox messages must be created in pending status"):
        store.create_mailbox_message(
            TeamMailboxMessage(
                message_id="msg-1",
                team_name="alpha-team",
                to_worker="worker-1",
                subject="Need review",
                body="Please review the patch.",
                status="delivered",
            )
        )


def test_create_mailbox_message_rejects_unknown_participants(store: TeamStateStore) -> None:
    with pytest.raises(ValueError, match="unknown worker 'worker-9'"):
        store.create_mailbox_message(
            TeamMailboxMessage(
                message_id="msg-1",
                team_name="alpha-team",
                to_worker="worker-9",
                subject="Need review",
                body="Please review the patch.",
            )
        )

    with pytest.raises(ValueError, match="unknown worker 'worker-9'"):
        store.create_mailbox_message(
            TeamMailboxMessage(
                message_id="msg-2",
                team_name="alpha-team",
                to_worker="worker-1",
                from_worker="worker-9",
                subject="Need review",
                body="Please review the patch.",
            )
        )


def test_create_mailbox_message_allows_leader_origin(store: TeamStateStore) -> None:
    message = store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-1",
            from_worker="main",
            subject="Need review",
            body="Please review the patch.",
        )
    )

    assert message.from_worker == "main"
