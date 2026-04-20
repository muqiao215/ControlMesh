"""Bot command definitions shared across layers.

Commands are ordered to foreground ControlMesh orchestration primitives.
Descriptions are kept concise so mobile clients do not truncate them.
"""

from __future__ import annotations

from controlmesh.i18n import t_cmd

# -- Core commands (every agent, shown in Telegram popup) ------------------
# Sorted by typical usage: daily actions → power-user → rare maintenance.


def get_bot_commands() -> list[tuple[str, str]]:
    """Return bot commands with translated descriptions."""
    return [
        # Core ControlMesh workflow
        ("new", t_cmd("bot.new")),
        ("model", t_cmd("bot.model")),
        ("mode", t_cmd("bot.mode")),
        ("cm", t_cmd("bot.cm")),
        ("tasks", t_cmd("bot.tasks")),
        ("session", t_cmd("bot.session")),
        ("agents", t_cmd("multiagent.agents")),
        ("cron", t_cmd("bot.cron")),
        ("status", t_cmd("bot.status")),
        ("memory", t_cmd("bot.memory")),
        # Execution control
        ("stop", t_cmd("bot.stop")),
        ("interrupt", t_cmd("bot.interrupt")),
        # Browse & reference
        ("showfiles", t_cmd("bot.showfiles")),
        ("info", t_cmd("bot.info")),
        ("help", t_cmd("bot.help")),
        # Maintenance (rare)
        ("diagnose", t_cmd("bot.diagnose")),
        ("upgrade", t_cmd("bot.upgrade")),
        ("restart", t_cmd("bot.restart")),
    ]


def get_multiagent_sub_commands() -> list[tuple[str, str]]:
    """Return multi-agent sub-commands with translated descriptions."""
    return [
        ("agents", t_cmd("multiagent.agents")),
        ("agent_start", t_cmd("multiagent.agent_start")),
        ("agent_stop", t_cmd("multiagent.agent_stop")),
        ("agent_restart", t_cmd("multiagent.agent_restart")),
        ("stop_all", t_cmd("multiagent.stop_all")),
    ]


# Backward-compatible module-level aliases.
# These are evaluated at import time, so i18n must be auto-initialized by then.
BOT_COMMANDS: list[tuple[str, str]] = get_bot_commands()
MULTIAGENT_SUB_COMMANDS: list[tuple[str, str]] = get_multiagent_sub_commands()
