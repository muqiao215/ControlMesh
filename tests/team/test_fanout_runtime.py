"""Focused Step 4 tests for fanout_merge topology runtime behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.execution import TeamFanoutMergeRuntime, TeamTopologyExecutionSpine
from controlmesh.team.models import TeamArtifactRef, TeamEvidenceRef, TeamStructuredResult


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


def _submit(name: str = "Fanout Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute a fanout task",
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
        "This summary is intentionally long so the fanout runtime must compress it before "
        "projecting it into topology progress. The reducer should still preserve the richer "
        "structured result boundary separately from the compressed checkpoint summary."
    )


def _worker_result(
    *,
    role: str,
    status: str,
    summary: str,
    next_action: str | None = None,
    needs_parent_input: bool = False,
    repair_hint: str | None = None,
    evidence_suffix: str = "main",
    artifacts: int = 1,
) -> TeamStructuredResult:
    return TeamStructuredResult(
        status=status,
        topology="fanout_merge",
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
        needs_parent_input=needs_parent_input,
        repair_hint=repair_hint,
    )


def _reducer_result(
    *,
    status: str,
    summary: str,
    next_action: str | None = None,
    needs_parent_input: bool = False,
    repair_hint: str | None = None,
    include_supporting_refs: bool = True,
) -> TeamStructuredResult:
    return TeamStructuredResult(
        status=status,
        topology="fanout_merge",
        substage="reducing",
        worker_role="reducer",
        summary=summary,
        evidence=(
            [TeamEvidenceRef(ref="event-reducer-final", summary="Reducer evidence")]
            if include_supporting_refs
            else []
        ),
        artifacts=(
            [TeamArtifactRef(ref="artifacts/reduced.md", label="reduced")]
            if include_supporting_refs
            else []
        ),
        next_action=next_action,
        needs_parent_input=needs_parent_input,
        repair_hint=repair_hint,
    )


def test_fanout_runtime_happy_path_dispatches_collects_and_reduces(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=4)
    runtime = TeamFanoutMergeRuntime(TeamTopologyExecutionSpine(hub))

    started = runtime.start(entry.task_id, planning_summary=_long_summary("Coordinator planned the fanout."))
    assert started.current_checkpoint.substage == "planning"

    dispatching = runtime.dispatch_workers(
        entry.task_id,
        worker_roles=["worker-a", "worker-b", "worker-c"],
    )
    assert dispatching.current_checkpoint.substage == "dispatching"
    assert dispatching.progress_summary.active_roles == ["worker-a", "worker-b", "worker-c"]
    assert dispatching.progress_summary.completed_roles == ["coordinator"]

    collecting = runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary=_long_summary("Worker A returned a candidate."),
                next_action="Send to reducer",
            ),
            _worker_result(
                role="worker-b",
                status="completed",
                summary=_long_summary("Worker B returned a candidate."),
                next_action="Send to reducer",
                evidence_suffix="secondary",
            ),
            _worker_result(
                role="worker-c",
                status="completed",
                summary=_long_summary("Worker C returned a candidate."),
                next_action="Send to reducer",
                evidence_suffix="third",
            ),
        ],
    )

    assert collecting.current_checkpoint.substage == "reducing"
    assert collecting.current_checkpoint.result is None
    assert collecting.progress_summary.active_roles == ["reducer"]
    assert collecting.progress_summary.completed_roles == ["coordinator", "worker-a", "worker-b", "worker-c"]
    assert collecting.progress_summary.artifact_count == 3

    completed = runtime.record_reducer_result(
        entry.task_id,
        _reducer_result(
            status="completed",
            summary=_long_summary("Reducer merged the strongest candidate."),
            next_action="Deliver the merged answer",
        ),
    )

    assert completed.current_checkpoint.substage == "completed"
    assert completed.current_checkpoint.phase_status == "completed"
    assert completed.current_checkpoint.result is not None
    assert completed.current_checkpoint.result.worker_role == "reducer"
    assert completed.current_checkpoint.reduced_result is not None
    assert completed.current_checkpoint.reduced_result.final_status == "completed"
    assert completed.current_checkpoint.reduced_result.selected_evidence
    assert completed.current_checkpoint.reduced_result.selected_artifacts[0].ref == "artifacts/reduced.md"
    assert completed.progress_summary.active_roles == []
    assert completed.progress_summary.completed_roles == [
        "coordinator",
        "worker-a",
        "worker-b",
        "worker-c",
        "reducer",
    ]


def test_fanout_runtime_partial_failure_still_reaches_reducer_with_partial_successes(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Fanout Partial Failure"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamFanoutMergeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Coordinator planned the fanout.")
    runtime.dispatch_workers(entry.task_id, worker_roles=["worker-a", "worker-b", "worker-c"])

    reducing = runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A returned a strong candidate.",
                next_action="Send to reducer",
            ),
            _worker_result(
                role="worker-b",
                status="failed",
                summary="Worker B failed while gathering evidence.",
                next_action="Ignore this branch",
                artifacts=0,
            ),
            _worker_result(
                role="worker-c",
                status="completed",
                summary="Worker C returned a backup candidate.",
                next_action="Send to reducer",
                evidence_suffix="backup",
            ),
        ],
    )

    assert reducing.current_checkpoint.substage == "reducing"
    assert reducing.progress_summary.phase_status == "in_progress"
    assert reducing.progress_summary.completed_roles == ["coordinator", "worker-a", "worker-c"]
    assert reducing.progress_summary.latest_summary is not None
    assert "partial" in reducing.progress_summary.latest_summary.lower()
    assert "worker-b" in reducing.progress_summary.latest_summary


def test_fanout_runtime_reducer_uses_partial_successes_when_some_workers_fail(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Fanout Reduce Partial Success"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=3)
    runtime = TeamFanoutMergeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Coordinator planned the fanout.")
    runtime.dispatch_workers(entry.task_id, worker_roles=["worker-a", "worker-b", "worker-c"])
    runtime.record_worker_results(
        entry.task_id,
        [
            _worker_result(
                role="worker-a",
                status="completed",
                summary="Worker A found the primary evidence set.",
                next_action="Use in merge",
                evidence_suffix="primary",
            ),
            _worker_result(
                role="worker-b",
                status="failed",
                summary="Worker B timed out on one branch.",
                next_action="Proceed without this branch",
                artifacts=0,
            ),
            _worker_result(
                role="worker-c",
                status="completed",
                summary="Worker C found corroborating evidence.",
                next_action="Use in merge",
                evidence_suffix="corroborating",
            ),
        ],
    )

    completed = runtime.record_reducer_result(
        entry.task_id,
        _reducer_result(
            status="completed",
            summary="Reducer merged the surviving worker candidates.",
            next_action="Deliver the merged answer",
            include_supporting_refs=False,
        ),
    )

    reduced = completed.current_checkpoint.reduced_result
    assert reduced is not None
    assert reduced.final_status == "completed"
    assert sorted(e.ref for e in reduced.selected_evidence) == [
        "event-worker-a-primary",
        "event-worker-c-corroborating",
    ]
    assert sorted(a.ref for a in reduced.selected_artifacts) == [
        "artifacts/worker-a-0.md",
        "artifacts/worker-c-0.md",
    ]
    assert completed.progress_summary.latest_summary is not None
    assert "2 evidence" in completed.progress_summary.latest_summary


def test_fanout_runtime_rejects_dispatches_beyond_taskhub_parallel_limit(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Fanout Dispatch Cap"), "claude", "opus")
    hub = _hub(registry, tmp_path, max_parallel=2)
    runtime = TeamFanoutMergeRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Coordinator planned the fanout.")

    with pytest.raises(ValueError, match="bounded parallel limit is 2"):
        runtime.dispatch_workers(entry.task_id, worker_roles=["worker-a", "worker-b", "worker-c"])
