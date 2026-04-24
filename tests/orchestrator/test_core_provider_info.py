"""Tests for ProviderManager.build_provider_info (via Orchestrator._build_provider_info)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from controlmesh.config import AgentConfig, reset_gemini_models, set_gemini_models
from controlmesh.orchestrator.providers import ProviderManager


@pytest.fixture(autouse=True)
def _reset_gemini():
    reset_gemini_models()
    yield
    reset_gemini_models()


def _make_provider_manager(
    available: frozenset[str],
    codex_models: list[MagicMock] | None = None,
) -> tuple[ProviderManager, MagicMock | None]:
    """Create a ProviderManager with the given authenticated providers."""
    pm = ProviderManager(AgentConfig())
    pm._available_providers = available

    codex_obs = None
    if codex_models is not None:
        cache = MagicMock()
        cache.models = codex_models
        codex_obs = MagicMock()
        codex_obs.get_cache.return_value = cache

    return pm, codex_obs


class TestBuildProviderInfo:
    def test_claude_only(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"claude"}))
        info = pm.build_provider_info(obs)
        assert len(info) == 1
        assert info[0]["id"] == "claude"
        assert info[0]["name"] == "Claude Code"
        assert info[0]["color"] == "#F97316"
        assert sorted(info[0]["models"]) == ["haiku", "opus", "sonnet"]

    def test_multiple_providers_sorted(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"gemini", "claude"}))
        info = pm.build_provider_info(obs)
        assert len(info) == 2
        assert info[0]["id"] == "claude"
        assert info[1]["id"] == "gemini"

    def test_gemini_with_runtime_models(self) -> None:
        set_gemini_models(frozenset({"gemini-2.5-pro", "gemini-2.5-flash"}))
        pm, obs = _make_provider_manager(frozenset({"gemini"}))
        info = pm.build_provider_info(obs)
        assert info[0]["models"] == ["gemini-2.5-flash", "gemini-2.5-pro"]

    def test_gemini_falls_back_to_aliases(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"gemini"}))
        info = pm.build_provider_info(obs)
        assert "auto" in info[0]["models"]

    def test_codex_with_cache(self) -> None:
        model1 = MagicMock()
        model1.id = "o3-mini"
        model2 = MagicMock()
        model2.id = "o4-mini"
        pm, obs = _make_provider_manager(frozenset({"codex"}), codex_models=[model1, model2])
        info = pm.build_provider_info(obs)
        assert info[0]["models"] == ["o3-mini", "o4-mini"]

    def test_codex_without_cache(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"codex"}))
        info = pm.build_provider_info(obs)
        assert info[0]["models"] == []

    def test_openai_agents_provider_info(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"openai_agents"}))
        pm._config.provider = "openai_agents"
        pm._config.model = "gpt-5.4"
        info = pm.build_provider_info(obs)
        assert info[0]["id"] == "openai_agents"
        assert info[0]["name"] == "OpenAI Agents"
        assert info[0]["color"] == "#2563EB"
        assert info[0]["models"] == ["gpt-5.4"]

    def test_claw_provider_info(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"claw"}))
        pm._config.provider = "claw"
        pm._config.model = "sonnet"
        info = pm.build_provider_info(obs)
        assert info[0]["id"] == "claw"
        assert info[0]["name"] == "Claw-Code"
        assert info[0]["color"] == "#C084FC"
        assert info[0]["models"] == ["sonnet"]

    def test_opencode_provider_info(self) -> None:
        pm, obs = _make_provider_manager(frozenset({"opencode"}))
        pm._config.provider = "opencode"
        pm._config.model = "openai/gpt-4.1"
        info = pm.build_provider_info(obs)
        assert info[0]["id"] == "opencode"
        assert info[0]["name"] == "OpenCode"
        assert info[0]["color"] == "#06B6D4"
        assert info[0]["models"] == ["openai/gpt-4.1"]

    def test_empty_providers(self) -> None:
        pm, obs = _make_provider_manager(frozenset())
        info = pm.build_provider_info(obs)
        assert info == []
