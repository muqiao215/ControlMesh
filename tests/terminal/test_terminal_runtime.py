from __future__ import annotations

from controlmesh.config import AgentConfig, TerminalConfig
from controlmesh.terminal.runtime import _config_with_terminal_provider


def test_config_with_terminal_provider_uses_terminal_model_for_default_provider() -> None:
    config = AgentConfig(
        provider="claude",
        model="sonnet",
        terminal=TerminalConfig(default_provider="codex", default_model="gpt-5.5"),
    )

    updated = _config_with_terminal_provider(config, "codex")

    assert updated.provider == "codex"
    assert updated.model == "gpt-5.5"


def test_config_with_terminal_provider_keeps_model_for_nondefault_provider() -> None:
    config = AgentConfig(provider="claude", model="sonnet")

    updated = _config_with_terminal_provider(config, "opencode")

    assert updated.provider == "opencode"
    assert updated.model == "sonnet"
