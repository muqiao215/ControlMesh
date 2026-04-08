"""Tests for the read-only team API envelope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ductor_bot.team.api import execute_team_api_operation
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamEvent,
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamTaskClaim,
    TeamWorker,
)
from ductor_bot.team.state import TeamStateStore


def _seed_store(tmp_path: Path) -> TeamStateStore:
    store = TeamStateStore(tmp_path / "team-state", "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate Cut 3-5",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(
                    name="worker-1",
                    role="executor",
                    provider="codex",
                    runtime=TeamRuntimeContext(provider_session_id="codex-sess-1"),
                ),
                TeamWorker(name="worker-2", role="verifier"),
            ],
        )
    )
    store.write_phase(
        TeamPhaseState(
            current_phase="verify",
            active=True,
            current_repair_attempt=1,
            max_repair_attempts=3,
            transitions=[
                {
                    "from_phase": "plan",
                    "to_phase": "approve",
                    "at": datetime.now(UTC).isoformat(),
                    "reason": "approved",
                }
            ],
        )
    )
    store.upsert_task(
        TeamTask(
            task_id="task-1",
            subject="Implement state store",
            status="in_progress",
            owner="worker-1",
            claim=TeamTaskClaim(
                worker="worker-1",
                token="lease-1",
                claimed_at=datetime.now(UTC).isoformat(),
                lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            ),
        )
    )
    store.upsert_task(TeamTask(task_id="task-2", subject="Verify behavior", status="pending"))
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
            status="pending",
        )
    )
    store.create_mailbox_message(
        TeamMailboxMessage(
            message_id="msg-1",
            team_name="alpha-team",
            to_worker="worker-2",
            from_worker="worker-1",
            subject="Need verification",
            body="Please verify the implementation.",
        )
    )
    first = store.append_event(
        TeamEvent(
            event_id="evt-1",
            team_name="alpha-team",
            event_type="task_claimed",
            task_id="task-1",
            worker="worker-1",
        )
    )
    assert first.event_id == "evt-1"
    store.append_event(
        TeamEvent(
            event_id="evt-2",
            team_name="alpha-team",
            event_type="phase_transitioned",
            phase="verify",
            worker="worker-2",
        )
    )
    return store


def test_read_manifest_returns_success_envelope(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    result = execute_team_api_operation(
        "read-manifest",
        {"team_name": "alpha-team"},
        state_root=tmp_path / "team-state",
    )

    assert result["ok"] is True
    assert result["operation"] == "read-manifest"
    assert result["data"]["manifest"]["team_name"] == "alpha-team"
    assert result["data"]["manifest"]["leader"]["session"]["transport"] == "tg"
    assert result["data"]["manifest"]["leader"]["runtime"]["cwd"] == "/repo"
    assert result["data"]["manifest"]["workers"][0]["runtime"]["provider_session_id"] == "codex-sess-1"


def test_list_tasks_supports_status_filter(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    result = execute_team_api_operation(
        "list-tasks",
        {"team_name": "alpha-team", "status": "pending"},
        state_root=tmp_path / "team-state",
    )

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["tasks"][0]["task_id"] == "task-2"


def test_get_summary_aggregates_team_state(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    result = execute_team_api_operation(
        "get-summary",
        {"team_name": "alpha-team"},
        state_root=tmp_path / "team-state",
    )

    summary = result["data"]["summary"]
    assert summary["team_name"] == "alpha-team"
    assert summary["phase"] == "verify"
    assert summary["task_counts"]["in_progress"] == 1
    assert summary["task_counts"]["pending"] == 1
    assert summary["dispatch_counts"]["pending"] == 1
    assert summary["mailbox_counts"]["pending"] == 1
    assert summary["latest_event_id"] == "evt-2"


def test_read_events_filters_after_event_id_and_worker(tmp_path: Path) -> None:
    _seed_store(tmp_path)

    result = execute_team_api_operation(
        "read-events",
        {"team_name": "alpha-team", "after_event_id": "evt-1", "worker": "worker-2"},
        state_root=tmp_path / "team-state",
    )

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["cursor"] == "evt-2"
    assert result["data"]["events"][0]["event_id"] == "evt-2"


def test_unknown_operation_returns_structured_error(tmp_path: Path) -> None:
    result = execute_team_api_operation(
        "write-manifest",
        {"team_name": "alpha-team"},
        state_root=tmp_path / "team-state",
    )

    assert result["ok"] is False
    assert result["operation"] == "unknown"
    assert result["error"]["code"] == "unknown_operation"
