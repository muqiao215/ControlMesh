"""Tests for normalize_tool_name()."""

from __future__ import annotations

import pytest

from controlmesh.text.response_format import normalize_tool_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bash", "Shell"),
        ("bash", "Shell"),
        ("BASH", "Shell"),
        ("PowerShell", "Shell"),
        ("powershell", "Shell"),
        ("cmd", "Shell"),
        ("CMD", "Shell"),
        ("sh", "Shell"),
        ("zsh", "Shell"),
        ("shell", "Shell"),
        ("Shell", "Shell"),
        ("Read", "Read"),
        ("Write", "Write"),
        ("SearchTool", "SearchTool"),
        ("Grep", "Grep"),
        ("Edit", "Edit"),
    ],
)
def test_normalize_tool_name(raw: str, expected: str) -> None:
    assert normalize_tool_name(raw) == expected


def test_non_shell_tools_unchanged() -> None:
    for name in ("Read", "Write", "Grep", "Edit", "WebSearch", "ComputerTool"):
        assert normalize_tool_name(name) == name
