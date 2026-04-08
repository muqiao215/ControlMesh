"""Tests for team state primitives."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamMailboxMessage,
    TeamTask,
    TeamTaskClaim,
)
from ductor_bot.team.state import TeamStateStore


@pytest.fixture
def store(tmp_path: Path) -> TeamStateStore:
    return TeamStateStore(tmp_path / "team-state", "alpha-team")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def test_claim_task_leases_task_and_blocks_competing_claim(store: TeamStateStore) -> None:
    task = TeamTask(task_id="task-1", subject="Implement feature")
    store.upsert_task(task)

    claim = TeamTaskClaim(
        worker="worker-1",
        token="lease-1",
        claimed_at=_iso(datetime.now(UTC)),
        lease_expires_at=_iso(datetime.now(UTC) + timedelta(minutes=5)),
    )
    claimed = store.claim_task("task-1", claim)
    assert claimed.claim is not None
    assert claimed.claim.worker == "worker-1"

    with pytest.raises(ValueError, match="already claimed"):
        store.claim_task(
            "task-1",
            TeamTaskClaim(
                worker="worker-2",
                token="lease-2",
                claimed_at=_iso(datetime.now(UTC)),
                lease_expires_at=_iso(datetime.now(UTC) + timedelta(minutes=5)),
            ),
        )


def test_expired_claim_can_be_reclaimed(store: TeamStateStore) -> None:
    expired = datetime.now(UTC) - timedelta(minutes=1)
    store.upsert_task(
        TeamTask(
            task_id="task-1",
            subject="Implement feature",
            claim=TeamTaskClaim(
                worker="worker-1",
                token="stale",
                claimed_at=_iso(expired - timedelta(minutes=5)),
                lease_expires_at=_iso(expired),
            ),
        )
    )

    reclaimed = store.claim_task(
        "task-1",
        TeamTaskClaim(
            worker="worker-2",
            token="fresh",
            claimed_at=_iso(datetime.now(UTC)),
            lease_expires_at=_iso(datetime.now(UTC) + timedelta(minutes=5)),
        ),
        now=datetime.now(UTC),
    )
    assert reclaimed.claim is not None
    assert reclaimed.claim.worker == "worker-2"


def test_dispatch_request_lifecycle_records_timestamps(store: TeamStateStore) -> None:
    request = store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
        )
    )
    assert request.status == "pending"

    notified = store.transition_dispatch_request("dispatch-1", "notified")
    assert notified.notified_at is not None
    assert notified.delivered_at is None

    delivered = store.transition_dispatch_request("dispatch-1", "delivered")
    assert delivered.delivered_at is not None


def test_mailbox_message_lifecycle_records_timestamps(store: TeamStateStore) -> None:
    message = store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-1",
            subject="Need review",
            body="Please review the patch",
        )
    )
    assert message.status == "pending"

    notified = store.mark_mailbox_message_notified("msg-1")
    assert notified.notified_at is not None
    assert notified.delivered_at is None

    delivered = store.mark_mailbox_message_delivered("msg-1")
    assert delivered.delivered_at is not None

