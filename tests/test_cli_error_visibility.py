"""CLIService error visibility guardrails."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock

from controlmesh.cli.service import CLIService, CLIServiceConfig
from controlmesh.cli.stream_events import ResultEvent, StreamEvent
from controlmesh.cli.types import AgentRequest, CLIResponse


class _FakeCLI:
    async def send(self, **_kwargs: object) -> CLIResponse:
        return CLIResponse(result="", is_error=True, returncode=7)

    async def send_streaming(self, **_kwargs: object) -> AsyncGenerator[StreamEvent, None]:
        yield ResultEvent(type="result", result="", is_error=True, returncode=7)


class _Models:
    def provider_for(self, _model: str) -> str:
        return "fake"


def _service(monkeypatch) -> CLIService:
    service = CLIService(
        config=CLIServiceConfig(
            working_dir=".",
            default_model="fake-model",
            provider="fake",
            max_turns=None,
            max_budget_usd=None,
            permission_mode="default",
        ),
        models=_Models(),
        available_providers=frozenset({"fake"}),
        process_registry=MagicMock(),
    )
    monkeypatch.setattr(service, "_make_cli", lambda _request: _FakeCLI())
    return service


async def test_execute_empty_error_gets_diagnostic(monkeypatch) -> None:
    response = await _service(monkeypatch).execute(AgentRequest(prompt="go"))

    assert response.is_error is True
    assert "fake exited with code 7 and produced no stdout/stderr." in response.result
    assert "provider: fake" in response.result


async def test_execute_streaming_empty_error_gets_diagnostic(monkeypatch) -> None:
    registry = MagicMock()
    registry.was_aborted.return_value = False
    service = _service(monkeypatch)
    service._process_registry = registry

    response = await service.execute_streaming(AgentRequest(prompt="go"))

    assert response.is_error is True
    assert "fake exited with code 7 and produced no stdout/stderr." in response.result
    assert "provider: fake" in response.result
