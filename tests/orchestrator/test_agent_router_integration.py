"""Integration-style routing tests for the orchestrator backend router slice."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.cli.types import AgentResponse
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.routing.router import RouteDecision
from controlmesh.routing.workunit import WorkUnit, WorkUnitKind, requirements_for_kind
from controlmesh.session.key import SessionKey
from controlmesh.tasks.models import TaskEntry, TaskSubmit


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


def _write_activation_policy(orch: Orchestrator, body: str) -> None:
    path = orch.paths.controlmesh_home / "routing" / "activation_policies.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _release_decision(prompt: str) -> RouteDecision:
    unit = WorkUnit(
        kind=WorkUnitKind.GITHUB_RELEASE,
        name=f"github_release: {prompt}",
        prompt=prompt,
        requirements=requirements_for_kind(WorkUnitKind.GITHUB_RELEASE),
    )
    return RouteDecision(
        workunit=unit,
        slot_name="release_runner",
        provider="gemini",
        model="flash",
        topology="pipeline",
        confidence=0.91,
        required_capabilities=unit.requirements.capabilities,
        evaluator="foreground",
        reason="policy matched; selected topology=pipeline",
        contract="",
    )


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


async def test_activation_policy_background_required_submits_taskhub_from_chat(
    orch: Orchestrator,
) -> None:
    _write_activation_policy(
        orch,
        """
activation_policies:
  github_release_always_background:
    execution: background_required
    match:
      workunit_kinds: [github_release]
    preferred_slots: [release_runner]
    topology: pipeline
    requires_foreground_approval: true
""".strip()
        + "\n",
    )
    hub = MagicMock()
    hub.submit = MagicMock(return_value="task1234")
    hub.start_maintenance = MagicMock()
    orch.set_task_hub(hub)

    with patch(
        "controlmesh.orchestrator.core.resolve_route",
        return_value=_release_decision("请帮我发布新版本"),
    ):
        result = await orch.handle_message(
            SessionKey(chat_id=1),
            "请帮我发布新版本",
            message_id=321,
        )

    hub.submit.assert_called_once()
    submit = hub.submit.call_args.args[0]
    assert isinstance(submit, TaskSubmit)
    assert submit.message_id == 321
    assert submit.route == "auto"
    assert submit.workunit_kind == "github_release"
    assert submit.topology == "pipeline"
    assert submit.evaluator == "foreground"
    assert "policy: github_release_always_background" in result.text
    assert "workunit: github_release" in result.text
    assert "slot: release_runner" in result.text
    assert "provider/model: gemini/flash" in result.text
    assert "task: task1234" in result.text
    assert "results: completion or approval follow-ups will return here" in result.text


async def test_activation_policy_skips_background_intercept_for_explicit_model_directive(
    orch: Orchestrator,
) -> None:
    _write_activation_policy(
        orch,
        """
activation_policies:
  github_release_always_background:
    execution: background_required
    match:
      workunit_kinds: [github_release]
""".strip()
        + "\n",
    )
    hub = MagicMock()
    hub.submit = MagicMock(return_value="task1234")
    hub.start_maintenance = MagicMock()
    orch.set_task_hub(hub)
    mock_execute = AsyncMock(return_value=_mock_response(result="foreground release flow"))
    object.__setattr__(orch._cli_service, "execute", mock_execute)

    result = await orch.handle_message(SessionKey(chat_id=1), "@sonnet 请帮我发布新版本")

    hub.submit.assert_not_called()
    assert result.text == "foreground release flow"
    request = mock_execute.call_args[0][0]
    assert request.prompt.startswith("请帮我发布新版本")
    assert request.model_override == "sonnet"


async def test_activation_policy_reports_when_no_background_route_is_available(
    orch: Orchestrator,
) -> None:
    _write_activation_policy(
        orch,
        """
activation_policies:
  github_release_always_background:
    execution: background_required
    match:
      workunit_kinds: [github_release]
""".strip()
        + "\n",
    )
    hub = MagicMock()
    hub.submit = MagicMock(return_value="task1234")
    hub.start_maintenance = MagicMock()
    orch.set_task_hub(hub)

    with patch("controlmesh.orchestrator.core.resolve_route", return_value=None):
        result = await orch.handle_message(SessionKey(chat_id=1), "请帮我发布新版本")

    hub.submit.assert_not_called()
    assert "Matched activation policy but no eligible background route was available." in result.text
    assert "policy: github_release_always_background" in result.text
    assert "workunit: github_release" in result.text
    assert "run it explicitly in foreground" in result.text


async def test_route_status_explains_background_routing_surface(orch: Orchestrator) -> None:
    _write_activation_policy(
        orch,
        """
activation_policies:
  github_release_always_background:
    execution: background_required
    match:
      workunit_kinds: [github_release]
""".strip()
        + "\n",
    )
    entry = TaskEntry(
        task_id="task1234",
        chat_id=1,
        parent_agent="main",
        name="Release",
        prompt_preview="please release",
        provider="gemini",
        model="flash",
        status="running",
        route="auto",
        workunit_kind="github_release",
        route_reason="policy=github_release_always_background; selected topology=pipeline",
        topology="pipeline",
        route_slot="release_runner",
    )
    hub = MagicMock()
    hub.registry.list_all.return_value = [entry]
    hub.start_maintenance = MagicMock()
    orch.set_task_hub(hub)

    result = await orch.handle_message(SessionKey(chat_id=1), "/route status")

    assert "Route status" in result.text
    assert "activation policies: 1" in result.text
    assert "github_release_always_background" in result.text
    assert "automatic background tasks: 1" in result.text
    assert "task1234" in result.text
    assert "Use `/route why task1234`" in result.text
    assert "`/agents` is for persistent sub-agents" in result.text


async def test_route_why_explains_auto_background_task(orch: Orchestrator) -> None:
    entry = TaskEntry(
        task_id="task1234",
        chat_id=1,
        parent_agent="main",
        name="Release",
        prompt_preview="please release",
        provider="gemini",
        model="flash",
        status="running",
        route="auto",
        workunit_kind="github_release",
        route_reason="policy=github_release_always_background; selected topology=pipeline",
        topology="pipeline",
        route_slot="release_runner",
        evaluator="foreground",
    )
    hub = MagicMock()
    hub.registry.get.return_value = entry
    hub.start_maintenance = MagicMock()
    orch.set_task_hub(hub)

    result = await orch.handle_message(SessionKey(chat_id=1), "/route why task1234")

    assert "Route why task1234" in result.text
    assert "route: auto" in result.text
    assert "workunit: github_release" in result.text
    assert "policy=github_release_always_background" in result.text
    assert "slot: release_runner" in result.text
    assert "provider/model: gemini/flash" in result.text
    assert "approval: foreground" in result.text
