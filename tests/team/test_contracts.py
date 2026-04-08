"""Tests for team contracts and data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ductor_bot.team.contracts import (
    TEAM_API_OPERATIONS,
    TEAM_DISPATCH_REQUEST_STATUSES,
    TEAM_PHASES,
    TEAM_TASK_STATUSES,
    TEAM_TERMINAL_PHASES,
)
from ductor_bot.team.models import TeamLeader, TeamManifest, TeamWorker


def test_contract_sets_include_expected_values() -> None:
    assert TEAM_API_OPERATIONS == (
        "read-manifest",
        "list-tasks",
        "get-summary",
        "read-events",
    )
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

