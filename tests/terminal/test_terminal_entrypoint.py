from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.terminal.runtime import TerminalRuntime


def test_interactive_controlmesh_defaults_to_terminal() -> None:
    from controlmesh import __main__ as main_mod

    with (
        patch.object(sys, "argv", ["controlmesh"]),
        patch("controlmesh.__main__._enforce_runtime_provenance"),
        patch("controlmesh.__main__.sys.stdin.isatty", return_value=True),
        patch("controlmesh.__main__.sys.stdout.isatty", return_value=True),
        patch("controlmesh.__main__._cmd_terminal") as terminal,
        patch("controlmesh.__main__._default_action") as default,
    ):
        main_mod.main()

    terminal.assert_called_once_with([])
    default.assert_not_called()


def test_noninteractive_controlmesh_keeps_default_action() -> None:
    from controlmesh import __main__ as main_mod

    with (
        patch.object(sys, "argv", ["controlmesh"]),
        patch("controlmesh.__main__._enforce_runtime_provenance"),
        patch("controlmesh.__main__.sys.stdin.isatty", return_value=False),
        patch("controlmesh.__main__.sys.stdout.isatty", return_value=False),
        patch("controlmesh.__main__._cmd_terminal") as terminal,
        patch("controlmesh.__main__._default_action") as default,
    ):
        main_mod.main()

    terminal.assert_not_called()
    default.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_background_runtime_startup_failure_does_not_prevent_terminal_start() -> None:
    runtime = TerminalRuntime(config=AgentConfig(), provider="codex")
    runtime.config.terminal.enable_background_agents = True

    with patch("controlmesh.multiagent.supervisor.AgentSupervisor.start_core", side_effect=OSError("busy")):
        await runtime.start_optional_background_runtime()

    assert runtime.supervisor is None


def test_bot_command_uses_legacy_default_action() -> None:
    from controlmesh import __main__ as main_mod

    with (
        patch.object(sys, "argv", ["controlmesh", "bot"]),
        patch("controlmesh.__main__._enforce_runtime_provenance"),
        patch("controlmesh.__main__._cmd_terminal") as terminal,
        patch("controlmesh.__main__._default_action") as default,
    ):
        main_mod.main()

    terminal.assert_not_called()
    default.assert_called_once_with(False)
