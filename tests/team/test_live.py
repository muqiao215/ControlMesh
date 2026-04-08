"""Tests for live team dispatch through the shared MessageBus."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ductor_bot.bus.envelope import LockMode, Origin
from ductor_bot.team.live import (
    TeamLiveDispatcher,
    build_dispatch_envelope,
    build_mailbox_envelope,
)
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamWorker,
)
from ductor_bot.team.state import TeamStateStore


@pytest.fixture
def store(tmp_path: Path) -> TeamStateStore:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate live team dispatch",
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
                        provider_session_id="codex-sess-1",
                        session_name="ia-worker-1",
                        routable_session=TeamSessionRef(transport="tg", chat_id=21, topic_id=4),
                    ),
                ),
                TeamWorker(name="worker-2", role="verifier"),
            ],
        )
    )
    return store


def test_build_dispatch_envelope_targets_leader_session(store: TeamStateStore) -> None:
    request = store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
        )
    )

    envelope = build_dispatch_envelope(store.read_manifest(), request)

    assert envelope.origin == Origin.INTERAGENT
    assert envelope.chat_id == 7
    assert envelope.topic_id == 12
    assert envelope.transport == "tg"
    assert envelope.lock_mode == LockMode.REQUIRED
    assert envelope.needs_injection is True
    assert envelope.metadata["team_name"] == "alpha-team"
    assert envelope.metadata["request_id"] == "dispatch-1"
    assert envelope.metadata["recipient"] == "worker-1"
    assert envelope.metadata["worker_provider"] == "codex"
    assert envelope.metadata["worker_session_name"] == "ia-worker-1"
    assert envelope.metadata["worker_provider_session_id"] == "codex-sess-1"
    assert envelope.metadata["worker_routable_session"] == "tg:21:4"
    assert "worker-1" in envelope.prompt
    assert "task-1" in envelope.prompt
    assert "ia-worker-1" in envelope.prompt
    assert "tg:21:4" in envelope.prompt


def test_build_mailbox_envelope_targets_leader_session_without_injection(
    store: TeamStateStore,
) -> None:
    message = store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-2",
            from_worker="worker-1",
            subject="Need verification",
            body="Please verify the latest patch.",
        )
    )

    envelope = build_mailbox_envelope(store.read_manifest(), message)

    assert envelope.origin == Origin.INTERAGENT
    assert envelope.chat_id == 7
    assert envelope.topic_id == 12
    assert envelope.transport == "tg"
    assert envelope.needs_injection is False
    assert envelope.lock_mode == LockMode.NONE
    assert "Need verification" in envelope.result_text
    assert "worker-1" in envelope.result_text
    assert "worker-2" in envelope.result_text


async def test_dispatch_request_success_marks_delivered_and_appends_events(
    store: TeamStateStore,
) -> None:
    request = store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
        )
    )
    bus = AsyncMock()

    async def _submit(envelope):  # type: ignore[no-untyped-def]
        envelope.result_text = "worker-1 acknowledged"

    bus.submit.side_effect = _submit
    dispatcher = TeamLiveDispatcher(store, bus)

    delivered = await dispatcher.dispatch_request("dispatch-1")
    events = store.read_events()

    assert request.status == "pending"
    assert delivered.status == "delivered"
    assert delivered.notified_at is not None
    assert delivered.delivered_at is not None
    assert [event.event_type for event in events] == [
        "dispatch_notified",
        "dispatch_delivered",
    ]
    assert events[-1].dispatch_request_id == "dispatch-1"


async def test_dispatch_request_injection_error_marks_failed_and_appends_event(
    store: TeamStateStore,
) -> None:
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
        )
    )
    bus = AsyncMock()

    async def _submit(envelope):  # type: ignore[no-untyped-def]
        envelope.is_error = True
        envelope.result_text = "injection failed"

    bus.submit.side_effect = _submit
    dispatcher = TeamLiveDispatcher(store, bus)

    failed = await dispatcher.dispatch_request("dispatch-1")
    events = store.read_events()

    assert failed.status == "failed"
    assert failed.failed_at is not None
    assert failed.last_error == "injection failed"
    assert [event.event_type for event in events] == ["dispatch_failed"]
    assert events[0].payload["error"] == "injection failed"


async def test_deliver_mailbox_message_marks_notified_and_appends_event(
    store: TeamStateStore,
) -> None:
    store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-2",
            from_worker="worker-1",
            subject="Need verification",
            body="Please verify the latest patch.",
        )
    )
    bus = AsyncMock()
    dispatcher = TeamLiveDispatcher(store, bus)

    notified = await dispatcher.deliver_mailbox_message("msg-1")
    events = store.read_events()

    assert notified.status == "notified"
    assert notified.notified_at is not None
    assert notified.delivered_at is None
    assert [event.event_type for event in events] == ["mailbox_message_notified"]
