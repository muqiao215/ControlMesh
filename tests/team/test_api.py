"""Tests for the read-only team API envelope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ductor_bot.team.api import execute_team_api_operation
from ductor_bot.team.models import (
    TeamDispatchRequest,
    TeamDispatchResult,
    TeamEvent,
    TeamLeader,
    TeamMailboxMessage,
    TeamManifest,
    TeamPhaseState,
    TeamPhaseTransition,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamTaskClaim,
    TeamWorker,
)
from ductor_bot.team.state import TeamStateStore
from ductor_bot.workspace.paths import DuctorPaths


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
                    runtime=TeamRuntimeContext(
                        provider_session_id="codex-sess-1",
                        session_name="ia-worker-1",
                        routable_session=TeamSessionRef(transport="tg", chat_id=9, topic_id=3),
                    ),
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
                TeamPhaseTransition(
                    from_phase="plan",
                    to_phase="approve",
                    at=datetime.now(UTC).isoformat(),
                    reason="approved",
                )
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
    assert result["data"]["manifest"]["workers"][0]["runtime"]["session_name"] == "ia-worker-1"
    assert result["data"]["manifest"]["workers"][0]["runtime"]["routable_session"] == {
        "transport": "tg",
        "chat_id": 9,
        "topic_id": 3,
    }


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
    assert summary["worker_runtimes"][0]["worker"] == "worker-1"
    assert summary["worker_runtimes"][0]["provider_session_id"] == "codex-sess-1"
    assert summary["worker_runtimes"][0]["session_name"] == "ia-worker-1"
    assert summary["worker_runtimes"][0]["routable_session"]["chat_id"] == 9


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


def test_read_only_api_does_not_create_team_dir_for_missing_team(tmp_path: Path) -> None:
    state_root = tmp_path / "team-state"

    result = execute_team_api_operation(
        "read-manifest",
        {"team_name": "missing-team"},
        state_root=state_root,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "not_found"
    assert (state_root / "missing-team").exists() is False


def test_record_dispatch_result_requires_internal_write_access(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    store.transition_dispatch_request(
        "dispatch-1",
        "notified",
        route=("worker_session", "tg:9:3"),
    )
    store.transition_dispatch_request(
        "dispatch-1",
        "delivered",
        route=("worker_session", "tg:9:3"),
    )

    result = execute_team_api_operation(
        "record-dispatch-result",
        {
            "team_name": "alpha-team",
            "request_id": "dispatch-1",
            "result": {"outcome": "completed", "reported_by": "worker-1"},
        },
        state_root=tmp_path / "team-state",
    )

    assert result["ok"] is False
    assert result["operation"] == "record-dispatch-result"
    assert result["error"]["code"] == "operation_not_allowed"


def test_record_dispatch_result_updates_dispatch_task_and_events(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    store.transition_dispatch_request(
        "dispatch-1",
        "notified",
        route=("worker_session", "tg:9:3"),
    )
    store.transition_dispatch_request(
        "dispatch-1",
        "delivered",
        route=("worker_session", "tg:9:3"),
    )

    result = execute_team_api_operation(
        "record-dispatch-result",
        {
            "team_name": "alpha-team",
            "request_id": "dispatch-1",
            "result": TeamDispatchResult(
                outcome="completed",
                summary="Implementation landed",
                reported_by="worker-1",
                task_status="completed",
            ).model_dump(mode="json"),
        },
        state_root=tmp_path / "team-state",
        allow_writes=True,
    )

    assert result["ok"] is True
    dispatch_request = result["data"]["dispatch_request"]
    assert dispatch_request["request_id"] == "dispatch-1"
    assert dispatch_request["result"]["outcome"] == "completed"
    assert dispatch_request["result"]["task_status"] == "completed"
    assert dispatch_request["live_route"] == "worker_session"

    task = store.get_task("task-1")
    assert task.status == "completed"

    new_events = store.read_events(after_event_id="evt-2")
    assert [event.event_type for event in new_events] == [
        "dispatch_result_recorded",
        "task_status_changed",
    ]
    assert new_events[0].payload["outcome"] == "completed"
    assert new_events[1].payload["status"] == "completed"


def test_api_defaults_to_canonical_resolved_team_state_root(tmp_path: Path) -> None:
    paths = DuctorPaths(ductor_home=tmp_path)
    _seed_store(paths.workspace)

    with patch("ductor_bot.team.api.resolve_paths", return_value=paths):
        result = execute_team_api_operation(
            "read-manifest",
            {"team_name": "alpha-team"},
        )

    assert result["ok"] is True
    assert result["data"]["manifest"]["team_name"] == "alpha-team"
