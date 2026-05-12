from __future__ import annotations

from controlmesh.tasks.host_execution import classify_host_execution
from controlmesh.tasks.models import TaskEntry


def _entry(*, workunit_kind: str = "", command: str = "") -> TaskEntry:
    return TaskEntry(
        task_id="task-1",
        chat_id=1,
        parent_agent="main",
        name="demo",
        prompt_preview="demo",
        provider="claude",
        model="sonnet",
        status="running",
        workunit_kind=workunit_kind,
        command=command,
    )


def test_long_shell_routes_to_host_job() -> None:
    decision = classify_host_execution(_entry(workunit_kind="long_shell", command="sleep 1"))
    assert decision.route_to_host is True
    assert decision.job_kind == "long_shell"


def test_uv_build_routes_to_host_job() -> None:
    decision = classify_host_execution(_entry(workunit_kind="uv_build", command="uv build"))
    assert decision.route_to_host is True
    assert decision.step_id == "uv_build"


def test_repo_write_routes_to_host_job() -> None:
    decision = classify_host_execution(_entry(workunit_kind="repo_write", command="git commit -m test"))
    assert decision.route_to_host is True
    assert decision.side_effect is True


def test_code_review_does_not_route_to_host_job() -> None:
    decision = classify_host_execution(_entry(workunit_kind="code_review", command=""))
    assert decision.route_to_host is False
