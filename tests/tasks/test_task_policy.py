"""Tests for shared task-runtime policy text."""

from __future__ import annotations

from controlmesh.orchestrator.hooks import DELEGATION_BRIEF, DELEGATION_REMINDER
from controlmesh.tasks.task_policy import build_task_agent_rules


def test_delegation_hooks_share_threshold_and_runtime_primitives() -> None:
    assert ">30 seconds" in DELEGATION_BRIEF.suffix
    assert "/tasks/create" in DELEGATION_BRIEF.suffix
    assert "/interagent/send" in DELEGATION_BRIEF.suffix
    assert ">30 seconds" in DELEGATION_REMINDER.suffix


def test_task_agent_rules_reuse_shared_task_policy() -> None:
    rendered = build_task_agent_rules("/tmp/task/TASKMEMORY.md")
    assert ">30 seconds" in rendered
    assert "/tasks/list" in rendered
    assert "/interagent/send" in rendered
