from __future__ import annotations

from pathlib import Path

from controlmesh.multiagent.plan_review_loop import host_job_tail_text
from controlmesh.runtime import HostJob, HostJobRunner, HostJobStep
from types import SimpleNamespace


def test_host_job_tail_returns_bounded_lines(tmp_path: Path) -> None:
    runner = HostJobRunner(
        SimpleNamespace(
            runtime_host_jobs_path=tmp_path / "runtime" / "host_jobs.json",
            runtime_host_jobs_dir=tmp_path / "runtime" / "host-jobs-state",
            runtime_host_job_artifacts_dir=tmp_path / "runtime" / "host-jobs",
        )
    )
    job = HostJob(
        job_id="release-v0.29.0",
        job_kind="release",
        state="running",
        current_step_id="pytest_full",
        steps=[HostJobStep(id="pytest_full", title="pytest", command="uv run pytest -q", state="running")],
    )
    runner.store.put(job)
    stdout_path = runner.store.stdout_path(job.job_id, "pytest_full")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path.write_text("\n".join(f"line {i}" for i in range(120)), encoding="utf-8")
    job.steps[0].stdout_path = str(stdout_path)
    runner.store.put(job)
    orch = SimpleNamespace(host_job_runner=runner)

    text = host_job_tail_text(orch, "release-v0.29.0", lines=20)
    assert "stdout tail" in text
    assert "line 119" in text
    assert "line 0" not in text
