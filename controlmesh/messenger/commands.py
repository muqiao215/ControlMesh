"""Shared command classification for messenger transports.

Defines which commands are handled directly by the transport (DIRECT)
and which are routed to the orchestrator (ORCHESTRATOR).
"""

from __future__ import annotations

from controlmesh.command_registry import COMMAND_SPECS, CommandTarget, classify_command

# Compatibility exports derived from the shared command ownership registry.
DIRECT_COMMANDS: frozenset[str] = frozenset(
    name for name, spec in COMMAND_SPECS.items() if spec.target is CommandTarget.DIRECT
)

ORCHESTRATOR_COMMANDS: frozenset[str] = frozenset(
    name for name, spec in COMMAND_SPECS.items() if spec.target is CommandTarget.ORCHESTRATOR
)

MULTIAGENT_COMMANDS: frozenset[str] = frozenset(
    name for name, spec in COMMAND_SPECS.items() if spec.target is CommandTarget.MULTIAGENT
)
