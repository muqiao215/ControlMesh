"""Focused Stage 6 tests for deferred-topology contract hardening."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from controlmesh.team.models import (
    TeamDirectorDecision,
    TeamJudgeDecision,
    TeamStructuredResult,
    TeamTopologyCheckpoint,
    TeamTopologyExecutionState,
    TeamTopologyProgressSummary,
)


def _checkpoint_kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "checkpoint_id": "cp-1",
        "topology": "director_worker",
        "substage": "director_deciding",
        "phase_status": "in_progress",
        "active_roles": ["director"],
        "completed_roles": ["worker-a"],
        "round_index": 2,
        "round_limit": 3,
    }
    payload.update(overrides)
    return payload


def _progress_kwargs(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "topology": "debate_judge",
        "substage": "judging",
        "phase_status": "in_progress",
        "active_roles": ["judge"],
        "completed_roles": ["candidate_a", "candidate_b"],
        "round_index": 2,
        "round_limit": 3,
    }
    payload.update(overrides)
    return payload


def test_round_metadata_projects_from_checkpoint_to_progress_summary() -> None:
    state = TeamTopologyExecutionState(
        task_id="task-1",
        execution_id="exec-1",
        topology="director_worker",
        checkpoints=[
            TeamTopologyCheckpoint(
                **_checkpoint_kwargs(),
                latest_summary="Director is deciding whether to dispatch another round.",
            )
        ],
    )

    assert state.current_checkpoint.round_index == 2
    assert state.current_checkpoint.round_limit == 3
    assert state.progress_summary.round_index == 2
    assert state.progress_summary.round_limit == 3


@pytest.mark.parametrize(
    ("factory", "match", "override"),
    [
        pytest.param(_checkpoint_kwargs, "round_index must be greater than or equal to 1", {"round_index": 0}, id="checkpoint-round-index-zero"),
        pytest.param(_progress_kwargs, "round_index must be greater than or equal to 1", {"round_index": 0}, id="progress-round-index-zero"),
        pytest.param(_checkpoint_kwargs, "round_limit must be greater than 0", {"round_limit": 0}, id="checkpoint-round-limit-zero"),
        pytest.param(_progress_kwargs, "round_limit must be greater than 0", {"round_limit": 0}, id="progress-round-limit-zero"),
        pytest.param(
            _checkpoint_kwargs,
            "round_index must not exceed round_limit",
            {"round_index": 4, "round_limit": 3},
            id="checkpoint-round-index-exceeds-limit",
        ),
        pytest.param(
            _progress_kwargs,
            "round_index must not exceed round_limit",
            {"round_index": 4, "round_limit": 3},
            id="progress-round-index-exceeds-limit",
        ),
        pytest.param(
            _checkpoint_kwargs,
            "round_index and round_limit must either both be set or both be omitted",
            {"round_limit": None},
            id="checkpoint-missing-round-limit",
        ),
        pytest.param(
            _progress_kwargs,
            "round_index and round_limit must either both be set or both be omitted",
            {"round_index": None},
            id="progress-missing-round-index",
        ),
    ],
)
def test_round_metadata_rejects_invalid_payloads(
    factory: Callable[..., dict[str, object]],
    match: str,
    override: dict[str, object],
) -> None:
    payload = factory(**override)
    model = TeamTopologyCheckpoint if "checkpoint_id" in payload else TeamTopologyProgressSummary

    with pytest.raises(ValidationError, match=match):
        model(**payload)


def test_director_decision_requires_typed_dispatch_roles() -> None:
    with pytest.raises(ValidationError, match="dispatch_roles are required when decision is dispatch_workers"):
        TeamDirectorDecision(
            topology="director_worker",
            round_index=1,
            decision="dispatch_workers",
            summary="Dispatch worker-a and worker-b for another pass.",
        )

    decision = TeamDirectorDecision(
        topology="director_worker",
        round_index=1,
        decision="dispatch_workers",
        dispatch_roles=["worker-a", "worker-b"],
        summary="Dispatch another worker batch.",
    )

    assert decision.dispatch_roles == ["worker-a", "worker-b"]


@pytest.mark.parametrize(
    ("topology", "substage", "status", "match"),
    [
        (
            "director_worker",
            "director_deciding",
            "completed",
            "must use substage 'collecting'",
        ),
        (
            "debate_judge",
            "judging",
            "completed",
            "must use substage 'collecting'",
        ),
        (
            "director_worker",
            "collecting",
            "blocked",
            "must use status completed, failed, or needs_repair",
        ),
        (
            "debate_judge",
            "collecting",
            "blocked",
            "must use status completed, failed, or needs_repair",
        ),
    ],
)
def test_deferred_topology_structured_results_reject_invalid_collection_contracts(
    topology: str,
    substage: str,
    status: str,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        TeamStructuredResult(
            status=status,
            topology=topology,
            substage=substage,
            worker_role="worker-a",
            summary="Invalid deferred-topology worker envelope.",
        )


def test_judge_decision_requires_typed_outcome_fields() -> None:
    with pytest.raises(ValidationError, match="winner_role is required when decision is select_winner"):
        TeamJudgeDecision(
            topology="debate_judge",
            round_index=1,
            decision="select_winner",
            summary="Candidate A wins.",
        )

    with pytest.raises(ValidationError, match="next_candidate_roles are required when decision is advance_round"):
        TeamJudgeDecision(
            topology="debate_judge",
            round_index=1,
            decision="advance_round",
            summary="Run another round between the same candidates.",
        )


def test_judge_decision_rejects_final_round_tie_auto_resolution() -> None:
    with pytest.raises(ValidationError, match="final_round_tie requires decision needs_parent_input"):
        TeamJudgeDecision(
            topology="debate_judge",
            round_index=2,
            decision="failed",
            summary="The debate ended in a tie.",
            stop_reason="final_round_tie",
        )

    decision = TeamJudgeDecision(
        topology="debate_judge",
        round_index=2,
        decision="needs_parent_input",
        summary="The final round remained tied and needs a parent choice.",
        stop_reason="final_round_tie",
    )

    assert decision.stop_reason == "final_round_tie"


@pytest.mark.parametrize(
    ("topology", "role"),
    [
        ("director_worker", "worker-a"),
        ("debate_judge", "candidate_a"),
    ],
)
def test_deferred_topology_structured_results_reject_direct_parent_input(
    topology: str,
    role: str,
) -> None:
    with pytest.raises(ValidationError, match="cannot request parent input through TeamStructuredResult"):
        TeamStructuredResult(
            status="needs_parent_input",
            topology=topology,
            substage="collecting",
            worker_role=role,
            summary="I need the parent to choose the next step.",
            needs_parent_input=True,
        )
