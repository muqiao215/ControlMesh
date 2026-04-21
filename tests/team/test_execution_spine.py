"""Focused Step 2 tests for the TaskHub-backed topology execution seam."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.execution import TeamTopologyExecutionSpine
from controlmesh.team.models import TeamTopologyExecutionState


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


def _submit(name: str = "Topology Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute a topology task",
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


def test_execution_spine_tracks_state_progression_in_taskhub_checkpoint_store(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(), "claude", "opus")
    hub = _hub(registry, tmp_path)
    spine = TeamTopologyExecutionSpine(hub)

    started = spine.start(
        entry.task_id,
        topology="pipeline",
        active_roles=["planner"],
        latest_summary="Planning started.",
    )
    assert started.current_checkpoint.substage == "planning"
    assert started.current_checkpoint.phase_status == "in_progress"
    assert started.progress_summary.active_roles == ["planner"]

    advanced = spine.record_checkpoint(
        entry.task_id,
        substage="worker_running",
        phase_status="in_progress",
        active_roles=["worker"],
        completed_roles=["planner"],
        latest_summary="Planner handed work to the worker.",
    )

    assert advanced.current_checkpoint.substage == "worker_running"
    assert advanced.current_checkpoint.completed_roles == ["planner"]
    assert advanced.progress_summary.latest_summary == "Planner handed work to the worker."

    reloaded = TeamTopologyExecutionSpine(hub).read(entry.task_id)
    assert reloaded is not None
    assert reloaded.current_checkpoint.substage == "worker_running"
    assert len(reloaded.checkpoints) == 2


def test_execution_spine_round_trips_interrupt_and_resume_on_same_task(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Interruptible Topology Task"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    spine = TeamTopologyExecutionSpine(hub)

    spine.start(
        entry.task_id,
        topology="pipeline",
        active_roles=["planner"],
        latest_summary="Planning started.",
    )
    spine.record_checkpoint(
        entry.task_id,
        substage="review_running",
        phase_status="in_progress",
        active_roles=["reviewer"],
        completed_roles=["planner", "worker"],
        latest_summary="Review is waiting for a parent choice.",
    )

    interrupted = spine.interrupt_for_parent(
        entry.task_id,
        requested_by_role="reviewer",
        question="Approve the current candidate?",
        waiting_on="parent approval",
        latest_summary="Waiting for parent approval before the review can finish.",
    )
    assert interrupted.interruption.status == "waiting_parent"
    assert interrupted.current_checkpoint.substage == "waiting_parent"
    assert interrupted.progress_summary.phase_status == "blocked"
    assert interrupted.progress_summary.needs_parent_input is True

    reloaded = TeamTopologyExecutionSpine(hub).read(entry.task_id)
    assert reloaded is not None
    assert reloaded.interruption.question == "Approve the current candidate?"

    resumed = TeamTopologyExecutionSpine(hub).resume_from_parent(
        entry.task_id,
        parent_input="Approved. Continue with the current candidate.",
        latest_summary="Parent approved the current candidate.",
    )

    assert resumed.interruption.status == "idle"
    assert resumed.interruption.resume_count == 1
    assert resumed.interruption.last_parent_input == "Approved. Continue with the current candidate."
    assert resumed.current_checkpoint.substage == "review_running"
    assert resumed.current_checkpoint.phase_status == "in_progress"
    assert resumed.progress_summary.needs_parent_input is False
    assert resumed.progress_summary.latest_summary == "Parent approved the current candidate."


def test_execution_state_schema_version_mismatch_is_rejected_on_direct_validation(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Bad Schema Task"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    spine = TeamTopologyExecutionSpine(hub)

    spine.start(
        entry.task_id,
        topology="pipeline",
        active_roles=["planner"],
        latest_summary="Planning started.",
    )

    payload = hub.read_topology_state(entry.task_id)
    assert payload is not None
    payload["schema_version"] = 999

    with pytest.raises(ValidationError, match="schema_version must be 1"):
        TeamTopologyExecutionState.model_validate(payload)


def test_execution_state_schema_version_mismatch_is_rejected_on_persisted_read(
    tmp_path: Path,
) -> None:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    entry = registry.create(_submit(name="Persisted Bad Schema Task"), "claude", "opus")
    hub = _hub(registry, tmp_path)
    spine = TeamTopologyExecutionSpine(hub)

    spine.start(
        entry.task_id,
        topology="pipeline",
        active_roles=["planner"],
        latest_summary="Planning started.",
    )

    payload = hub.read_topology_state(entry.task_id)
    assert payload is not None
    payload["schema_version"] = 999
    hub.write_topology_state(entry.task_id, payload)

    with pytest.raises(ValidationError, match="schema_version must be 1"):
        TeamTopologyExecutionSpine(hub).read(entry.task_id)
