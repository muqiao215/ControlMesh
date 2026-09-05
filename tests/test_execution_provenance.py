from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from controlmesh.bus.envelope import ExecutionContext, Origin, SourceScope
from controlmesh.cli.process_registry import ProcessRegistry
from controlmesh.cli.service import CLIService, CLIServiceConfig
from controlmesh.cli.types import AgentRequest
from controlmesh.config import ModelRegistry
from controlmesh.execution_policy import ExecutionPolicyDenied
from controlmesh.tasks.models import TaskEntry


def _context(scope: SourceScope = SourceScope.GROUP_MESSAGE) -> ExecutionContext:
    return ExecutionContext.issue(
        origin=Origin.USER,
        source_scope=scope,
        transport="test",
        source_id="message-1",
    )


def test_execution_context_round_trip_is_strict_and_non_sensitive() -> None:
    context = _context()
    persisted = context.to_dict()
    assert persisted["source_ref"] != "message-1"
    assert ExecutionContext.from_dict(persisted) == context
    with pytest.raises(ValueError, match="trace_id"):
        ExecutionContext.from_dict({**persisted, "trace_id": "not-a-trace"})


def test_task_entry_persists_execution_context_without_prompt_or_paths() -> None:
    entry = TaskEntry(
        task_id="task-1",
        chat_id=1,
        parent_agent="main",
        name="safe",
        prompt_preview="do work",
        execution_context=_context(),
    )
    restored = TaskEntry.from_dict(entry.to_dict())
    assert restored.execution_context == entry.execution_context
    assert "message-1" not in str(entry.to_dict())


def test_cli_service_denies_required_scope_before_provider_construction(tmp_path: Path) -> None:
    service = CLIService(
        config=CLIServiceConfig(
            working_dir=str(tmp_path),
            default_model="opus",
            provider="claude",
            max_turns=None,
            max_budget_usd=None,
            permission_mode="bypassPermissions",
            docker_container="",
        ),
        models=ModelRegistry(),
        available_providers=frozenset({"claude"}),
        process_registry=ProcessRegistry(),
    )
    with patch("controlmesh.cli.service.create_cli", new_callable=MagicMock) as create_cli, pytest.raises(
        ExecutionPolicyDenied
    ) as raised:
        service._make_cli(AgentRequest(prompt="group work", execution_context=_context()))
    create_cli.assert_not_called()
    assert raised.value.decision.reason_code == "sandbox_required_unavailable"
    assert service.last_execution_policy_decision == raised.value.decision
