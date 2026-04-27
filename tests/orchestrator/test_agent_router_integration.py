"""Integration-style routing tests for the orchestrator backend router slice."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from controlmesh.cli.types import AgentResponse
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.session.key import SessionKey


@pytest.fixture
def orch(orch: Orchestrator) -> Orchestrator:
    return orch


def _mock_response(**kwargs: object) -> AgentResponse:
    defaults: dict[str, object] = {
        "result": "Response text",
        "session_id": "sess-router",
        "is_error": False,
    }
    defaults.update(kwargs)
    return AgentResponse(**defaults)  # type: ignore[arg-type]


async def test_disabled_router_leaves_behavior_unchanged(orch: Orchestrator) -> None:
    mock_execute = AsyncMock(return_value=_mock_response())
    object.__setattr__(orch._cli_service, "execute", mock_execute)

    await orch.handle_message(SessionKey(chat_id=1), "@openai_agents hello")

    request = mock_execute.call_args[0][0]
    assert request.prompt.startswith("hello")
    assert request.provider_override == "claude"
    assert request.model_override == "opus"


async def test_enabled_router_uses_openai_agents_provider_override(orch: Orchestrator) -> None:
    orch._config.agent_graph.enabled = True
    orch._config.agent_graph.openai_agents_model = "gpt-5.4"
    mock_execute = AsyncMock(return_value=_mock_response(result="planned"))
    object.__setattr__(orch._cli_service, "execute", mock_execute)

    result = await orch.handle_message(SessionKey(chat_id=1), "@openai_agents hello")

    request = mock_execute.call_args[0][0]
    assert result.text == "planned"
    assert request.prompt.startswith("hello")
    assert request.provider_override == "openai_agents"
    assert request.model_override == "gpt-5.4"


async def test_enabled_router_does_not_override_model_directive(orch: Orchestrator) -> None:
    orch._config.agent_graph.enabled = True
    mock_execute = AsyncMock(return_value=_mock_response())
    object.__setattr__(orch._cli_service, "execute", mock_execute)

    await orch.handle_message(SessionKey(chat_id=1), "@openai_agents @sonnet hello")

    request = mock_execute.call_args[0][0]
    assert request.prompt.startswith("hello")
    assert request.provider_override == "claude"
    assert request.model_override == "sonnet"


async def test_claude_command_menu_still_wins_over_router(orch: Orchestrator) -> None:
    key = SessionKey(chat_id=1)
    orch._config.agent_graph.enabled = True
    session, _ = await orch._sessions.resolve_session(key, provider="claude", model="opus")
    session.command_mode = "claude"
    session.command_mode_model = "opus"
    await orch._sessions.sync_command_mode(session, mode="claude", model="opus")

    mock_execute = AsyncMock(return_value=_mock_response(result="Native Claude response"))
    object.__setattr__(orch._cli_service, "execute", mock_execute)

    result = await orch.handle_message(key, "/compact")

    request = mock_execute.call_args[0][0]
    assert result.text == "Native Claude response"
    assert request.prompt == "/compact"
    assert request.provider_override == "claude"
