"""Tests for command definitions."""

from controlmesh.commands import BOT_COMMANDS


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
