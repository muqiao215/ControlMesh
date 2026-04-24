"""Tests for provider choices in ``controlmesh agents add``."""

from __future__ import annotations

from unittest.mock import patch

from controlmesh.cli_commands import agents as agents_cli


def test_agents_add_offers_claw_code_and_opencode_providers(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CONTROLMESH_HOME", str(tmp_path))

    prompts = iter(["token", "", "", "claw", "sonnet"])
    seen_choices: list[str] = []

    class _Prompt:
        def __init__(self, value: str) -> None:
            self._value = value

        def ask(self) -> str:
            return self._value

    def _text(*_args, **_kwargs):
        return _Prompt(next(prompts))

    def _select(*_args, **kwargs):
        seen_choices.extend(kwargs["choices"])
        return _Prompt(next(prompts))

    with (
        patch("controlmesh.cli_commands.agents.questionary.text", side_effect=_text),
        patch("controlmesh.cli_commands.agents.questionary.select", side_effect=_select),
        patch("controlmesh.cli_commands.agents._console.print"),
    ):
        agents_cli.agents_add(["worker"])

    assert "claw-code" in seen_choices
    assert "opencode" in seen_choices
