"""Focused Step 3 tests for pipeline-only topology runtime behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.execution import TeamPipelineRuntime, TeamTopologyExecutionSpine
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


def _submit(name: str = "Pipeline Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute a pipeline task",
        message_id=1,
        thread_id=9,
        parent_agent="main",
        name=name,
    )


def _hub(registry: TaskRegistry, tmp_path: Path) -> TaskHub:
    hub = TaskHub(
        registry,
        MagicMock(workspace=tmp_path),
        cli_service=_make_cli_service(),
        config=_make_config(),
    )
    hub.set_result_handler("main", AsyncMock())
    return hub


def _long_summary(prefix: str) -> str:
    return (
        f"{prefix} "
        "This summary is intentionally long so the pipeline runtime must compress it before "
        "projecting it into topology progress. The detailed explanation should remain in the "
        "structured result, not in the progress summary."
    )


def _worker_result(*, substage: str, status: str, role: str, summary: str, **extra: object) -> TeamStructuredResult:
    return TeamStructuredResult(
        status=status,
        topology="pipeline",
        substage=substage,
        worker_role=role,
        summary=summary,
        evidence=[TeamEvidenceRef(ref=f"event-{role}-{substage}", summary=f"{role} evidence")],
        artifacts=[TeamArtifactRef(ref=f"artifacts/{role}-{substage}.md", label=f"{role}-{substage}")],
        **extra,
    )


def test_pipeline_runtime_happy_path_reduces_review_output_and_compresses_progress(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamPipelineRuntime(TeamTopologyExecutionSpine(hub))

    started = runtime.start(entry.task_id, planning_summary=_long_summary("Planner sequenced the run."))
    assert started.current_checkpoint.substage == "planning"

    worker_running = runtime.dispatch_worker(entry.task_id)
    assert worker_running.current_checkpoint.substage == "worker_running"
    assert worker_running.progress_summary.active_roles == ["worker"]
    assert worker_running.progress_summary.completed_roles == ["planner"]

    worker_result = _worker_result(
        substage="worker_running",
        status="completed",
        role="worker",
        summary=_long_summary("Worker finished the main pass."),
        next_action="Send to reviewer",
    )
    review_running = runtime.record_worker_result(entry.task_id, worker_result)

    assert review_running.current_checkpoint.substage == "review_running"
    assert review_running.current_checkpoint.result == worker_result
    assert review_running.progress_summary.active_roles == ["reviewer"]
    assert review_running.progress_summary.completed_roles == ["planner", "worker"]
    assert review_running.progress_summary.artifact_count == 1
    assert review_running.progress_summary.latest_summary is not None
    assert len(review_running.progress_summary.latest_summary) < len(worker_result.summary)

    review_result = _worker_result(
        substage="review_running",
        status="completed",
        role="reviewer",
        summary=_long_summary("Reviewer accepted the worker pass."),
        next_action="Deliver final result",
    )
    completed = runtime.record_review_result(entry.task_id, review_result)

    assert completed.current_checkpoint.substage == "completed"
    assert completed.current_checkpoint.phase_status == "completed"
    assert completed.current_checkpoint.result == review_result
    assert completed.current_checkpoint.reduced_result is not None
    assert completed.current_checkpoint.reduced_result.final_status == "completed"
    assert completed.current_checkpoint.reduced_result.selected_evidence[0].ref == "event-reviewer-review_running"
    assert completed.progress_summary.completed_roles == ["planner", "worker", "reviewer"]
    assert completed.progress_summary.active_roles == []
    assert completed.progress_summary.latest_summary is not None
    assert len(completed.progress_summary.latest_summary) < len(review_result.summary)


def test_pipeline_runtime_interruption_path_round_trips_waiting_parent_and_resume(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Pipeline Interruption Task"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamPipelineRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Planner sequenced the run.")
    runtime.dispatch_worker(entry.task_id)
    runtime.record_worker_result(
        entry.task_id,
        _worker_result(
            substage="worker_running",
            status="completed",
            role="worker",
            summary="Worker delivered the first draft.",
            next_action="Send to reviewer",
        ),
    )

    review_waiting = runtime.record_review_result(
        entry.task_id,
        _worker_result(
            substage="review_running",
            status="needs_parent_input",
            role="reviewer",
            summary=_long_summary("Reviewer needs a parent decision."),
            needs_parent_input=True,
            next_action="Ask the parent to pick the final direction",
        ),
        parent_question="Approve option A or option B?",
        waiting_on="parent approval",
    )

    assert review_waiting.current_checkpoint.substage == "waiting_parent"
    assert review_waiting.current_checkpoint.result is not None
    assert review_waiting.current_checkpoint.result.status == "needs_parent_input"
    assert review_waiting.interruption.status == "waiting_parent"
    assert review_waiting.interruption.question == "Approve option A or option B?"
    assert review_waiting.progress_summary.needs_parent_input is True
    assert review_waiting.progress_summary.waiting_on == "parent approval"

    resumed = runtime.resume_from_parent(
        entry.task_id,
        parent_input="Choose option A and continue.",
    )

    assert resumed.current_checkpoint.substage == "review_running"
    assert resumed.current_checkpoint.phase_status == "in_progress"
    assert resumed.progress_summary.active_roles == ["reviewer"]
    assert resumed.interruption.status == "idle"
    assert resumed.interruption.last_parent_input == "Choose option A and continue."


def test_pipeline_runtime_repair_path_returns_to_review_before_completion(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Pipeline Repair Task"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    runtime = TeamPipelineRuntime(TeamTopologyExecutionSpine(hub))

    runtime.start(entry.task_id, planning_summary="Planner sequenced the run.")
    runtime.dispatch_worker(entry.task_id)
    runtime.record_worker_result(
        entry.task_id,
        _worker_result(
            substage="worker_running",
            status="completed",
            role="worker",
            summary="Worker delivered the first draft.",
            next_action="Send to reviewer",
        ),
    )

    repairing = runtime.record_review_result(
        entry.task_id,
        _worker_result(
            substage="review_running",
            status="needs_repair",
            role="reviewer",
            summary=_long_summary("Reviewer found one issue that needs repair."),
            repair_hint="Add the missing validation branch.",
            next_action="Send back to worker for repair",
        ),
    )

    assert repairing.current_checkpoint.substage == "repairing"
    assert repairing.current_checkpoint.result is not None
    assert repairing.current_checkpoint.result.status == "needs_repair"
    assert repairing.current_checkpoint.repair_state == "Add the missing validation branch."
    assert repairing.progress_summary.active_roles == ["worker"]
    assert repairing.progress_summary.completed_roles == ["planner"]

    back_to_review = runtime.record_repair_result(
        entry.task_id,
        _worker_result(
            substage="repairing",
            status="completed",
            role="worker",
            summary="Worker repaired the missing validation branch.",
            next_action="Return to reviewer",
        ),
    )

    assert back_to_review.current_checkpoint.substage == "review_running"
    assert back_to_review.current_checkpoint.result is not None
    assert back_to_review.current_checkpoint.result.substage == "repairing"
    assert back_to_review.progress_summary.active_roles == ["reviewer"]
    assert back_to_review.progress_summary.completed_roles == ["planner", "worker"]
