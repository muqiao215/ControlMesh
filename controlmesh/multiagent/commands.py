"""Telegram command handlers for agent fleet management and /mesh workflows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from controlmesh.i18n import t
from controlmesh.multiagent.plan_review_loop import (
    approve_current_phase,
    artifacts_text,
    cancel_workflow,
    create_mesh_workflow,
    repair_current_phase,
    score_current_phase,
    workflow_status_text,
)
from controlmesh.orchestrator.registry import OrchestratorResult
from controlmesh.text.response_format import SEP, fmt

if TYPE_CHECKING:
    from controlmesh.orchestrator.core import Orchestrator
    from controlmesh.session.key import SessionKey

logger = logging.getLogger(__name__)

_STATUS_EMOJI = {
    "running": "●",
    "starting": "◐",
    "crashed": "✖",
    "stopped": "○",
}


def _workflow_usage(prefix: str = "/mesh") -> str:
    return (
        f"Usage: {prefix} <request> | run | status | approve | repair | score | cancel | artifacts"
    )


def _workflow_started_text(task_id: str, plan_id: str) -> str:
    return (
        "ControlMesh workflow created.\n"
        f"- task: {task_id}\n"
        f"- plan: {plan_id}\n"
        "- next: planning runs in background, then phase 1 will start automatically"
    )


async def cmd_agents(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /agents fleet status and legacy workflow compatibility."""
    supervisor = orch.supervisor
    if supervisor is None:
        return OrchestratorResult(text=t("agents.not_active"))

    raw = text.strip()
    if raw != "/agents":
        return await _cmd_agents_compat(orch, key, raw)

    lines: list[str] = []
    for name in sorted(supervisor.health.keys()):
        health = supervisor.health[name]
        stack = supervisor.stacks.get(name)
        emoji = _STATUS_EMOJI.get(health.status, "?")
        role = "main" if (stack and stack.is_main) else "sub"

        info = f"  {emoji} **{name}** [{role}] — {health.status}"
        if health.status == "running" and health.uptime_human:
            info += f" ({health.uptime_human})"
        if stack:
            model_label = stack.config.model
            effort = stack.config.reasoning_effort
            if effort:
                model_label += f" ({effort})"
            info += f" | {model_label}"
        if health.restart_count > 0:
            info += f" (restarts: {health.restart_count})"
        if health.status == "crashed" and health.last_crash_error:
            info += f"\n      Error: {health.last_crash_error[:100]}"
        lines.append(info)

    if not lines:
        return OrchestratorResult(
            text=fmt(
                t("agents.header"),
                SEP,
                "\n".join([t("agents.empty"), "", "Workflow tip:", "- Use `/mesh <request>` for phased workflows."]),
            )
        )

    help_lines = [
        "",
        "Workflow tip:",
        "- Use `/mesh <request>` for phased workflows.",
        "- Legacy compatibility remains: `/agents run <request>`.",
    ]
    return OrchestratorResult(text=fmt(t("agents.header"), SEP, "\n".join(lines + help_lines)))


async def _cmd_agents_compat(
    orch: Orchestrator,
    key: SessionKey,
    text: str,
) -> OrchestratorResult:
    parts = text.split(None, 2)
    if len(parts) < 2:
        return OrchestratorResult(text=_workflow_usage("/agents"))

    action = parts[1].strip().lower()
    if action == "run":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /agents run <request>")
        task_id, plan_id = await create_mesh_workflow(orch, key, parts[2], source_command="/agents")
        return OrchestratorResult(
            text=f"{_workflow_started_text(task_id, plan_id)}\n\nTip: `/agents` is now a compatibility path. Use `/mesh` for phased workflows."
        )

    if action == "approve":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /agents approve <plan_id>")
        return OrchestratorResult(text=await approve_current_phase(orch, key, parts[2].strip()))

    if action == "repair":
        if len(parts) < 3:
            return OrchestratorResult(text="Usage: /agents repair <plan_id> [feedback]")
        repair_parts = parts[2].split(None, 1)
        plan_id = repair_parts[0].strip()
        feedback = repair_parts[1].strip() if len(repair_parts) > 1 else ""
        return OrchestratorResult(text=await repair_current_phase(orch, key, plan_id, feedback))

    if action == "status":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /agents status <plan_id>")
        return OrchestratorResult(text=workflow_status_text(orch, parts[2].strip(), command_prefix="/mesh"))

    task_id, plan_id = await create_mesh_workflow(
        orch,
        key,
        text.removeprefix("/agents").strip(),
        source_command="/agents",
    )
    return OrchestratorResult(
        text=f"{_workflow_started_text(task_id, plan_id)}\n\nTip: `/agents` is now a compatibility path. Use `/mesh` for phased workflows."
    )


