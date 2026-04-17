"""Product-friendly Feishu native CLI aliases."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console

from controlmesh.cli_commands.auth import cmd_auth

_console = Console()
_HELP_FLAGS = {"--help", "-h"}
_FEISHU_USAGE = """Usage:
  controlmesh feishu native <command>

Commands:
  native    Product-friendly Feishu native aliases.
"""
_FEISHU_NATIVE_USAGE = """Usage:
  controlmesh feishu native bootstrap
  controlmesh feishu native doctor
  controlmesh feishu native probe
  controlmesh feishu native register-begin

Commands:
  bootstrap       Start the Feishu native bootstrap flow.
  doctor          Run Feishu auth/runtime doctor checks.
  probe           Probe current Feishu runtime readiness.
  register-begin  Begin Feishu app registration flow.
"""
_FEISHU_NATIVE_BOOTSTRAP_USAGE = """Usage:
  controlmesh feishu native bootstrap

Start the product-friendly Feishu native bootstrap flow.
"""
_NATIVE_AUTH_COMMANDS = {
    "bootstrap": ["auth", "feishu", "setup"],
    "doctor": ["auth", "feishu", "doctor"],
    "probe": ["auth", "feishu", "probe"],
    "register-begin": ["auth", "feishu", "register-begin"],
}
_NATIVE_COMMAND_USAGE = {
    "bootstrap": _FEISHU_NATIVE_BOOTSTRAP_USAGE,
    "doctor": "Usage:\n  controlmesh feishu native doctor\n",
    "probe": "Usage:\n  controlmesh feishu native probe\n",
    "register-begin": "Usage:\n  controlmesh feishu native register-begin\n",
}


def cmd_feishu(args: Sequence[str]) -> None:
    """Handle `controlmesh feishu ...` aliases."""
    action_args = _parse_feishu_command(args)
    if not action_args or action_args[0] in _HELP_FLAGS:
        _console.print(_FEISHU_USAGE)
        return
    if len(action_args) >= 2 and action_args[0] == "native":
        _cmd_feishu_native(action_args[1:])
        return
    raise SystemExit(1)


def _parse_feishu_command(args: Sequence[str]) -> list[str]:
    if not args:
        return []
    if args[0] == "feishu":
        return list(args[1:])
    if len(args) > 1 and args[1] == "feishu":
        return list(args[2:])
    return list(args)


def _cmd_feishu_native(args: Sequence[str]) -> None:
    if not args:
        cmd_auth(_NATIVE_AUTH_COMMANDS["bootstrap"])
        return

    action = args[0]
    if action in _HELP_FLAGS:
        _console.print(_FEISHU_NATIVE_USAGE)
        return

    if any(arg in _HELP_FLAGS for arg in args[1:]):
        usage = _NATIVE_COMMAND_USAGE.get(action)
        if usage:
            _console.print(usage)
            return

    auth_args = _NATIVE_AUTH_COMMANDS.get(action)
    if auth_args:
        cmd_auth(auth_args)
        return

    raise SystemExit(1)
