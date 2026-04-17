"""Product-facing task runtime CLI commands."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from controlmesh.config import AgentConfig
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.tasks.task_policy import (
    TASK_RUNTIME_PRIMITIVES,
    TASK_TOOL_DOC_PATH,
    delegation_threshold_text,
)
from controlmesh.workspace.paths import resolve_paths

_console = Console()
_HELP_FLAGS = {"--help", "-h"}
_TASKS_USAGE = """Usage:
  controlmesh tasks list
  controlmesh tasks doctor

Commands:
  list    List background tasks from the local task registry.
  doctor  Show task runtime health, policy, and primitive endpoints.
"""
_TASKS_LIST_USAGE = """Usage:
  controlmesh tasks list

List background tasks from the local task registry.
"""
_TASKS_DOCTOR_USAGE = """Usage:
  controlmesh tasks doctor

Show task runtime health, policy, and primitive endpoints.
"""


def load_config() -> AgentConfig:
    """Import lazily to avoid a cycle with ``controlmesh.__main__``."""
    from controlmesh.__main__ import load_config as _load_config

    return _load_config()


def cmd_tasks(args: Sequence[str]) -> None:
    """Handle `controlmesh tasks ...` commands."""
    action_args = _parse_tasks_command(args)
    if action_args and action_args[0] in _HELP_FLAGS:
        _console.print(_TASKS_USAGE)
        return

    action = action_args[0] if action_args else "list"
    if any(arg in _HELP_FLAGS for arg in action_args[1:]):
        if action == "list":
            _console.print(_TASKS_LIST_USAGE)
            return
        if action == "doctor":
            _console.print(_TASKS_DOCTOR_USAGE)
            return

    if action == "list":
        _cmd_tasks_list()
        return
    if action == "doctor":
        _cmd_tasks_doctor()
        return
    raise SystemExit(1)


def _parse_tasks_command(args: Sequence[str]) -> list[str]:
    if not args:
        return []
    if args[0] == "tasks":
        return list(args[1:])
    if len(args) > 1 and args[1] == "tasks":
        return list(args[2:])
    return list(args)


def _registry_from_config() -> tuple[object, TaskRegistry]:
    config = load_config()
    paths = resolve_paths(controlmesh_home=config.controlmesh_home)
    return config, TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)


def _cmd_tasks_list() -> None:
    _config, registry = _registry_from_config()
    entries = registry.list_all()
    if not entries:
        _console.print("No background tasks.")
        return

    table = Table(title="Background Tasks")
    table.add_column("Task ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Owner")
    table.add_column("Provider")
    table.add_column("Elapsed", justify="right")
    table.add_column("Preview")
    for entry in entries:
        provider = "/".join(part for part in (entry.provider, entry.model) if part) or "-"
        elapsed = f"{entry.elapsed_seconds:.0f}s" if entry.elapsed_seconds else "-"
        table.add_row(
            entry.task_id,
            entry.name,
            entry.status,
            entry.parent_agent,
            provider,
            elapsed,
            entry.prompt_preview,
        )
    _console.print(table)


def _cmd_tasks_doctor() -> None:
    config, registry = _registry_from_config()
    paths = resolve_paths(controlmesh_home=config.controlmesh_home)
    entries = registry.list_all()
    counts = Counter(entry.status for entry in entries)

    _console.print("Task runtime doctor")
    _console.print(f"Tasks enabled: {str(config.tasks.enabled).lower()}")
    _console.print(f"Delegation threshold: {delegation_threshold_text()}")
    _console.print(f"Max parallel per chat: {config.tasks.max_parallel}")
    _console.print(f"Task timeout: {config.tasks.timeout_seconds:.0f}s")
    _console.print(f"Registry path: {paths.tasks_registry_path}")
    _console.print(f"Task folder root: {paths.tasks_dir}")
    _console.print(f"Runtime primitives: {', '.join(TASK_RUNTIME_PRIMITIVES)}")
    _console.print(f"Task tool docs: {TASK_TOOL_DOC_PATH}")
    _console.print(f"Total tasks: {len(entries)}")
    for status in ("running", "waiting", "done", "failed", "cancelled"):
        _console.print(f"  {status}: {counts.get(status, 0)}")
