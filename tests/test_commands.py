"""Tests for command definitions."""

from controlmesh.command_registry import get_visible_commands, is_controlmesh_owned_command
from controlmesh.commands import BOT_COMMANDS, get_bot_commands


def test_commands_is_list_of_tuples() -> None:
    assert isinstance(BOT_COMMANDS, list)
    for item in BOT_COMMANDS:
        assert isinstance(item, tuple)
        assert len(item) == 2
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)


def test_expected_commands_present() -> None:
    names = {cmd for cmd, _ in BOT_COMMANDS}
    expected = {
        "new",
        "model",
        "cm",
        "tasks",
        "session",
        "agents",
        "cron",
        "status",
        "memory",
        "stop",
        "interrupt",
        "help",
    }
    assert expected.issubset(names)
    assert "mode" not in names


def test_rare_commands_not_in_popup_menu() -> None:
    names = {cmd for cmd, _ in BOT_COMMANDS}
    assert not {"showfiles", "info", "diagnose", "upgrade", "restart", "agent_commands"} & names


def test_no_duplicate_commands() -> None:
    names = [cmd for cmd, _ in BOT_COMMANDS]
    assert len(names) == len(set(names))


def test_visible_commands_are_display_only_subset() -> None:
    visible = set(get_visible_commands())

    assert visible == {cmd for cmd, _ in BOT_COMMANDS}
    assert "history" not in visible
    assert "agent_start" not in visible
    assert is_controlmesh_owned_command("/history today")
    assert is_controlmesh_owned_command("/agent_start worker")


def test_worker_visible_commands_exclude_main_only_entries() -> None:
    worker_visible = get_visible_commands(agent_name="worker")
    worker_bot_commands = [cmd for cmd, _ in get_bot_commands(agent_name="worker")]

    assert worker_visible == worker_bot_commands
    assert "agents" not in worker_visible
    assert "history" not in worker_visible
