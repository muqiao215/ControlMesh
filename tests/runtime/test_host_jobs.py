from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from controlmesh.runtime import HostJob, HostJobRunner, HostJobSpec, HostJobStep
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=tmp_path / "repo",
    )


def _job(*, state: str = "pending") -> HostJob:
    return HostJob(
        job_id="release-v0.29.0",
        plan_id="release-plan",
        repo="/repo",
        version="0.29.0",
        tag="v0.29.0",
        state=state,  # type: ignore[arg-type]
        steps=[
            HostJobStep(id="pytest_full", title="pytest", command="uv run pytest -q", state="completed"),
            HostJobStep(id="push_main", title="push", command="git push origin main", state="pending", approval_required=True),
        ],
    )


async def _wait_for_job_state(
    runner: HostJobRunner,
    job_id: str,
    expected: str,
    *,
    max_wait: float = 2.0,
    interval: float = 0.02,
) -> HostJob:
    deadline = asyncio.get_running_loop().time() + max_wait
    while True:
        job = runner.get(job_id)
        assert job is not None
        if job.state == expected:
            return job
        if asyncio.get_running_loop().time() >= deadline:
            pytest.fail(f"job {job_id} did not reach state {expected!r}; last state was {job.state!r}")
        await asyncio.sleep(interval)


def test_host_job_store_writes_per_job_authority_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = HostJobRunner(paths)
    job = _job()
    runner.store.put(job)

    job_dir = paths.runtime_host_jobs_dir / job.job_id
    assert (job_dir / "HOST_JOB.json").is_file()
    assert (job_dir / "STEPS.json").is_file()
    assert (job_dir / "TOOL_RESULT.json").is_file()

    host_job = json.loads((job_dir / "HOST_JOB.json").read_text(encoding="utf-8"))
    steps = json.loads((job_dir / "STEPS.json").read_text(encoding="utf-8"))
    tool_result = json.loads((job_dir / "TOOL_RESULT.json").read_text(encoding="utf-8"))

    assert host_job["job_id"] == job.job_id
    assert steps["steps"][1]["id"] == "push_main"
    assert tool_result["status"] == "pending"


