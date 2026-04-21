"""Focused Stage 7B tests for debate_judge topology runtime behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.execution import TeamDebateJudgeRuntime, TeamTopologyExecutionSpine
from controlmesh.team.models import (
    TeamArtifactRef,
    TeamEvidenceRef,
    TeamJudgeDecision,
    TeamStructuredResult,
)


def _make_config(**overrides: object) -> MagicMock:
    config = MagicMock()
    config.enabled = True
    config.max_parallel = 5
    config.timeout_seconds = 60.0
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _make_cli_service(result: str = "done", session_id: str = "sess-1") -> MagicMock:
    cli = MagicMock()
    response = MagicMock()
    response.result = result
    response.session_id = session_id
    response.is_error = False
    response.timed_out = False
    response.num_turns = 3
    cli.execute = AsyncMock(return_value=response)
    cli.resolve_provider = MagicMock(return_value=("claude", "opus"))
    return cli


def _submit(name: str = "Debate Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute a debate_judge task",
        message_id=1,
        thread_id=9,
        parent_agent="main",
        name=name,
    )


def _hub(registry: TaskRegistry, tmp_path: Path, *, max_parallel: int = 5) -> TaskHub:
    hub = TaskHub(
        registry,
        MagicMock(workspace=tmp_path),
        cli_service=_make_cli_service(),
        config=_make_config(max_parallel=max_parallel),
    )
    hub.set_result_handler("main", AsyncMock())
    return hub


def _candidate_result(
    *,
    role: str,
    status: str = "completed",
    summary: str,
    confidence: float | None = None,
    next_action: str | None = None,
    repair_hint: str | None = None,
    evidence_suffix: str = "main",
) -> TeamStructuredResult:
    return TeamStructuredResult(
        status=status,
        topology="debate_judge",
        substage="collecting",
        worker_role=role,
        summary=summary,
        evidence=[
            TeamEvidenceRef(
                ref=f"event-{role}-{evidence_suffix}",
                summary=f"{role} evidence {evidence_suffix}",
            )
        ],
        artifacts=[
            TeamArtifactRef(
                ref=f"artifacts/{role}.md",
                label=role,
            )
        ],
        confidence=confidence,
        next_action=next_action,
        repair_hint=repair_hint,
    )


def _judge_decision(
    *,
    round_index: int,
    decision: str,
    summary: str,
    winner_role: str | None = None,
    next_candidate_roles: list[str] | None = None,
    repair_hint: str | None = None,
    stop_reason: str | None = None,
    evidence_suffix: str = "judge",
) -> TeamJudgeDecision:
    return TeamJudgeDecision(
        topology="debate_judge",
        round_index=round_index,
        decision=decision,
        winner_role=winner_role,
        next_candidate_roles=list(next_candidate_roles or []),
        summary=summary,
        evidence=[TeamEvidenceRef(ref=f"event-{evidence_suffix}", summary=f"{evidence_suffix} evidence")],
        artifacts=[TeamArtifactRef(ref=f"artifacts/{evidence_suffix}.md", label=evidence_suffix)],
        repair_hint=repair_hint,
        stop_reason=stop_reason,
    )


def test_debate_judge_runtime_selects_round_one_winner_and_reduces_terminal_result(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    started = runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the first candidate comparison.",
        round_limit=2,
    )
    assert started.current_checkpoint.substage == "planning"
    assert started.current_checkpoint.round_index == 1
    assert started.current_checkpoint.round_limit == 2

    candidate_round = runtime.start_candidate_round(
        entry.task_id,
        candidate_roles=["candidate_a", "candidate_b"],
    )
    assert candidate_round.current_checkpoint.substage == "candidate_round"
    assert candidate_round.progress_summary.active_roles == ["candidate_a", "candidate_b"]

    judging = runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(
                role="candidate_a",
                summary="Candidate A presented the safer rollout plan.",
                confidence=0.61,
                next_action="Judge for operational safety.",
            ),
            _candidate_result(
                role="candidate_b",
                summary="Candidate B presented the faster rollout plan.",
                confidence=0.79,
                next_action="Judge for operational safety.",
                evidence_suffix="backup",
            ),
        ],
    )
    assert judging.current_checkpoint.substage == "judging"
    assert judging.current_checkpoint.round_index == 1
    assert judging.progress_summary.active_roles == ["judge"]

    completed = runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=1,
            decision="select_winner",
            winner_role="candidate_a",
            summary="Candidate A wins because its evidence better addresses rollback safety.",
        ),
    )

    assert completed.current_checkpoint.substage == "completed"
    assert completed.current_checkpoint.phase_status == "completed"
    assert completed.current_checkpoint.round_index == 1
    reduced = completed.current_checkpoint.reduced_result
    assert reduced is not None
    assert reduced.final_status == "completed"
    assert reduced.selected_evidence[0].ref == "event-judge"
    assert reduced.selected_artifacts[0].ref == "artifacts/judge.md"
    assert completed.progress_summary.active_roles == []


def test_debate_judge_runtime_advances_non_final_tie_into_next_round(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Tie Advances"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the first candidate comparison.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A made the reliability case."),
            _candidate_result(
                role="candidate_b",
                summary="Candidate B made the speed case.",
                evidence_suffix="backup",
            ),
        ],
    )

    advanced = runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=1,
            decision="advance_round",
            next_candidate_roles=["candidate_a", "candidate_b"],
            summary="Round one is tied. Narrow the next round to failure recovery tradeoffs.",
        ),
    )

    assert advanced.current_checkpoint.substage == "candidate_round"
    assert advanced.current_checkpoint.phase_status == "in_progress"
    assert advanced.current_checkpoint.round_index == 2
    assert advanced.current_checkpoint.round_limit == 2
    assert advanced.progress_summary.active_roles == ["candidate_a", "candidate_b"]
    assert advanced.progress_summary.latest_summary is not None
    assert "Round one is tied" in advanced.progress_summary.latest_summary


def test_debate_judge_runtime_escalates_final_round_tie_to_parent_input(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Final Tie"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A argued for safety."),
            _candidate_result(role="candidate_b", summary="Candidate B argued for speed."),
        ],
    )
    runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=1,
            decision="advance_round",
            next_candidate_roles=["candidate_a", "candidate_b"],
            summary="The first round is still tied.",
        ),
    )
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(
                role="candidate_a",
                summary="Candidate A added rollback evidence.",
                evidence_suffix="round-two-a",
            ),
            _candidate_result(
                role="candidate_b",
                summary="Candidate B added latency evidence.",
                evidence_suffix="round-two-b",
            ),
        ],
    )

    blocked = runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=2,
            decision="needs_parent_input",
            summary="The final round remains tied on safety versus speed tradeoffs.",
            stop_reason="final_round_tie",
        ),
        parent_question="Choose which tradeoff should win: safety or speed?",
        waiting_on="parent tradeoff decision",
    )

    assert blocked.current_checkpoint.substage == "waiting_parent"
    assert blocked.current_checkpoint.phase_status == "blocked"
    assert blocked.current_checkpoint.round_index == 2
    assert blocked.progress_summary.needs_parent_input is True
    assert blocked.current_checkpoint.reduced_result is None
    assert blocked.interruption.resume_substage == "judging"


def test_debate_judge_runtime_routes_insufficient_evidence_to_repair(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Needs Repair"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(
                role="candidate_a",
                status="needs_repair",
                summary="Candidate A needs more rollout evidence.",
                repair_hint="Add rollback validation.",
            ),
            _candidate_result(
                role="candidate_b",
                status="failed",
                summary="Candidate B could not verify its latency claim.",
            ),
        ],
    )

    repairing = runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=1,
            decision="needs_repair",
            summary="The judge does not have enough evidence to choose a winner yet.",
            repair_hint="Both candidates must add concrete validation evidence.",
        ),
    )

    assert repairing.current_checkpoint.substage == "repairing"
    assert repairing.current_checkpoint.phase_status == "in_progress"
    assert repairing.current_checkpoint.round_index == 1
    assert repairing.current_checkpoint.repair_state == "Both candidates must add concrete validation evidence."
    assert repairing.progress_summary.active_roles == ["candidate_a", "candidate_b"]


def test_debate_judge_runtime_resumes_parent_interruption_back_to_judging(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Resume"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A argued for safety."),
            _candidate_result(role="candidate_b", summary="Candidate B argued for speed."),
        ],
    )
    runtime.record_judge_decision(
        entry.task_id,
        _judge_decision(
            round_index=1,
            decision="needs_parent_input",
            summary="Judge needs a parent call on whether safety or speed matters more.",
            stop_reason="parent_decision_required",
        ),
        parent_question="Which evaluation axis should dominate: safety or speed?",
        waiting_on="parent priority decision",
    )

    resumed = runtime.resume_from_parent(
        entry.task_id,
        parent_input="Prioritize safety over speed.",
        latest_summary="Parent prioritized safety. Judge can now finish the round-one decision.",
    )

    assert resumed.current_checkpoint.substage == "judging"
    assert resumed.current_checkpoint.phase_status == "in_progress"
    assert resumed.current_checkpoint.round_index == 1
    assert resumed.current_checkpoint.round_limit == 2
    assert resumed.progress_summary.active_roles == ["judge"]
    assert resumed.interruption.status == "idle"
    assert resumed.interruption.last_parent_input == "Prioritize safety over speed."


@pytest.mark.parametrize(
    ("candidate_roles", "match"),
    [
        pytest.param(
            ["candidate_a"],
            "requires exactly two candidate roles",
            id="one-candidate",
        ),
        pytest.param(
            ["candidate_a", "candidate_a"],
            "candidate roles must be unique within one debate round",
            id="duplicate-candidates",
        ),
    ],
)
def test_debate_judge_runtime_rejects_invalid_candidate_round_sets(
    tmp_path: Path,
    candidate_roles: list[str],
    match: str,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Invalid Candidate Set"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )

    with pytest.raises(ValueError, match=match):
        runtime.start_candidate_round(entry.task_id, candidate_roles=candidate_roles)


def test_debate_judge_runtime_rejects_duplicate_candidate_results_in_one_round(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Duplicate Candidate Result"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])

    with pytest.raises(ValueError, match="candidate 'candidate_a' was reported more than once"):
        runtime.record_candidate_results(
            entry.task_id,
            [
                _candidate_result(role="candidate_a", summary="Candidate A returned the first answer."),
                _candidate_result(
                    role="candidate_a",
                    summary="Candidate A was incorrectly duplicated in the same round.",
                    evidence_suffix="duplicate",
                ),
            ],
        )


@pytest.mark.parametrize(
    ("results", "match"),
    [
        pytest.param(
            [
                _candidate_result(role="candidate_a", summary="Candidate A returned its answer."),
            ],
            "candidate results must exactly match the active round roles \\(missing: candidate_b\\)",
            id="missing-candidate",
        ),
        pytest.param(
            [
                _candidate_result(role="candidate_a", summary="Candidate A returned its answer."),
                _candidate_result(
                    role="candidate_c",
                    summary="Candidate C was never part of the active round.",
                    evidence_suffix="unexpected",
                ),
            ],
            "candidate results must exactly match the active round roles \\(missing: candidate_b; unexpected: candidate_c\\)",
            id="unexpected-candidate",
        ),
    ],
)
def test_debate_judge_runtime_rejects_candidate_result_role_mismatches(
    tmp_path: Path,
    results: list[TeamStructuredResult],
    match: str,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Candidate Result Mismatch"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])

    with pytest.raises(ValueError, match=match):
        runtime.record_candidate_results(entry.task_id, results)


def test_debate_judge_runtime_rejects_judge_decision_round_index_mismatch(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Round Drift"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A argued for safety."),
            _candidate_result(role="candidate_b", summary="Candidate B argued for speed."),
        ],
    )

    with pytest.raises(ValueError, match="judge decision round_index 2 does not match the current round 1"):
        runtime.record_judge_decision(
            entry.task_id,
            _judge_decision(
                round_index=2,
                decision="select_winner",
                winner_role="candidate_a",
                summary="Judge tried to resolve round one with a drifted round index.",
            ),
        )


def test_debate_judge_runtime_rejects_advancing_after_final_round(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Final Round Advance"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped a single-round debate.",
        round_limit=1,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A argued for safety."),
            _candidate_result(role="candidate_b", summary="Candidate B argued for speed."),
        ],
    )

    with pytest.raises(ValueError, match="final round judge ties must escalate instead of advancing another round"):
        runtime.record_judge_decision(
            entry.task_id,
            _judge_decision(
                round_index=1,
                decision="advance_round",
                next_candidate_roles=["candidate_a", "candidate_b"],
                summary="Judge incorrectly tried to advance past the final round.",
            ),
        )


def test_debate_judge_runtime_rejects_final_round_tie_stop_reason_before_final_round(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Debate Premature Final Tie"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamDebateJudgeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(
        entry.task_id,
        planning_summary="Judge scoped the debate.",
        round_limit=2,
    )
    runtime.start_candidate_round(entry.task_id, candidate_roles=["candidate_a", "candidate_b"])
    runtime.record_candidate_results(
        entry.task_id,
        [
            _candidate_result(role="candidate_a", summary="Candidate A argued for safety."),
            _candidate_result(role="candidate_b", summary="Candidate B argued for speed."),
        ],
    )

    with pytest.raises(ValueError, match="final_round_tie is only valid when the current round is the final round"):
        runtime.record_judge_decision(
            entry.task_id,
            _judge_decision(
                round_index=1,
                decision="needs_parent_input",
                summary="Judge tried to escalate a non-final tie as if it were the final round.",
                stop_reason="final_round_tie",
            ),
            parent_question="Should the judge escalate this early tie?",
            waiting_on="parent tradeoff decision",
        )
