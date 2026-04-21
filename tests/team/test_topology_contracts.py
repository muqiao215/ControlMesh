"""Focused Step 1 tests for topology/result/progress team contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from controlmesh.team.contracts import (
    TEAM_DEBATE_JUDGE_SUBSTAGES,
    TEAM_DIRECTOR_WORKER_SUBSTAGES,
    TEAM_FANOUT_MERGE_SUBSTAGES,
    TEAM_PIPELINE_SUBSTAGES,
    TEAM_PROGRESS_STATUSES,
    TEAM_RESULT_ITEM_KINDS,
    TEAM_RESULT_SCHEMA_VERSION,
    TEAM_RESULT_STATUSES,
    TEAM_TOPOLOGIES,
    TEAM_TOPOLOGY_SUBSTAGES,
)
from controlmesh.team.models import (
    TeamArtifactRef,
    TeamEvidenceRef,
    TeamReducedTopologyResult,
    TeamResultItemRef,
    TeamStructuredResult,
    TeamTopologyProgressSummary,
)


def test_topology_contract_sets_include_deferred_topologies() -> None:
    assert TEAM_TOPOLOGIES == (
        "pipeline",
        "fanout_merge",
        "director_worker",
        "debate_judge",
    )
    assert TEAM_PIPELINE_SUBSTAGES == (
        "planning",
        "worker_running",
        "review_running",
        "completed",
        "failed",
        "waiting_parent",
        "repairing",
    )
    assert TEAM_FANOUT_MERGE_SUBSTAGES == (
        "planning",
        "dispatching",
        "collecting",
        "reducing",
        "completed",
        "failed",
        "waiting_parent",
        "repairing",
    )
    assert TEAM_DIRECTOR_WORKER_SUBSTAGES == (
        "planning",
        "dispatching",
        "collecting",
        "director_deciding",
        "waiting_parent",
        "repairing",
        "completed",
        "failed",
    )
    assert TEAM_DEBATE_JUDGE_SUBSTAGES == (
        "planning",
        "candidate_round",
        "collecting",
        "judging",
        "waiting_parent",
        "repairing",
        "completed",
        "failed",
    )
    assert TEAM_TOPOLOGY_SUBSTAGES["pipeline"] == TEAM_PIPELINE_SUBSTAGES
    assert TEAM_TOPOLOGY_SUBSTAGES["fanout_merge"] == TEAM_FANOUT_MERGE_SUBSTAGES
    assert TEAM_TOPOLOGY_SUBSTAGES["director_worker"] == TEAM_DIRECTOR_WORKER_SUBSTAGES
    assert TEAM_TOPOLOGY_SUBSTAGES["debate_judge"] == TEAM_DEBATE_JUDGE_SUBSTAGES
    assert TEAM_RESULT_SCHEMA_VERSION == 1
    assert TEAM_RESULT_STATUSES == (
        "completed",
        "failed",
        "blocked",
        "needs_parent_input",
        "needs_repair",
    )
    assert TEAM_RESULT_ITEM_KINDS == (
        "message",
        "tool_call",
        "tool_result",
        "interrupt",
        "dispatch",
        "phase_transition",
        "repair_note",
    )
    assert TEAM_PROGRESS_STATUSES == (
        "pending",
        "in_progress",
        "blocked",
        "completed",
        "failed",
    )


def test_structured_result_accepts_pipeline_substage_and_defaults_schema_version() -> None:
    result = TeamStructuredResult(
        status="completed",
        topology="pipeline",
        substage="review_running",
        worker_role="reviewer",
        summary="Review completed with one follow-up note.",
        result_items=[
            TeamResultItemRef(kind="dispatch", ref="dispatch-1"),
            TeamResultItemRef(kind="repair_note", ref="event-2", summary="Captured one follow-up."),
        ],
        evidence=[TeamEvidenceRef(ref="event-2", summary="Review event")],
        artifacts=[TeamArtifactRef(ref="artifacts/report.md", label="review-report")],
        confidence=0.82,
        next_action="promote reduced result",
    )

    assert result.schema_version == TEAM_RESULT_SCHEMA_VERSION
    assert result.topology == "pipeline"
    assert result.substage == "review_running"
    assert result.result_items[1].kind == "repair_note"


def test_schema_versioned_topology_result_models_reject_mismatches() -> None:
    with pytest.raises(ValidationError, match="schema_version must be 1"):
        TeamStructuredResult(
            schema_version=999,
            status="completed",
            topology="pipeline",
            substage="review_running",
            worker_role="reviewer",
            summary="Wrong schema version.",
        )

    with pytest.raises(ValidationError, match="schema_version must be 1"):
        TeamReducedTopologyResult(
            schema_version=999,
            topology="fanout_merge",
            final_status="completed",
            reduced_summary="Wrong schema version.",
        )

    with pytest.raises(ValidationError, match="schema_version must be 1"):
        TeamTopologyProgressSummary(
            schema_version=999,
            topology="pipeline",
            substage="planning",
            phase_status="pending",
        )


def test_structured_result_rejects_sdk_colored_item_names() -> None:
    with pytest.raises(ValidationError, match="kind must be one of"):
        TeamResultItemRef(kind="handoff_note", ref="event-1")


@pytest.mark.parametrize(
    ("topology", "substage"),
    [
        ("pipeline", "reducing"),
        ("fanout_merge", "director_deciding"),
        ("director_worker", "candidate_round"),
        ("debate_judge", "worker_running"),
    ],
)
def test_structured_result_rejects_substage_from_other_topology(
    topology: str,
    substage: str,
) -> None:
    with pytest.raises(ValidationError, match=rf"for topology '{topology}'"):
        TeamStructuredResult(
            status="completed",
            topology=topology,
            substage=substage,
            worker_role="reviewer",
            summary="This should fail because the substage belongs to another topology.",
        )


def test_structured_result_requires_parent_input_status_consistency() -> None:
    with pytest.raises(ValidationError, match="status must be needs_parent_input"):
        TeamStructuredResult(
            status="blocked",
            topology="fanout_merge",
            substage="waiting_parent",
            worker_role="reducer",
            summary="Need the parent to choose a candidate.",
            needs_parent_input=True,
        )


def test_structured_result_requires_repair_hint_for_needs_repair() -> None:
    with pytest.raises(ValidationError, match="repair_hint is required"):
        TeamStructuredResult(
            status="needs_repair",
            topology="fanout_merge",
            substage="repairing",
            worker_role="reducer",
            summary="Repair is required before reduction can continue.",
        )


def test_reduced_topology_result_exposes_reduced_boundary() -> None:
    reduced = TeamReducedTopologyResult(
        topology="fanout_merge",
        final_status="completed",
        reduced_summary="Merged three candidate reports into one concise recommendation.",
        selected_evidence=[TeamEvidenceRef(ref="event-3", kind="event")],
        selected_artifacts=[TeamArtifactRef(ref="artifacts/final.md", kind="file")],
        next_action="deliver summary",
    )

    assert reduced.schema_version == TEAM_RESULT_SCHEMA_VERSION
    assert reduced.final_status == "completed"
    assert reduced.selected_artifacts[0].ref == "artifacts/final.md"


def test_progress_summary_validates_parent_waiting_boundary() -> None:
    summary = TeamTopologyProgressSummary(
        topology="fanout_merge",
        substage="collecting",
        phase_status="in_progress",
        active_roles=["worker-1", "worker-2"],
        completed_roles=["planner"],
        latest_summary="Two workers finished; one still collecting evidence.",
        artifact_count=2,
    )

    assert summary.schema_version == TEAM_RESULT_SCHEMA_VERSION
    assert summary.substage == "collecting"
    assert summary.artifact_count == 2

    with pytest.raises(ValidationError, match="waiting_on is required"):
        TeamTopologyProgressSummary(
            topology="pipeline",
            substage="waiting_parent",
            phase_status="blocked",
            active_roles=["reviewer"],
            completed_roles=["planner", "worker"],
            latest_summary="Waiting on parent decision.",
            needs_parent_input=True,
        )
