"""Tests for the shared command classification module."""

from __future__ import annotations

from controlmesh.commands import BOT_COMMANDS, MULTIAGENT_SUB_COMMANDS, get_bot_commands
from controlmesh.messenger.commands import (
    DIRECT_COMMANDS,
    MULTIAGENT_COMMANDS,
    ORCHESTRATOR_COMMANDS,
    classify_command,
)


class TestClassifyCommand:
    """Tests for classify_command()."""

    def test_direct_commands(self) -> None:
        for cmd in DIRECT_COMMANDS:
            assert classify_command(cmd) == "direct", f"{cmd} should be direct"

    def test_orchestrator_commands(self) -> None:
        for cmd in ORCHESTRATOR_COMMANDS:
            assert classify_command(cmd) == "orchestrator", f"{cmd} should be orchestrator"

    def test_multiagent_commands(self) -> None:
        for cmd in MULTIAGENT_COMMANDS:
            assert classify_command(cmd) == "multiagent", f"{cmd} should be multiagent"

    def test_unknown_command(self) -> None:
        assert classify_command("nonexistent") == "unknown"
        assert classify_command("") == "unknown"
        assert classify_command("foobar") == "unknown"

    def test_history_is_orchestrator_command(self) -> None:
        assert classify_command("history") == "orchestrator"


class TestCommandSetIntegrity:
    """Tests for structural invariants of the command sets."""

    def test_no_overlap_direct_orchestrator(self) -> None:
        overlap = DIRECT_COMMANDS & ORCHESTRATOR_COMMANDS
        assert not overlap, f"DIRECT and ORCHESTRATOR overlap: {overlap}"

    def test_no_overlap_direct_multiagent(self) -> None:
        overlap = DIRECT_COMMANDS & MULTIAGENT_COMMANDS
        assert not overlap, f"DIRECT and MULTIAGENT overlap: {overlap}"

    def test_no_overlap_orchestrator_multiagent(self) -> None:
        overlap = ORCHESTRATOR_COMMANDS & MULTIAGENT_COMMANDS
        assert not overlap, f"ORCHESTRATOR and MULTIAGENT overlap: {overlap}"

    def test_all_bot_commands_classified(self) -> None:
        """Every command in BOT_COMMANDS must be classified (not unknown)."""
        for cmd_name, _desc in BOT_COMMANDS:
            result = classify_command(cmd_name)
            assert result != "unknown", f"BOT_COMMANDS entry {cmd_name!r} is not classified"

    def test_all_multiagent_sub_commands_classified(self) -> None:
        """Every command in MULTIAGENT_SUB_COMMANDS must be classified."""
        for cmd_name, _desc in MULTIAGENT_SUB_COMMANDS:
            result = classify_command(cmd_name)
            assert result != "unknown", (
                f"MULTIAGENT_SUB_COMMANDS entry {cmd_name!r} is not classified"
            )

    def test_telegram_menu_highlights_controlmesh_orchestration(self) -> None:
        """The popup menu should lead with ControlMesh orchestration primitives."""
        command_names = [cmd_name for cmd_name, _desc in get_bot_commands()]

        assert "cm" in command_names
        assert "agents" in command_names
        assert "agent_commands" not in command_names
        assert command_names.index("mode") < command_names.index("diagnose")
        assert command_names.index("tasks") < command_names.index("diagnose")
        assert command_names.index("agents") < command_names.index("diagnose")
