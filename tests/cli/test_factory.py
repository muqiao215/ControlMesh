"""Tests for cli/factory.py: create_cli backend selection."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.claude_provider import ClaudeCodeCLI
from controlmesh.cli.claw_provider import ClawCLI
from controlmesh.cli.codex_provider import CodexCLI
from controlmesh.cli.factory import create_cli
from controlmesh.cli.gemini_provider import GeminiCLI
from controlmesh.cli.openai_agents_provider import OpenAIAgentsCLI
from controlmesh.cli.opencode_provider import OpenCodeCLI


@pytest.fixture(autouse=True)
def _mock_local_cli_binaries() -> Generator[None, None, None]:
    """Keep provider-construction tests independent from host PATH."""
    with (
        patch("controlmesh.cli.claude_provider.ClaudeCodeCLI._find_cli", return_value="claude"),
        patch("controlmesh.cli.codex_provider.CodexCLI._find_cli", return_value="codex"),
    ):
        yield


def test_create_cli_returns_claude_by_default() -> None:
    cli = create_cli(CLIConfig(provider="claude"))
    assert isinstance(cli, ClaudeCodeCLI)


def test_create_cli_returns_codex() -> None:
    cli = create_cli(CLIConfig(provider="codex"))
    assert isinstance(cli, CodexCLI)


def test_create_cli_returns_gemini() -> None:
    with (
        patch("controlmesh.cli.gemini_provider.find_gemini_cli", return_value="/usr/bin/gemini"),
        patch("controlmesh.cli.gemini_provider.find_gemini_cli_js", return_value=None),
    ):
        cli = create_cli(CLIConfig(provider="gemini"))
    assert isinstance(cli, GeminiCLI)


def test_create_cli_returns_openai_agents() -> None:
    cli = create_cli(CLIConfig(provider="openai_agents"))
    assert isinstance(cli, OpenAIAgentsCLI)


def test_create_cli_returns_claw() -> None:
    with patch("controlmesh.cli.claw_provider.which", return_value="/usr/bin/claw"):
        cli = create_cli(CLIConfig(provider="claw"))
    assert isinstance(cli, ClawCLI)


def test_create_cli_returns_opencode() -> None:
    with patch("controlmesh.cli.opencode_provider.which", return_value="/usr/bin/opencode"):
        cli = create_cli(CLIConfig(provider="opencode"))
    assert isinstance(cli, OpenCodeCLI)


def test_create_cli_unknown_provider_returns_claude() -> None:
    cli = create_cli(CLIConfig(provider="unknown"))
    assert isinstance(cli, ClaudeCodeCLI)
