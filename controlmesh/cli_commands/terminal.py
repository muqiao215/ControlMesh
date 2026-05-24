"""CLI command for the ControlMesh enhanced terminal."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence


def cmd_terminal(args: Sequence[str]) -> None:
    """Run the enhanced terminal."""
    asyncio.run(_run(args))


async def _run(args: Sequence[str]) -> None:
    from controlmesh.__main__ import load_config
    from controlmesh.terminal.app import TerminalApp

    config = load_config()
    app = TerminalApp.from_args(config=config, args=args)
    await app.run()