async def cmd_mesh(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /mesh phased workflow controls."""
    raw = text.strip()
    parts = raw.split(None, 3)
    if raw == "/mesh":
        return OrchestratorResult(text="Usage: /mesh <request>")
    if len(parts) < 2:
        return OrchestratorResult(text=_workflow_usage("/mesh"))

    action = parts[1].strip().lower()
    if action == "run":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh run <request>")
        task_id, plan_id = await create_mesh_workflow(orch, key, parts[2], source_command="/mesh")
        return OrchestratorResult(text=_workflow_started_text(task_id, plan_id))

    if action == "status":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh status <plan_id>")
        return OrchestratorResult(text=workflow_status_text(orch, parts[2].strip(), command_prefix="/mesh"))

    if action == "approve":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh approve <plan_id>")
        return OrchestratorResult(text=await approve_current_phase(orch, key, parts[2].strip()))

    if action == "repair":
        if len(parts) < 3:
            return OrchestratorResult(text="Usage: /mesh repair <plan_id> [feedback]")
        repair_parts = parts[2].split(None, 1)
        plan_id = repair_parts[0].strip()
        feedback = repair_parts[1].strip() if len(repair_parts) > 1 else ""
        return OrchestratorResult(text=await repair_current_phase(orch, key, plan_id, feedback))

    if action == "score":
        if len(parts) < 4:
            return OrchestratorResult(text="Usage: /mesh score <plan_id> <score> <comment>")
        score_parts = parts[2].split(None, 1)
        if len(score_parts) < 2:
            return OrchestratorResult(text="Usage: /mesh score <plan_id> <score> <comment>")
        plan_id = score_parts[0].strip()
        score_token = score_parts[1].strip()
        if len(parts) < 4 or not parts[3].strip():
            return OrchestratorResult(text="Usage: /mesh score <plan_id> <score> <comment>")
        return OrchestratorResult(text=await score_current_phase(orch, key, plan_id, score_token, parts[3].strip()))

    if action == "cancel":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh cancel <plan_id>")
        return OrchestratorResult(text=await cancel_workflow(orch, parts[2].strip()))

    if action == "artifacts":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh artifacts <plan_id>")
        return OrchestratorResult(text=artifacts_text(orch, parts[2].strip()))

    task_id, plan_id = await create_mesh_workflow(
        orch,
        key,
        raw.removeprefix("/mesh").strip(),
        source_command="/mesh",
    )
    return OrchestratorResult(text=_workflow_started_text(task_id, plan_id))


async def cmd_agent_stop(orch: Orchestrator, _key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /agent_stop <name>: stop a sub-agent."""
    supervisor = orch.supervisor
    if supervisor is None:
        return OrchestratorResult(text=t("agents.not_active"))

    parts = text.split(None, 1)
    if len(parts) < 2:
        return OrchestratorResult(text=t("agents.usage_stop"))

    name = parts[1].strip().lower()
    if name == "main":
        return OrchestratorResult(text=t("agents.cannot_stop_main"))

    if name not in supervisor.stacks:
        return OrchestratorResult(text=t("agents.not_running", name=name))

    await supervisor.stop_agent(name)
    return OrchestratorResult(text=t("agents.stopped", name=name))


async def cmd_agent_start(orch: Orchestrator, _key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /agent_start <name>: start a sub-agent from the registry."""
    supervisor = orch.supervisor
    if supervisor is None:
        return OrchestratorResult(text=t("agents.not_active"))

    parts = text.split(None, 1)
    if len(parts) < 2:
        return OrchestratorResult(text=t("agents.usage_start"))

    name = parts[1].strip().lower()
    result = await supervisor.start_agent_by_name(name)
    return OrchestratorResult(text=result)


async def cmd_agent_restart(orch: Orchestrator, _key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /agent_restart <name>: restart a sub-agent."""
    supervisor = orch.supervisor
    if supervisor is None:
        return OrchestratorResult(text=t("agents.not_active"))

    parts = text.split(None, 1)
    if len(parts) < 2:
        return OrchestratorResult(text=t("agents.usage_restart"))

    name = parts[1].strip().lower()
    result = await supervisor.restart_agent(name)
    return OrchestratorResult(text=result)
