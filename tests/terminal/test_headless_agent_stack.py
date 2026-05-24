from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.config import AgentConfig
from controlmesh.multiagent.models import SubAgentConfig, merge_sub_agent_config
from controlmesh.multiagent.stack import AgentStack, AgentStackMode, HeadlessBot


def test_headless_subagent_config_does_not_require_transport_credentials(tmp_path) -> None:
    main = AgentConfig(controlmesh_home=str(tmp_path))
    sub = SubAgentConfig(name="coder", mode="headless", provider="codex", model="gpt-5.5")

    config = merge_sub_agent_config(main, sub, tmp_path / "coder")

    assert config.provider == "codex"
    assert config.model == "gpt-5.5"
    assert config.telegram_token == ""
    assert config.allowed_user_ids == []


@pytest.mark.asyncio
async def test_headless_agent_stack_creates_orchestrator_without_transport_bot(tmp_path) -> None:
    config = AgentConfig(controlmesh_home=str(tmp_path))
    orchestrator = MagicMock()
    orchestrator.shutdown = AsyncMock()

    with (
        patch("controlmesh.multiagent.stack.init_workspace"),
        patch("controlmesh.orchestrator.core.Orchestrator.create", AsyncMock(return_value=orchestrator)),
    ):
        stack = await AgentStack.create("coder", config, mode=AgentStackMode.HEADLESS)

    assert stack.mode is AgentStackMode.HEADLESS
    assert isinstance(stack.bot, HeadlessBot)
    assert stack.orchestrator is orchestrator
