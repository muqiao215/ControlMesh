"""Focused Stage 7A tests for director_worker topology runtime behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.execution import TeamDirectorWorkerRuntime, TeamTopologyExecutionSpine
from controlmesh.team.models import (
    TeamArtifactRef,
    TeamDirectorDecision,
    TeamEvidenceRef,
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


def _submit(name: str = "Director Worker Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute a director_worker task",
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


def _long_summary(prefix: str) -> str:
    return (
        f"{prefix} "
        "This summary is intentionally long so the director runtime must compress it before "
        "projecting it into topology progress while keeping the typed result boundaries intact."
    )


def _worker_result(
    *,
    role: str,
    status: str,
    summary: str,
    next_action: str | None = None,
    repair_hint: str | None = None,
    evidence_suffix: str = "main",
    artifacts: int = 1,
) -> TeamStructuredResult:
    return TeamStructuredResult(
        status=status,
        topology="director_worker",
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
                ref=f"artifacts/{role}-{index}.md",
                label=f"{role}-{index}",
            )
            for index in range(artifacts)
        ],
        next_action=next_action,
        repair_hint=repair_hint,
    )


def _director_decision(
    *,
    round_index: int,
    decision: str,
    summary: str,
    dispatch_roles: list[str] | None = None,
    next_action: str | None = None,
    repair_hint: str | None = None,
    stop_reason: str | None = None,
    include_supporting_refs: bool = True,
) -> TeamDirectorDecision:
    return TeamDirectorDecision(
        topology="director_worker",
        round_index=round_index,
        decision=decision,
        dispatch_roles=list(dispatch_roles or []),
        summary=summary,
        evidence=(
            [TeamEvidenceRef(ref=f"event-director-{decision}", summary=f"director {decision}")]
            if include_supporting_refs
            else []
        ),
        artifacts=(
            [TeamArtifactRef(ref=f"artifacts/director-{decision}.md", label=decision)]
            if include_supporting_refs
            else []
        ),
        next_action=next_action,
        repair_hint=repair_hint,
        stop_reason=stop_reason,
    )


def test_director_worker_runtime_happy_path_supports_early_completion(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=4)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    started = runtime.start(entry.task_id, planning_summary=_long_summary("Director planned the first round."))
    assert started.current_checkpoint.substage == "planning"
    assert started.current_checkpoint.round_index == 1
    assert started.current_checkpoint.round_limit == 3

    dispatching = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a", "worker-b"],
            summary=_long_summary("Director launched the first batch."),
            next_action="Collect both worker answers before deciding.",
        ),
    )
    assert dispatching.current_checkpoint.substage == "dispatching"
    assert dispatching.progress_summary.active_roles == ["worker-a", "worker-b"]
    assert dispatching.progress_summary.round_index == 1

    deciding = runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary=_long_summary("Worker A produced a strong candidate."),
                next_action="Use in the director decision.",
            ),
            _worker_result(
                role="worker-b",
                status="completed",
                summary=_long_summary("Worker B produced corroborating evidence."),
                next_action="Use in the director decision.",
                evidence_suffix="backup",
            ),
        ],
    )
    assert deciding.current_checkpoint.substage == "director_deciding"
    assert deciding.current_checkpoint.round_index == 1
    assert deciding.progress_summary.active_roles == ["director"]
    assert deciding.progress_summary.completed_roles == ["director", "worker-a", "worker-b"]

    completed = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="complete",
            summary=_long_summary("Director completed after the first round."),
            next_action="Deliver the merged answer.",
            include_supporting_refs=False,
        ),
    )

    reduced = completed.current_checkpoint.reduced_result
    assert completed.current_checkpoint.substage == "completed"
    assert completed.current_checkpoint.phase_status == "completed"
    assert reduced is not None
    assert reduced.final_status == "completed"
    assert sorted(e.ref for e in reduced.selected_evidence) == [
        "event-worker-a-main",
        "event-worker-b-backup",
    ]
    assert sorted(a.ref for a in reduced.selected_artifacts) == [
        "artifacts/worker-a-0.md",
        "artifacts/worker-b-0.md",
    ]


def test_director_worker_runtime_supports_second_round_dispatch_path(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Second Round Task"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a", "worker-b"],
            summary="Director launched the first batch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A produced a narrow answer.",
                next_action="Need one more branch.",
            ),
            _worker_result(
                role="worker-b",
                status="failed",
                summary="Worker B failed to gather enough evidence.",
                artifacts=0,
            ),
        ],
    )

    second_round = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=2,
            decision="dispatch_workers",
            dispatch_roles=["worker-c"],
            summary="Director wants one bounded second round.",
            next_action="Run a focused follow-up worker.",
        ),
    )

    assert second_round.current_checkpoint.substage == "dispatching"
    assert second_round.current_checkpoint.round_index == 2
    assert second_round.current_checkpoint.round_limit == 3
    assert second_round.progress_summary.active_roles == ["worker-c"]
    assert second_round.progress_summary.completed_roles == ["director"]


def test_director_worker_runtime_repair_path_reenters_dispatch_from_repairing(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Repair Task"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a"],
            summary="Director launched the first batch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="needs_repair",
                summary="Worker A needs one missing constraint before continuing.",
                repair_hint="Clarify the missing policy branch.",
                next_action="Director should repair the brief.",
            )
        ],
    )

    repairing = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="needs_repair",
            summary="Director accepted the repair request.",
            repair_hint="Clarify the missing policy branch.",
            next_action="Prepare a repaired follow-up batch.",
        ),
    )

    assert repairing.current_checkpoint.substage == "repairing"
    assert repairing.current_checkpoint.round_index == 1
    assert repairing.current_checkpoint.repair_state == "Clarify the missing policy branch."
    assert repairing.progress_summary.active_roles == ["director"]

    redispatch = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=2,
            decision="dispatch_workers",
            dispatch_roles=["worker-b"],
            summary="Director relaunched a repaired worker batch.",
        ),
    )

    assert redispatch.current_checkpoint.substage == "dispatching"
    assert redispatch.current_checkpoint.round_index == 2
    assert redispatch.progress_summary.active_roles == ["worker-b"]


def test_director_worker_runtime_round_trips_parent_input_from_repairing(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Ask Parent Task"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(
        TeamTopologyExecutionSpine(hub),
        max_parent_interruptions=2,
    )

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a"],
            summary="Director launched the first batch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="needs_repair",
                summary="Worker A needs parent input routed through the director.",
                repair_hint="Clarify the acceptance policy.",
            )
        ],
    )
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="needs_repair",
            summary="Director is preparing a repair path.",
            repair_hint="Clarify the acceptance policy.",
        ),
    )

    waiting = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="needs_parent_input",
            summary="Director needs one parent decision before repairing.",
            stop_reason="parent_decision_required",
            next_action="Ask the parent to confirm the policy branch.",
        ),
        parent_question="Should the director prefer speed or completeness for the repair?",
        waiting_on="parent policy decision",
    )

    assert waiting.current_checkpoint.substage == "waiting_parent"
    assert waiting.current_checkpoint.round_index == 1
    assert waiting.current_checkpoint.result is None
    assert waiting.interruption.status == "waiting_parent"
    assert waiting.interruption.resume_substage == "repairing"

    resumed = runtime.resume_from_parent(
        entry.task_id,
        parent_input="Prefer completeness for this repair path.",
    )

    assert resumed.current_checkpoint.substage == "repairing"
    assert resumed.current_checkpoint.round_index == 1
    assert resumed.progress_summary.active_roles == ["director"]
    assert resumed.interruption.status == "idle"
    assert resumed.interruption.last_parent_input == "Prefer completeness for this repair path."


def test_director_worker_runtime_budget_exhaustion_closes_the_run(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Budget Task"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(
        TeamTopologyExecutionSpine(hub),
        max_total_worker_dispatches=1,
    )

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a"],
            summary="Director launched the only allowed worker dispatch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A delivered a partial answer.",
                next_action="Director may want a follow-up.",
            )
        ],
    )

    failed = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=2,
            decision="dispatch_workers",
            dispatch_roles=["worker-b"],
            summary="Director asked for a second batch despite the hard dispatch budget.",
        ),
    )

    reduced = failed.current_checkpoint.reduced_result
    assert failed.current_checkpoint.substage == "failed"
    assert failed.current_checkpoint.phase_status == "failed"
    assert reduced is not None
    assert reduced.final_status == "failed"
    assert "budget_exhausted" in reduced.reduced_summary


@pytest.mark.parametrize(
    ("results", "match"),
    [
        pytest.param(
            [
                _worker_result(
                    role="worker-a",
                    status="completed",
                    summary="Worker A returned the only submitted result.",
                ),
            ],
            "expected \\['worker-a', 'worker-b'\\], received \\['worker-a'\\]",
            id="missing-dispatched-role",
        ),
        pytest.param(
            [
                _worker_result(
                    role="worker-a",
                    status="completed",
                    summary="Worker A returned a valid result.",
                ),
                _worker_result(
                    role="worker-c",
                    status="completed",
                    summary="Worker C was never dispatched in this round.",
                ),
            ],
            "expected \\['worker-a', 'worker-b'\\], received \\['worker-a', 'worker-c'\\]",
            id="unexpected-extra-role",
        ),
    ],
)
def test_director_worker_runtime_rejects_collection_role_mismatches(
    tmp_path: Path,
    results: list[TeamStructuredResult],
    match: str,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Collection Mismatch"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a", "worker-b"],
            summary="Director launched the first batch.",
        ),
    )

    with pytest.raises(ValueError, match=match):
        runtime.record_worker_results(entry.task_id, results)


def test_director_worker_runtime_rejects_duplicate_worker_roles_in_one_batch(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Duplicate Worker Batch"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a", "worker-b"],
            summary="Director launched the first batch.",
        ),
    )

    with pytest.raises(ValueError, match="requires unique worker roles per batch"):
        runtime.record_worker_results(
            entry.task_id,
            [
                _worker_result(
                    role="worker-a",
                    status="completed",
                    summary="Worker A returned the first candidate.",
                ),
                _worker_result(
                    role="worker-a",
                    status="failed",
                    summary="Worker A was incorrectly duplicated in the batch.",
                    artifacts=0,
                ),
            ],
        )


def test_director_worker_runtime_rejects_non_dispatch_round_index_drift(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Round Drift"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a"],
            summary="Director launched the first batch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A returned a candidate answer.",
            )
        ],
    )

    with pytest.raises(ValueError, match="must match the current round_index 1"):
        runtime.record_director_decision(
            entry.task_id,
            _director_decision(
                round_index=2,
                decision="complete",
                summary="Director tried to complete with a drifted round index.",
                include_supporting_refs=False,
            ),
        )


def test_director_worker_runtime_parent_interrupt_budget_fails_closed(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Director Parent Budget"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamDirectorWorkerRuntime(
        TeamTopologyExecutionSpine(hub),
        max_parent_interruptions=0,
    )

    runtime.start(entry.task_id, planning_summary="Director planned the run.")
    runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="dispatch_workers",
            dispatch_roles=["worker-a"],
            summary="Director launched the first batch.",
        ),
    )
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A returned a partial answer that still needs a policy choice.",
            )
        ],
    )

    failed = runtime.record_director_decision(
        entry.task_id,
        _director_decision(
            round_index=1,
            decision="needs_parent_input",
            summary="Director attempted a parent interruption after the budget was exhausted.",
            stop_reason="parent_decision_required",
            include_supporting_refs=False,
        ),
        parent_question="Should the director ask the parent anyway?",
        waiting_on="parent policy decision",
    )

    reduced = failed.current_checkpoint.reduced_result
    assert failed.current_checkpoint.substage == "failed"
    assert failed.interruption.status == "idle"
    assert reduced is not None
    assert reduced.final_status == "failed"
    assert "max_parent_interruptions was exceeded" in reduced.reduced_summary
