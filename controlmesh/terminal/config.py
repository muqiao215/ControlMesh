"""Argument parsing helpers for the local terminal."""

from __future__ import annotations

from collections.abc import Sequence

from controlmesh.config import AgentConfig
from controlmesh.terminal.modes import TerminalMode


def parse_provider(args: Sequence[str], config: AgentConfig) -> str:
    """Resolve terminal provider from CLI args or config."""
    if "--provider" in args:
        idx = list(args).index("--provider")
        if idx + 1 < len(args):
            return args[idx + 1]
    for arg in args:
        if arg.startswith("--provider="):
            return arg.split("=", 1)[1]
    return config.terminal.default_provider or config.provider


def parse_mode(args: Sequence[str], config: AgentConfig) -> TerminalMode:
    """Resolve initial terminal mode from CLI args or config."""
    if "--native" in args:
        return TerminalMode.NATIVE
    if "--enhanced" in args:
        return TerminalMode.ENHANCED
    if "--mode" in args:
        idx = list(args).index("--mode")
        if idx + 1 < len(args):
            return TerminalMode(args[idx + 1])
    for arg in args:
        if arg.startswith("--mode="):
            return TerminalMode(arg.split("=", 1)[1])
    return TerminalMode(config.terminal.default_mode)
