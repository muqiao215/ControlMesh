"""Telegram command handlers for agent fleet management and /mesh workflows."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from controlmesh.i18n import t
from controlmesh.routing.capabilities import CapabilityRegistry, default_capability_registry, load_capability_registry
from controlmesh.multiagent.approval_intent import parse_mesh_approval_intent
from controlmesh.multiagent.plan_review_loop import (
    approve_current_phase,
    artifacts_text,
    cancel_workflow,
    create_mesh_workflow,
    host_job_status_text,
    host_job_tail_text,
    mesh_clarification_text,
    _mesh_started_text,
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
                "\n".join(
                    [
                        t("agents.empty"),
                        "",
                        *_taskhub_policy_lines(orch),
                        "",
                        "Workflow tip:",
                        "- Use `/mesh <request>` for phased workflows.",
                    ]
                ),
            )
        )

    policy_lines = ["", *_taskhub_policy_lines(orch)]
    help_lines = [
        "",
        "Workflow tip:",
        "- Use `/mesh <request>` for phased workflows.",
        "- Legacy compatibility remains: `/agents run <request>`.",
    ]
    return OrchestratorResult(
        text=fmt(t("agents.header"), SEP, "\n".join(lines + policy_lines + help_lines))
    )


def _taskhub_policy_lines(orch: Orchestrator) -> list[str]:
    """Render the TaskHub execution policy block shown by /agents."""
    config = getattr(orch, "_config", None)
    tasks_cfg = getattr(config, "tasks", None)
    routing_cfg = getattr(config, "agent_routing", None)
    if tasks_cfg is None:
        return ["TaskHub policy:", "- unavailable: no task configuration"]

    default_provider = str(getattr(tasks_cfg, "default_provider", "") or "")
    default_model = str(getattr(tasks_cfg, "default_model", "") or "")
    if not default_provider:
        default_provider = str(getattr(config, "provider", "") or "")
    if not default_model:
        default_model = str(getattr(config, "model", "") or "")

    registry = _load_taskhub_capability_registry(config)
    background_slots = [slot for slot in registry.slots if slot.mode == "background"]
    profile_lines = [
        (
            f"  - {slot.name}: {slot.provider or 'runtime-default'}"
            f"{('/' + slot.model) if slot.model else ''}; {slot.role}; {slot.cost_class}; "
            f"tools={','.join(slot.tools) or '-'}; perms={','.join(slot.business_permissions) or 'none'}"
        )
        for slot in background_slots[:5]
    ]
    if len(background_slots) > 5:
        profile_lines.append(f"  - ... {len(background_slots) - 5} more")
    if not profile_lines:
        profile_lines.append("  - none")

    max_parallel = getattr(tasks_cfg, "max_parallel", 0)
    cadence = getattr(tasks_cfg, "cadence", "on_demand")
    guards = list(getattr(tasks_cfg, "risk_guards", []) or [])
    guard_text = ", ".join(str(item) for item in guards) or "none"
    routing_state = "enabled" if bool(getattr(routing_cfg, "enabled", False)) else "disabled"
    return [
        "TaskHub policy:",
        f"- default: {default_provider or '-'} / {default_model or '-'}",
        f"- max_parallel: {max_parallel}",
        f"- cadence: {cadence}",
        f"- routing: {routing_state}",
        f"- risk_guards: {guard_text}",
        "- force foreground: release, git_write, repo_write, publish",
        "- worker profiles:",
        *profile_lines,
    ]


def _load_taskhub_capability_registry(config: object) -> CapabilityRegistry:
    routing_cfg = getattr(config, "agent_routing", None)
    path = str(getattr(routing_cfg, "capability_registry", "") or "")
    if path:
        home = getattr(config, "controlmesh_home", "")
        from pathlib import Path

        registry_path = Path(path)
        if not registry_path.is_absolute() and home:
            registry_path = Path(str(home)).expanduser() / registry_path
        return load_capability_registry(registry_path, config)
    return default_capability_registry(config)


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
        start = await create_mesh_workflow(orch, key, parts[2], source_command="/agents")
        return OrchestratorResult(
            text=f"{_mesh_started_text(start)}\n\nTip: `/agents` is now a compatibility path. Use `/mesh` for phased workflows."
        )

    if action == "approve":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /agents approve <plan_id> <step_id>")
        intent = parse_mesh_approval_intent(f"/mesh approve {parts[2].strip()}")
        if intent is None:
            return OrchestratorResult(text="Usage: /agents approve <plan_id> <step_id>")
        return OrchestratorResult(text=await approve_current_phase(orch, key, intent.target, intent.step_id))

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

    start = await create_mesh_workflow(
        orch,
        key,
        text.removeprefix("/agents").strip(),
        source_command="/agents",
    )
    return OrchestratorResult(
        text=f"{_mesh_started_text(start)}\n\nTip: `/agents` is now a compatibility path. Use `/mesh` for phased workflows."
    )


async def cmd_mesh(orch: Orchestrator, key: SessionKey, text: str) -> OrchestratorResult:
    """Handle /mesh phased workflow controls."""
    raw = text.strip()
    parts = raw.split(None, 3)
    if raw == "/mesh":
        return OrchestratorResult(text=mesh_clarification_text())
    if len(parts) < 2:
        return OrchestratorResult(text=_workflow_usage("/mesh"))

    action = parts[1].strip().lower()
    async def _start_mesh(prompt: str) -> OrchestratorResult:
        try:
            start = await create_mesh_workflow(orch, key, prompt, source_command="/mesh")
        except ValueError as exc:
            return OrchestratorResult(text=str(exc))
        return OrchestratorResult(text=_mesh_started_text(start))

    if action == "run":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text=mesh_clarification_text())
        return await _start_mesh(parts[2])

    if action == "status":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh status <target>")
        target = parts[2].strip()
        host_status = host_job_status_text(orch, target, command_prefix="/mesh")
        if not host_status.startswith("No host job found"):
            return OrchestratorResult(text=host_status)
        return OrchestratorResult(text=workflow_status_text(orch, target, command_prefix="/mesh"))

    if action == "tail":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh tail <target> [lines]")
        target = parts[2].strip()
        line_count = 80
        if len(parts) >= 4 and parts[3].strip():
            try:
                line_count = int(parts[3].strip())
            except ValueError:
                return OrchestratorResult(text="Usage: /mesh tail <target> [lines]")
        return OrchestratorResult(text=host_job_tail_text(orch, target, lines=line_count))

    if action == "approve":
        if len(parts) < 3 or not parts[2].strip():
            return OrchestratorResult(text="Usage: /mesh approve <plan_id> <step_id>")
        intent = parse_mesh_approval_intent(raw)
        if intent is None:
            return OrchestratorResult(text="Usage: /mesh approve <plan_id> <step_id>")
        return OrchestratorResult(text=await approve_current_phase(orch, key, intent.target, intent.step_id))

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

    return await _start_mesh(raw.removeprefix("/mesh").strip())


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
