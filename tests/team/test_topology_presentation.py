"""Focused Step 5 tests for topology progress presentation."""

from __future__ import annotations

from controlmesh.team.models import TeamTopologyProgressSummary
from controlmesh.team.presentation import render_topology_progress_lines


def test_render_topology_progress_lines_renders_waiting_and_roles() -> None:
    summary = TeamTopologyProgressSummary(
        topology="pipeline",
        substage="waiting_parent",
        phase_status="blocked",
        active_roles=["reviewer"],
        completed_roles=["planner", "worker"],
        waiting_on="parent approval on the candidate patch",
        latest_summary="Waiting on parent confirmation before finalizing the review pass.",
        artifact_count=1,
        needs_parent_input=True,
    )

    lines = render_topology_progress_lines(summary)

    assert lines[0] == "topology: pipeline · waiting_parent · blocked"
    assert "active: reviewer" in lines[1]
    assert "done: planner, worker" in lines[1]
    assert "artifacts: 1" in lines[1]
    assert "waiting: parent approval on the candidate patch" in lines[2]
    assert lines[3].startswith("summary: Waiting on parent confirmation")


def test_render_topology_progress_lines_compresses_long_summary_and_repair_state() -> None:
    summary = TeamTopologyProgressSummary(
        topology="fanout_merge",
        substage="repairing",
        phase_status="in_progress",
        active_roles=["reducer"],
        completed_roles=["coordinator", "worker-a", "worker-c"],
        latest_summary=(
            "Reducer is rebuilding the merged answer after a partial fanout failure and must keep "
            "the task surface compact for the parent-facing progress renderer."
        ),
        repair_state=(
            "Repair the merged answer by removing the unsupported claim, re-grounding the evidence, "
            "and keeping the final checkpoint bounded."
        ),
    )

    lines = render_topology_progress_lines(summary)

    assert lines[0] == "topology: fanout_merge · repairing · in_progress"
    assert "repair: Repair the merged answer" in lines[2]
    assert lines[2].endswith("...")
    assert lines[3].startswith("summary: Reducer is rebuilding the merged answer")
    assert lines[3].endswith("...")


def test_render_topology_progress_lines_renders_round_metadata_compactly() -> None:
    summary = TeamTopologyProgressSummary(
        topology="debate_judge",
        substage="judging",
        phase_status="in_progress",
        active_roles=["judge"],
        completed_roles=["candidate-a", "candidate-b"],
        latest_summary="Judge is comparing the candidate envelopes for the current round.",
        round_index=2,
        round_limit=3,
    )

    lines = render_topology_progress_lines(summary)

    assert lines[0] == "topology: debate_judge · judging · in_progress · round 2/3"
    assert "active: judge" in lines[1]
    assert "done: candidate-a, candidate-b" in lines[1]
