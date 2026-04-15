"""Tests for scene features: OrchestratorResult metadata and footer appending."""

from __future__ import annotations

from controlmesh.cli.types import AgentResponse
from controlmesh.config import SceneConfig
from controlmesh.messenger.telegram.message_dispatch import _build_footer
from controlmesh.orchestrator.flows import _finish_normal
from controlmesh.orchestrator.registry import OrchestratorResult


class TestOrchestratorResultMetadata:
    def test_defaults(self) -> None:
        r = OrchestratorResult(text="hello")
        assert r.model_name is None
        assert r.total_tokens == 0
        assert r.input_tokens == 0
        assert r.cost_usd == 0.0
        assert r.duration_ms is None

    def test_explicit_metadata(self) -> None:
        r = OrchestratorResult(
            text="hello",
            model_name="opus",
            total_tokens=1000,
            input_tokens=800,
            cost_usd=0.05,
            duration_ms=3000.0,
        )
        assert r.model_name == "opus"
        assert r.total_tokens == 1000
        assert r.input_tokens == 800
        assert r.cost_usd == 0.05
        assert r.duration_ms == 3000.0


class TestFinishNormalMetadata:
    def test_populates_metadata(self) -> None:
        response = AgentResponse(
            result="Agent output",
            total_tokens=500,
            input_tokens=300,
            cost_usd=0.02,
            duration_ms=2500.0,
        )
        result = _finish_normal(response, model_name="opus")
        assert result.model_name == "opus"
        assert result.total_tokens == 500
        assert result.input_tokens == 300
        assert result.cost_usd == 0.02
        assert result.duration_ms == 2500.0

    def test_error_response_no_metadata(self) -> None:
        response = AgentResponse(result="fail", is_error=True)
        result = _finish_normal(response, model_name="opus")
        assert result.model_name is None


class TestBuildFooter:
    def test_footer_built_when_enabled(self) -> None:
        scene = SceneConfig(technical_footer=True)
        result = OrchestratorResult(
            text="Hello",
            model_name="opus",
            total_tokens=1000,
            input_tokens=800,
            cost_usd=0.05,
            duration_ms=3000.0,
        )
        footer = _build_footer(result, scene)
        assert "Model: opus" in footer
        assert "Tokens: 1000" in footer

    def test_footer_empty_when_disabled(self) -> None:
        scene = SceneConfig(technical_footer=False)
        result = OrchestratorResult(text="Hello", model_name="opus")
        assert _build_footer(result, scene) == ""

    def test_footer_empty_without_model(self) -> None:
        scene = SceneConfig(technical_footer=True)
        result = OrchestratorResult(text="Hello")
        assert _build_footer(result, scene) == ""

    def test_footer_empty_with_none_config(self) -> None:
        result = OrchestratorResult(text="Hello", model_name="opus")
        assert _build_footer(result, None) == ""
