"""Capability registry loading and default agent slots."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class AgentSlot:
    """A routable runtime/model/tool capability slot."""

    name: str
    runtime: str = ""
    provider: str = ""
    model: str = ""
    mode: str = "background"
    role: str = "worker"
    cost_class: str = "standard"
    allow_subagent: bool = True
    capabilities: dict[str, float] = field(default_factory=dict)
    tools: tuple[str, ...] = ()
    can_edit: bool = False
    canonical_write: bool = False
    topology_preferences: dict[str, str] = field(default_factory=dict)

    def capability_score(self, capability: str) -> float:
        return float(self.capabilities.get(capability, 0.0))


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    """Collection of routable slots."""

    slots: tuple[AgentSlot, ...] = ()

    def candidates(self, *, mode: str = "background") -> tuple[AgentSlot, ...]:
        selected = [slot for slot in self.slots if slot.mode == mode]
        return tuple(selected or self.slots)


def default_capability_registry(config: object | None = None) -> CapabilityRegistry:
    """Build conservative defaults from the active config."""
    provider = str(getattr(config, "provider", "claude") or "claude")
    model = str(getattr(config, "model", "opus") or "opus")
    slots = [
        AgentSlot(
            name="foreground_controller",
            runtime="controlmesh_foreground",
            provider=provider,
            model=model,
            mode="foreground",
            role="controller",
            cost_class="premium",
            allow_subagent=False,
            canonical_write=True,
            capabilities={
                "planning": 0.9,
                "routing": 0.9,
                "synthesis": 0.86,
                "final_judgment": 0.88,
            },
        ),
        AgentSlot(
            name="background_worker",
            runtime="controlmesh_background",
            provider=provider,
            model=model,
            mode="background",
            role="worker",
            cost_class="standard",
            allow_subagent=True,
            can_edit=True,
            capabilities={
                "shell_execution": 0.72,
                "test_log_analysis": 0.72,
                "evidence_writer": 0.72,
                "code_patch": 0.72,
                "test_execution": 0.72,
                "code_review": 0.68,
                "diff_understanding": 0.68,
            },
        ),
        AgentSlot(
            name="release_runner",
            runtime="controlmesh_background",
            provider="gemini",
            model="flash",
            mode="background",
            role="worker",
            cost_class="cheap",
            allow_subagent=True,
            capabilities={
                "github_release": 0.86,
                "shell_execution": 0.75,
                "release_notes": 0.85,
                "evidence_writer": 0.82,
            },
            topology_preferences={"github_release": "pipeline"},
        ),
        AgentSlot(
            name="codex_cli",
            runtime="codex_cli",
            provider="codex",
            model="",
            mode="background",
            role="worker",
            cost_class="premium",
            allow_subagent=False,
            can_edit=True,
            capabilities={
                "code_review": 0.9,
                "adversarial_review": 0.9,
                "diff_understanding": 0.88,
                "code_patch": 0.86,
                "test_execution": 0.82,
                "test_log_analysis": 0.82,
                "evidence_writer": 0.84,
                "shell_execution": 0.78,
            },
            topology_preferences={
                "code_review": "fanout_merge",
                "patch_candidate": "director_worker",
            },
        ),
        AgentSlot(
            name="claude_code.codex_plugin_review",
            runtime="claude_code",
            provider="claude",
            model="",
            mode="background",
            role="worker",
            cost_class="standard",
            allow_subagent=True,
            capabilities={
                "code_review": 0.86,
                "adversarial_review": 0.88,
                "diff_understanding": 0.84,
                "evidence_writer": 0.82,
            },
            topology_preferences={"code_review": "fanout_merge"},
        ),
        AgentSlot(
            name="opencode.explore",
            runtime="opencode",
            provider="opencode",
            model="",
            mode="background",
            role="worker",
            cost_class="cheap",
            allow_subagent=True,
            capabilities={
                "code_search": 0.86,
                "code_review": 0.78,
                "diff_understanding": 0.76,
                "test_log_analysis": 0.78,
                "evidence_writer": 0.78,
                "shell_execution": 0.78,
            },
        ),
    ]
    return CapabilityRegistry(slots=tuple(slots))


def load_capability_registry(path: str | Path, config: object | None = None) -> CapabilityRegistry:
    """Load capability slots from YAML, falling back to defaults when absent."""
    registry_path = Path(path).expanduser()
    if not registry_path.is_file():
        return default_capability_registry(config)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return default_capability_registry(config)
    raw_slots = raw.get("agent_slots", {})
    if not isinstance(raw_slots, dict):
        return default_capability_registry(config)

    slots: list[AgentSlot] = []
    for name, payload in raw_slots.items():
        if not isinstance(name, str) or not isinstance(payload, dict):
            continue
        slots.append(_slot_from_mapping(name, payload))
    return CapabilityRegistry(slots=tuple(slots)) if slots else default_capability_registry(config)


def _slot_from_mapping(name: str, payload: dict[str, Any]) -> AgentSlot:
    capabilities_raw = payload.get("capabilities", {})
    capabilities: dict[str, float] = {}
    if isinstance(capabilities_raw, dict):
        for cap, value in capabilities_raw.items():
            if isinstance(cap, str):
                raw_score = value.get("score", 0.0) if isinstance(value, dict) else value
                try:
                    capabilities[cap] = float(raw_score)
                except (TypeError, ValueError):
                    continue
    permissions = payload.get("permissions", {})
    if not isinstance(permissions, dict):
        permissions = {}
    tools = payload.get("tools", ())
    if not isinstance(tools, list):
        tools = []
    topology_preferences = payload.get("topology_preferences", {})
    if not isinstance(topology_preferences, dict):
        topology_preferences = {}
    model = str(payload.get("model", ""))
    if model.lower() == "auto":
        model = ""
    return AgentSlot(
        name=name,
        runtime=str(payload.get("runtime", "")),
        provider=str(payload.get("provider", "")),
        model=model,
        mode=str(payload.get("mode", "background")),
        role=str(payload.get("role", "worker")),
        cost_class=str(payload.get("cost_class", "standard")),
        allow_subagent=bool(payload.get("allow_subagent", True)),
        capabilities=capabilities,
        tools=tuple(str(tool) for tool in tools),
        can_edit=bool(payload.get("can_edit", permissions.get("edit", False))),
        canonical_write=bool(
            payload.get("canonical_write", permissions.get("canonical_write", False))
        ),
        topology_preferences={str(k): str(v) for k, v in topology_preferences.items()},
    )
