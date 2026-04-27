"""Route WorkUnits to provider/model/topology decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from controlmesh.routing.capabilities import (
    CapabilityRegistry,
    default_capability_registry,
    load_capability_registry,
)
from controlmesh.routing.policy import (
    default_topology_for_kind,
    detect_workunit_kind,
    normalize_topology,
)
from controlmesh.routing.scorer import rank_slots
from controlmesh.routing.workunit import WorkUnit, build_workunit_contract, requirements_for_kind


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Resolved route for one background task."""

    workunit: WorkUnit
    slot_name: str
    provider: str = ""
    model: str = ""
    topology: str = ""
    confidence: float = 0.0
    required_capabilities: tuple[str, ...] = ()
    evaluator: str = ""
    reason: str = ""
    contract: str = ""


def resolve_route(
    config: object,
    *,
    prompt: str,
    route: str = "",
    workunit_kind: str = "",
    command: str = "",
    target: str = "",
    evidence: str = "",
    name: str = "",
    topology: str = "",
    required_capabilities: tuple[str, ...] = (),
    registry: CapabilityRegistry | None = None,
) -> RouteDecision | None:
    """Resolve a task route when routing is enabled or explicitly requested."""
    routing_cfg = getattr(config, "agent_routing", None)
    enabled = bool(getattr(routing_cfg, "enabled", True))
    if route != "auto" and not enabled:
        return None

    kind = detect_workunit_kind(
        explicit=workunit_kind,
        command=command,
        prompt=prompt,
        target=target,
        evidence=evidence,
    )
    if kind is None:
        return None

    requirements = requirements_for_kind(kind)
    if required_capabilities:
        requirements = type(requirements)(
            capabilities=tuple(required_capabilities),
            avoid_capabilities=requirements.avoid_capabilities,
            can_edit=requirements.can_edit,
            evaluator_required=requirements.evaluator_required,
            promotion_allowed=requirements.promotion_allowed,
        )
    unit = WorkUnit(
        kind=kind,
        name=name,
        prompt=prompt,
        command=command,
        target=target,
        evidence=evidence,
        topology=topology,
        requirements=requirements,
    )
    registry = registry or _registry_from_config(config)
    ranked = rank_slots(registry.candidates(mode="background"), unit)
    if not ranked:
        return None

    best = ranked[0]
    requested_topology = normalize_topology(topology)
    selected_topology = (
        requested_topology
        or best.slot.topology_preferences.get(kind.value, "")
        or default_topology_for_kind(kind)
    )
    confidence = max(0.0, min(1.0, best.score))
    evaluator = "foreground" if requirements.evaluator_required else ""
    return RouteDecision(
        workunit=unit,
        slot_name=best.slot.name,
        provider=best.slot.provider,
        model=best.slot.model,
        topology=selected_topology,
        confidence=confidence,
        required_capabilities=requirements.capabilities,
        evaluator=evaluator,
        reason=f"{best.reason}; selected topology={selected_topology or 'background_single'}",
        contract=build_workunit_contract(unit),
    )


def _registry_from_config(config: object) -> CapabilityRegistry:
    routing_cfg = getattr(config, "agent_routing", None)
    path = str(getattr(routing_cfg, "capability_registry", "") or "")
    if path:
        if not Path(path).is_absolute():
            home = Path(str(getattr(config, "controlmesh_home", "~/.controlmesh"))).expanduser()
            path = str(home / path)
        return load_capability_registry(path, config)
    return default_capability_registry(config)
