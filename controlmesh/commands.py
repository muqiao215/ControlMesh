"""Bot command definitions shared across layers.

Commands are ordered to foreground ControlMesh orchestration primitives.
Descriptions are kept concise so mobile clients do not truncate them.
"""

from __future__ import annotations

from controlmesh.command_registry import get_visible_commands
from controlmesh.i18n import t_cmd

_COMMAND_DESC_KEYS: dict[str, str] = {
    "new": "bot.new",
    "model": "bot.model",
    "cm": "bot.cm",
    "tasks": "bot.tasks",
    "session": "bot.session",
    "agents": "multiagent.agents",
    "cron": "bot.cron",
    "status": "bot.status",
    "memory": "bot.memory",
    "settings": "bot.settings",
    "stop": "bot.stop",
    "interrupt": "bot.interrupt",
    "help": "bot.help",
    "agent_start": "multiagent.agent_start",
    "agent_stop": "multiagent.agent_stop",
    "agent_restart": "multiagent.agent_restart",
    "stop_all": "multiagent.stop_all",
}


def get_bot_commands(agent_name: str = "main") -> list[tuple[str, str]]:
    """Return bot commands with translated descriptions."""
    return [
        (cmd, t_cmd(_COMMAND_DESC_KEYS[cmd]))
        for cmd in get_visible_commands(agent_name=agent_name)
        if cmd in _COMMAND_DESC_KEYS
    ]


def get_multiagent_sub_commands() -> list[tuple[str, str]]:
    """Return multi-agent sub-commands with translated descriptions."""
    return [
        ("agents", t_cmd(_COMMAND_DESC_KEYS["agents"])),
        ("agent_start", t_cmd(_COMMAND_DESC_KEYS["agent_start"])),
        ("agent_stop", t_cmd(_COMMAND_DESC_KEYS["agent_stop"])),
        ("agent_restart", t_cmd(_COMMAND_DESC_KEYS["agent_restart"])),
        ("stop_all", t_cmd(_COMMAND_DESC_KEYS["stop_all"])),
    ]


# Backward-compatible module-level aliases.
# These are evaluated at import time, so i18n must be auto-initialized by then.
BOT_COMMANDS: list[tuple[str, str]] = get_bot_commands()
MULTIAGENT_SUB_COMMANDS: list[tuple[str, str]] = get_multiagent_sub_commands()
