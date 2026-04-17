"""Product-friendly Feishu native CLI aliases."""

from __future__ import annotations

from collections.abc import Sequence

from controlmesh.cli_commands.auth import cmd_auth


def cmd_feishu(args: Sequence[str]) -> None:
    """Handle `controlmesh feishu ...` aliases."""
    action_args = _parse_feishu_command(args)
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
    action = args[0] if args else "bootstrap"
    if action == "bootstrap":
        cmd_auth(["auth", "feishu", "setup"])
        return
    if action == "doctor":
        cmd_auth(["auth", "feishu", "doctor"])
        return
    if action == "probe":
        cmd_auth(["auth", "feishu", "probe"])
        return
    if action == "register-begin":
        cmd_auth(["auth", "feishu", "register-begin"])
        return
    raise SystemExit(1)
