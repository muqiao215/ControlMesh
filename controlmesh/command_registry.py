"""Shared ControlMesh command ownership registry.

This module is the single truth source for:
- command ownership
- transport/orchestrator classification
- visible popup command menus
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandTarget(StrEnum):
    """Dispatch targets for owned slash commands."""

    DIRECT = "direct"
    ORCHESTRATOR = "orchestrator"
    MULTIAGENT = "multiagent"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One owned slash command."""

    name: str
    target: CommandTarget
    visible: bool = False
    main_agent_only: bool = False
    reserved: bool = True
    accepts_args: bool = False


_COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("new", CommandTarget.DIRECT, visible=True, accepts_args=True),
    CommandSpec("model", CommandTarget.ORCHESTRATOR, visible=True, accepts_args=True),
    CommandSpec("cm", CommandTarget.ORCHESTRATOR, visible=True, accepts_args=True),
    CommandSpec("tasks", CommandTarget.ORCHESTRATOR, visible=True),
    CommandSpec("session", CommandTarget.DIRECT, visible=True),
    CommandSpec("agents", CommandTarget.MULTIAGENT, visible=True, main_agent_only=True),
    CommandSpec("cron", CommandTarget.ORCHESTRATOR, visible=True),
    CommandSpec("status", CommandTarget.ORCHESTRATOR, visible=True),
    CommandSpec("memory", CommandTarget.ORCHESTRATOR, visible=True),
    CommandSpec("settings", CommandTarget.ORCHESTRATOR, visible=True, accepts_args=True),
    CommandSpec("stop", CommandTarget.DIRECT, visible=True),
    CommandSpec("interrupt", CommandTarget.DIRECT, visible=True),
    CommandSpec("help", CommandTarget.DIRECT, visible=True),
    CommandSpec("start", CommandTarget.DIRECT),
    CommandSpec("info", CommandTarget.DIRECT),
    CommandSpec("showfiles", CommandTarget.DIRECT),
    CommandSpec("restart", CommandTarget.DIRECT),
    CommandSpec("stop_all", CommandTarget.DIRECT, main_agent_only=True),
    CommandSpec("agent_commands", CommandTarget.DIRECT, main_agent_only=True),
    CommandSpec("back", CommandTarget.ORCHESTRATOR),
    CommandSpec("history", CommandTarget.ORCHESTRATOR, accepts_args=True),
    CommandSpec("diagnose", CommandTarget.ORCHESTRATOR),
    CommandSpec("upgrade", CommandTarget.ORCHESTRATOR),
    CommandSpec("sessions", CommandTarget.ORCHESTRATOR),
    CommandSpec("agent_start", CommandTarget.MULTIAGENT, main_agent_only=True, accepts_args=True),
    CommandSpec("agent_stop", CommandTarget.MULTIAGENT, main_agent_only=True, accepts_args=True),
    CommandSpec(
        "agent_restart",
        CommandTarget.MULTIAGENT,
        main_agent_only=True,
        accepts_args=True,
    ),
)

COMMAND_SPECS: dict[str, CommandSpec] = {spec.name: spec for spec in _COMMAND_SPECS}


def normalize_command_name(text_or_cmd: str) -> str:
    """Return the normalized slash-command name without prefix, mention, or args."""
    token = text_or_cmd.strip().split(maxsplit=1)[0] if text_or_cmd.strip() else ""
    token = token.lstrip("/!")
    token = token.split("@", 1)[0]
    return token.lower()


def get_command_spec(text_or_cmd: str) -> CommandSpec | None:
    """Return the owned command spec for a raw command string or command name."""
    return COMMAND_SPECS.get(normalize_command_name(text_or_cmd))


def is_controlmesh_owned_command(text_or_cmd: str) -> bool:
    """Return True when the command is owned by ControlMesh."""
    return get_command_spec(text_or_cmd) is not None


def is_command_available_for_agent(text_or_cmd: str, *, agent_name: str = "main") -> bool:
    """Return True when the command is owned and allowed for the current agent."""
    spec = get_command_spec(text_or_cmd)
    if spec is None:
        return False
    return not (spec.main_agent_only and agent_name != "main")


def classify_command(text_or_cmd: str) -> str:
    """Classify a command as direct/orchestrator/multiagent/unknown."""
    spec = get_command_spec(text_or_cmd)
    if spec is None:
        return "unknown"
    return spec.target.value


def get_reserved_commands() -> frozenset[str]:
    """Return all reserved ControlMesh slash-command names."""
    return frozenset(spec.name for spec in _COMMAND_SPECS if spec.reserved)


def get_command_names(
    *,
    agent_name: str = "main",
    targets: frozenset[CommandTarget] | None = None,
    visible_only: bool = False,
) -> list[str]:
    """Return command names filtered by visibility, target, and agent scope."""
    names: list[str] = []
    for spec in _COMMAND_SPECS:
        if visible_only and not spec.visible:
            continue
        if spec.main_agent_only and agent_name != "main":
            continue
        if targets is not None and spec.target not in targets:
            continue
        names.append(spec.name)
    return names


def get_visible_commands(*, agent_name: str = "main") -> list[str]:
    """Return popup-visible command names for one agent."""
    return get_command_names(agent_name=agent_name, visible_only=True)
