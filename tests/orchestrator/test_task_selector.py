"""Tests for task selector topology-aware rendering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from controlmesh.orchestrator.selectors.task_selector import task_selector_start
from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry


def _submit(name: str = "Topology Task") -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="execute the bounded topology task",
        message_id=1,
        thread_id=None,
        parent_agent="main",
        name=name,
    )


def _make_hub(tmp_path: Path) -> TaskHub:
    registry = TaskRegistry(tmp_path / "tasks.json", tmp_path / "tasks")
    return TaskHub(
        registry,
        MagicMock(workspace=tmp_path),
        cli_service=MagicMock(),
        config=MagicMock(enabled=True, max_parallel=5, timeout_seconds=60.0),
    )


def test_task_selector_renders_topology_progress_from_persisted_state(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    entry = hub.registry.create(_submit(), "claude", "opus")
    hub.write_topology_state(
        entry.task_id,
        {
            "task_id": entry.task_id,
            "execution_id": f"{entry.task_id}-exec",
            "topology": "fanout_merge",
            "checkpoints": [
                {
                    "checkpoint_id": "cp_0001",
                    "topology": "fanout_merge",
                    "substage": "reducing",
                    "phase_status": "in_progress",
                    "active_roles": ["reducer"],
                    "completed_roles": ["coordinator", "worker-a", "worker-c"],
                    "latest_summary": "Reducer is merging the partial fanout result.",
                    "artifact_count": 2,
                    "recorded_at": "2026-04-21T00:00:00+00:00",
                }
            ],
            "created_at": "2026-04-21T00:00:00+00:00",
            "updated_at": "2026-04-21T00:00:00+00:00",
        },
    )

    resp = task_selector_start(hub, 42)

    assert "topology: fanout_merge · reducing · in_progress" in resp.text
    assert "active: reducer" in resp.text
    assert "done: coordinator, worker-a, worker-c" in resp.text
    assert "summary: Reducer is merging the partial fanout result." in resp.text


def test_task_selector_renders_round_aware_compact_progress(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    submit = _submit(name="Round Aware Task")
    submit.topology = "director_worker"
    entry = hub.registry.create(submit, "claude", "opus")
    hub.write_topology_state(
        entry.task_id,
        {
            "task_id": entry.task_id,
            "execution_id": f"{entry.task_id}-exec",
            "topology": "director_worker",
            "checkpoints": [
                {
                    "checkpoint_id": "cp_0002",
                    "topology": "director_worker",
                    "substage": "director_deciding",
                    "phase_status": "in_progress",
                    "active_roles": ["director"],
                    "completed_roles": ["worker-a", "worker-b"],
                    "latest_summary": "Director is deciding whether another bounded dispatch round is needed.",
                    "round_index": 2,
                    "round_limit": 3,
                    "recorded_at": "2026-04-21T00:00:00+00:00",
                }
            ],
            "created_at": "2026-04-21T00:00:00+00:00",
            "updated_at": "2026-04-21T00:00:00+00:00",
        },
    )

    resp = task_selector_start(hub, 42)

    assert "topology: director_worker · director_deciding · in_progress · round 2/3" in resp.text
    assert "active: director" in resp.text
    assert "done: worker-a, worker-b" in resp.text


def test_task_selector_skips_invalid_topology_state_payload(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    submit = _submit(name="Broken Topology Task")
    submit.topology = "pipeline"
    entry = hub.registry.create(submit, "claude", "opus")
    hub.write_topology_state(
        entry.task_id,
        {
            "task_id": entry.task_id,
            "execution_id": f"{entry.task_id}-exec",
            "topology": "pipeline",
            "checkpoints": [],
            "created_at": "2026-04-21T00:00:00+00:00",
            "updated_at": "2026-04-21T00:00:00+00:00",
        },
    )

    resp = task_selector_start(hub, 42)

    assert "Broken Topology Task" in resp.text
    assert "topology selection: pipeline" in resp.text


def test_task_selector_renders_selected_topology_without_runtime_checkpoint(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    submit = _submit(name="Selected Topology Task")
    submit.topology = "fanout_merge"
    hub.registry.create(submit, "claude", "opus")

    resp = task_selector_start(hub, 42)

    assert "Selected Topology Task" in resp.text
    assert "topology selection: fanout_merge" in resp.text


def test_task_selector_groups_plan_phases_for_same_plan(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    submit_a = _submit(name="Phase One")
    submit_a.plan_id = "demo-plan"
    submit_a.phase_id = "phase-001"
    submit_a.phase_title = "Audit"
    entry_a = hub.registry.create(submit_a, "claude", "opus")
    hub.registry.update_status(entry_a.task_id, "waiting")

    submit_b = _submit(name="Phase Two")
    submit_b.plan_id = "demo-plan"
    submit_b.phase_id = "phase-002"
    submit_b.phase_title = "Implement"
    entry_b = hub.registry.create(submit_b, "claude", "opus")
    hub.registry.update_status(entry_b.task_id, "waiting")

    resp = task_selector_start(hub, 42)

    assert "Phases for `demo-plan`:" in resp.text
    assert "phase: phase-001: Audit" in resp.text
    assert "phase: phase-002: Implement" in resp.text


def test_task_selector_hides_completed_waiting_residue_from_active_waiting(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    submit = _submit(name="Old Release Residue")
    submit.plan_id = "old-release-plan"
    submit.phase_id = "publish"
    submit.phase_title = "Publish"
    entry = hub.registry.create(submit, "codex", "gpt-5.5")
    hub.registry.update_status(
        entry.task_id,
        "waiting",
        completed_at=123.0,
        result_preview="Released ControlMesh v0.24.33.",
        last_question="",
        tool_result_delivered_at=0.0,
        tool_result_consumed_at=0.0,
    )

    resp = task_selector_start(hub, 42)

    assert "**Waiting for answer**" not in resp.text
    assert "Old Release Residue" in resp.text


def test_task_selector_keeps_parent_input_waiting_visible(tmp_path: Path) -> None:
    hub = _make_hub(tmp_path)
    entry = hub.registry.create(_submit(name="Needs Parent Reply"), "claude", "opus")
    hub.registry.update_status(
        entry.task_id,
        "waiting",
        completed_at=123.0,
        last_question="Which framework?",
        tool_result_delivered_at=124.0,
        tool_result_consumed_at=0.0,
    )

    resp = task_selector_start(hub, 42)

    assert "**Waiting for answer**" in resp.text
    assert "Needs Parent Reply" in resp.text
    assert "Which framework?" in resp.text
