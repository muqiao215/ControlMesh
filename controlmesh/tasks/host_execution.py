"""Central host-execution policy for durable host-side process routing."""

from __future__ import annotations

from dataclasses import dataclass

from controlmesh.tasks.models import TaskEntry

_HOST_EXECUTION_WORKUNITS = frozenset(
    {
        "test_execution",
        "long_shell",
        "release_validation",
        "uv_build",
        "git_write",
        "repo_write",
        "repo_publish",
        "github_release",
        "publish",
        "release_publish",
    }
)
_SIDE_EFFECT_WORKUNITS = frozenset(
    {
        "git_write",
        "repo_write",
        "repo_publish",
        "github_release",
        "publish",
        "release_publish",
    }
)
_LONG_RUNNING_WORKUNITS = frozenset({"test_execution", "long_shell", "release_validation", "uv_build"})


@dataclass(frozen=True, slots=True)
class HostExecutionDecision:
    route_to_host: bool
    job_kind: str = ""
    step_id: str = ""
    step_title: str = ""
    side_effect: bool = False
    reason: str = ""


def classify_host_execution(entry: TaskEntry) -> HostExecutionDecision:
    workunit_kind = str(entry.workunit_kind or "").strip()
    if workunit_kind in _HOST_EXECUTION_WORKUNITS:
        return HostExecutionDecision(
            route_to_host=True,
            job_kind=workunit_kind,
            step_id=_default_step_id(workunit_kind),
            step_title=_default_step_title(workunit_kind),
            side_effect=workunit_kind in _SIDE_EFFECT_WORKUNITS,
            reason=f"workunit={workunit_kind}",
        )

    if _looks_like_host_command(entry.command):
        return HostExecutionDecision(
            route_to_host=True,
            job_kind=workunit_kind or "long_shell",
            step_id=_default_step_id(workunit_kind or "long_shell"),
            step_title=_default_step_title(workunit_kind or "long_shell"),
            side_effect=_looks_like_side_effect_command(entry.command),
            reason="command heuristic",
        )

    return HostExecutionDecision(route_to_host=False)


def is_host_execution_workunit(kind: str) -> bool:
    return str(kind or "").strip() in _HOST_EXECUTION_WORKUNITS


def is_long_running_host_execution(kind: str) -> bool:
    return str(kind or "").strip() in _LONG_RUNNING_WORKUNITS


def _default_step_id(workunit_kind: str) -> str:
    return str(workunit_kind or "host_execution").strip() or "host_execution"


def _default_step_title(workunit_kind: str) -> str:
    labels = {
        "test_execution": "Run test execution",
        "long_shell": "Run long shell command",
        "release_validation": "Run release validation",
        "uv_build": "Build package",
        "git_write": "Run git write command",
        "repo_write": "Run repository write command",
        "repo_publish": "Run repository publish command",
        "github_release": "Run GitHub release command",
        "publish": "Run publish command",
        "release_publish": "Run release publish command",
    }
    return labels.get(workunit_kind, "Run host execution")


def _looks_like_host_command(command: str) -> bool:
    normalized = str(command or "").strip().lower()
    if not normalized:
        return False
    tokens = ("pytest", "uv build", "git push", "gh release create", "twine upload", "uv publish")
    return any(token in normalized for token in tokens)


def _looks_like_side_effect_command(command: str) -> bool:
    normalized = str(command or "").strip().lower()
    if not normalized:
        return False
    tokens = ("git push", "gh release create", "publish", "upload")
    return any(token in normalized for token in tokens)