def test_ensure_job_accepts_generic_spec(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = HostJobRunner(paths)
    spec = HostJobSpec(
        job_id="generic-job",
        job_kind="long_shell",
        repo="/repo",
        summary="Run generic shell",
        steps=[HostJobStep(id="long_shell", title="shell", command="echo ok")],
    )

    job = runner.ensure_job(spec)

    assert job.job_id == "generic-job"
    assert job.job_kind == "long_shell"
    assert job.steps[0].id == "long_shell"


def test_terminal_state_cannot_be_overwritten(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = HostJobRunner(paths)
    job = _job(state="completed")
    job.completed_at = "2026-05-12T00:00:00Z"
    runner.store.put(job)

    stored = runner.get(job.job_id)
    assert stored is not None
    stored.state = "cancelled"  # type: ignore[assignment]
    runner.store.put(stored)

    persisted = runner.get(job.job_id)
    assert persisted is not None
    assert persisted.state == "completed"

    runner._finalize_job(persisted)
    after_finalize = runner.get(job.job_id)
    assert after_finalize is not None
    assert after_finalize.state == "completed"


def test_terminal_step_state_cannot_be_overwritten(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = HostJobRunner(paths)
    job = _job()
    job.steps[1].state = "completed"
    runner.store.put(job)

    stored = runner.get(job.job_id)
    assert stored is not None
    stored.steps[1].state = "running"
    runner.store.put(stored)

    persisted = runner.get(job.job_id)
    assert persisted is not None
    assert persisted.steps[1].state == "completed"


def test_reconcile_is_idempotent(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    runner = HostJobRunner(paths)
    job = _job()
    job.state = "awaiting_approval"
    job.current_step_id = "push_main"
    job.steps[1].state = "awaiting_approval"
    runner.store.put(job)

    first = runner.get(job.job_id)
    second = runner.get(job.job_id)
    assert first is not None
    assert second is not None
    assert first.state == second.state == "awaiting_approval"
    assert first.current_step_id == second.current_step_id == "push_main"


@pytest.mark.asyncio
async def test_host_job_writes_exit_code_and_tool_result(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    runner = HostJobRunner(paths)
    job = HostJob(
        job_id="release-v0.29.0",
        plan_id="release-plan",
        repo=str(repo),
        version="0.29.0",
        tag="v0.29.0",
        steps=[HostJobStep(id="pytest_full", title="pytest", command="exit 0")],
    )
    runner.store.put(job)

    runner.start(job.job_id)
    persisted = await _wait_for_job_state(runner, job.job_id, "completed")
    assert persisted.state == "completed"
    assert persisted.steps[0].exit_code == 0

    tool_result = json.loads(
        (paths.runtime_host_jobs_dir / job.job_id / "TOOL_RESULT.json").read_text(encoding="utf-8")
    )
    assert tool_result["status"] == "completed"
    assert tool_result["exit_code"] == 0


@pytest.mark.asyncio
async def test_completed_job_cannot_become_cancelled(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    runner = HostJobRunner(paths)
    job = HostJob(
        job_id="task-complete",
        plan_id="",
        repo=str(repo),
        steps=[HostJobStep(id="test_execution", title="test", command="exit 0")],
    )
    runner.store.put(job)
    runner.start(job.job_id)
    persisted = await _wait_for_job_state(runner, job.job_id, "completed")
    assert persisted.state == "completed"

    cancelled = await runner.cancel(job.job_id)
    assert cancelled.state == "completed"


@pytest.mark.asyncio
async def test_cancel_kills_process_group(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    marker = tmp_path / "child.pid"
    script = (
        "bash -lc 'sleep 30 & child=$!; echo $child > "
        + str(marker)
        + "; wait'"
    )
    runner = HostJobRunner(paths)
    job = HostJob(
        job_id="task-cancel",
        plan_id="",
        repo=str(repo),
        steps=[HostJobStep(id="long_shell", title="shell", command=script)],
    )
    runner.store.put(job)
    runner.start(job.job_id)
    await asyncio.sleep(0.3)

    cancelled = await runner.cancel(job.job_id)
    assert cancelled.state == "cancelled"
    child_pid = int(marker.read_text(encoding="utf-8").strip())
    await asyncio.sleep(0.1)
    with pytest.raises(OSError, match=r"\[Errno \d+\]"):  # ESRCH: no such process
        os.kill(child_pid, 0)


@pytest.mark.asyncio
async def test_reconcile_running_job_after_supervisor_restart(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    first = HostJobRunner(paths)
    job = HostJob(
        job_id="task-deadbeef",
        job_kind="test_execution",
        source_task_id="deadbeef",
        plan_id="",
        repo=str(repo),
        version="",
        tag="",
        steps=[HostJobStep(id="test_execution", title="pytest", command="sleep 0.2")],
    )
    first.store.put(job)
    first.start(job.job_id)
    await asyncio.sleep(0.05)
    await first.shutdown()

    second = HostJobRunner(paths)
    persisted = second.get(job.job_id)
    assert persisted is not None
    assert persisted.current_step_id == "test_execution"
    assert persisted.steps[0].state == "running"


@pytest.mark.asyncio
async def test_reconcile_completed_job_after_supervisor_restart(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    first = HostJobRunner(paths)
    job = HostJob(
        job_id="task-cafebabe",
        job_kind="test_execution",
        source_task_id="cafebabe",
        plan_id="",
        repo=str(repo),
        version="",
        tag="",
        steps=[HostJobStep(id="test_execution", title="pytest", command="exit 0")],
    )
    first.store.put(job)
    first.start(job.job_id)
    await asyncio.sleep(0.2)

    second = HostJobRunner(paths)
    persisted = second.get(job.job_id)
    assert persisted is not None
    assert persisted.state == "completed"
    assert persisted.steps[0].exit_code == 0
