"""Tests for team contracts and data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from controlmesh.session.key import SessionKey
from controlmesh.team.contracts import (
    TEAM_API_OPERATIONS,
    TEAM_API_READ_OPERATIONS,
    TEAM_API_WRITE_OPERATIONS,
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_PHASES,
    TEAM_TASK_STATUSES,
    TEAM_TERMINAL_PHASES,
)
from controlmesh.team.models import (
    TeamLeader,
    TeamManifest,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamWorker,
)


def test_contract_sets_include_expected_values() -> None:
    assert TEAM_API_READ_OPERATIONS == (
        "read-manifest",
        "list-tasks",
        "get-summary",
        "read-snapshot",
        "read-events",
    )
    assert TEAM_API_WRITE_OPERATIONS == ("record-dispatch-result",)
    assert TEAM_API_OPERATIONS == TEAM_API_READ_OPERATIONS + TEAM_API_WRITE_OPERATIONS
    assert TEAM_TASK_STATUSES == (
        "pending",
        "blocked",
        "in_progress",
        "completed",
        "failed",
        "cancelled",
    )
    assert TEAM_DISPATCH_REQUEST_STATUSES == (
        "pending",
        "notified",
        "delivered",
        "failed",
        "cancelled",
    )
    assert TEAM_PHASES == ("plan", "approve", "execute", "verify", "repair")
    assert TEAM_TERMINAL_PHASES == ("complete", "failed", "cancelled")


def test_manifest_rejects_duplicate_worker_names() -> None:
    with pytest.raises(ValidationError, match="worker names must be unique"):
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate implementation",
            leader=TeamLeader(agent_name="main"),
            workers=[
                TeamWorker(name="worker-1", role="executor"),
                TeamWorker(name="worker-1", role="verifier"),
            ],
        )


def test_worker_name_must_match_safe_pattern() -> None:
    with pytest.raises(ValidationError, match="safe team identifier"):
        TeamWorker(name="worker 1", role="executor")


def test_leader_session_identity_composes_with_session_key() -> None:
    leader = TeamLeader(
        agent_name="main",
        session=TeamSessionRef.from_session_key(SessionKey.matrix(chat_id=999)),
    )

    assert leader.session_key == SessionKey.matrix(chat_id=999)
    assert leader.session.storage_key == "mx:999"


def test_manifest_normalizes_legacy_flat_identity_fields() -> None:
    manifest = TeamManifest.model_validate(
        {
            "team_name": "alpha-team",
            "task_description": "Coordinate implementation",
            "leader": {
                "agent_name": "main",
                "session_transport": "tg",
                "session_chat_id": 7,
                "session_topic_id": 12,
            },
            "workers": [
                {
                    "name": "worker-1",
                    "role": "executor",
                    "provider": "codex",
                    "session_id": "sess-1",
                }
            ],
            "cwd": "/repo",
        }
    )

    assert manifest.leader.session_key == SessionKey.telegram(chat_id=7, topic_id=12)
    assert manifest.cwd == "/repo"
    assert manifest.leader.runtime.cwd == "/repo"
    assert manifest.workers[0].runtime.provider_session_id == "sess-1"
    assert manifest.workers[0].session_id == "sess-1"


def test_worker_runtime_ref_exposes_explicit_owner_and_optional_route() -> None:
    worker = TeamWorker(
        name="worker-1",
        role="executor",
        provider="codex",
        runtime=TeamRuntimeContext(
            provider_session_id="sess-1",
            session_name="ia-worker-1",
            routable_session=TeamSessionRef(transport="tg", chat_id=7, topic_id=23),
        ),
    )

    runtime_ref = worker.runtime_ref

    assert runtime_ref.worker == "worker-1"
    assert runtime_ref.role == "executor"
    assert runtime_ref.provider == "codex"
    assert runtime_ref.provider_session_id == "sess-1"
    assert runtime_ref.session_name == "ia-worker-1"
    assert runtime_ref.routable_session is not None
    assert runtime_ref.session_key == SessionKey.telegram(chat_id=7, topic_id=23)


def test_manifest_worker_runtime_ref_raises_for_unknown_worker() -> None:
    manifest = TeamManifest(
        team_name="alpha-team",
        task_description="Coordinate implementation",
        leader=TeamLeader(agent_name="main"),
        workers=[TeamWorker(name="worker-1", role="executor")],
    )

    with pytest.raises(ValueError, match="unknown worker"):
        manifest.worker_runtime_ref("worker-2")
