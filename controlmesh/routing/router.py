"""Route WorkUnits to provider/model/topology decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from controlmesh.routing.activation import ActivationIntent
from controlmesh.routing.capabilities import (
    AgentSlot,
    CapabilityRegistry,
    default_capability_registry,
    load_capability_registry,
)
from controlmesh.routing.policy import (
    default_topology_for_kind,
    detect_workunit_kind,
    normalize_topology,
)
from controlmesh.routing.scorer import RouteScoringContext, rank_slots
from controlmesh.routing.scorer import SlotRuntimeState
from controlmesh.routing.workunit import (
    WorkUnit,
    WorkUnitKind,
    build_workunit_contract,
    requirements_for_kind,
)

_COST_RANK: dict[str, int] = {"cheap": 0, "standard": 1, "premium": 2}


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
    scoring_context: RouteScoringContext | None = None,
    slot_state_resolver: Callable[[AgentSlot], SlotRuntimeState | None] | None = None,
    activation_intent: ActivationIntent | None = None,
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
    routing_cfg = getattr(config, "agent_routing", None)
    overrides = _workunit_overrides(routing_cfg, kind)

    # Merge activation intent constraints into overrides (policy takes precedence over scoring)
    # Foreground-required is a hard block for auto-routing: if route=auto and the matched
    # policy says foreground_required, we cannot satisfy it in the auto background path,
    # so return None immediately rather than scoring against background slots.
    if activation_intent and activation_intent.matched_policy:
        if activation_intent.execution_mode == "foreground_required":
            # Policy blocks auto background routing — nothing in the auto path can satisfy
            # a foreground-required task, so stop here with no route decision.
            return None
        _merge_activation_intent(overrides, activation_intent)

    override_capabilities = _tuple_field(overrides, "capabilities")
    if override_capabilities:
        required_capabilities = override_capabilities
    override_can_edit = requirements.can_edit
    if "can_edit" in overrides:
        override_can_edit = _bool_field(overrides, "can_edit", bool(requirements.can_edit))
    if "allowed_edit" in overrides:
        override_can_edit = _bool_field(overrides, "allowed_edit", bool(requirements.can_edit))
    evaluator_required = _bool_field(
        overrides,
        "requires_foreground_approval",
        requirements.evaluator_required,
    )
    if required_capabilities or overrides:
        requirements = type(requirements)(
            capabilities=tuple(required_capabilities or requirements.capabilities),
            avoid_capabilities=requirements.avoid_capabilities,
            can_edit=override_can_edit,
            evaluator_required=evaluator_required,
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
    candidates = _apply_subagent_policy(
        registry.candidates(mode="background"),
        routing_cfg=routing_cfg,
        overrides=overrides,
    )
    if slot_state_resolver is not None:
        states = dict((scoring_context or RouteScoringContext()).slot_state)
        for slot in candidates:
            state = slot_state_resolver(slot)
            if state is not None:
                states[slot.name] = state
        scoring_context = RouteScoringContext(slot_state=states)
    ranked = rank_slots(candidates, unit, scoring_context)
    if not ranked:
        return None

    best = ranked[0]
    min_confidence = float(getattr(routing_cfg, "min_confidence", 0.0) or 0.0)
    confidence = max(0.0, min(1.0, best.score))
    if confidence < min_confidence:
        return None
    requested_topology = normalize_topology(topology)
    selected_topology = (
        requested_topology
        or normalize_topology(str(overrides.get("topology", "") or ""))
        or best.slot.topology_preferences.get(kind.value, "")
        or default_topology_for_kind(kind)
    )
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


def _workunit_overrides(routing_cfg: object, kind: WorkUnitKind) -> dict[str, object]:
    raw = getattr(routing_cfg, "workunit_overrides", {}) if routing_cfg is not None else {}
    if not isinstance(raw, dict):
        return {}
    payload = raw.get(kind.value, {})
    return payload if isinstance(payload, dict) else {}


def _tuple_field(payload: dict[str, object], key: str) -> tuple[str, ...]:
    raw = payload.get(key, ())
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list | tuple):
        return tuple(str(item) for item in raw if str(item))
    return ()


def _bool_field(payload: dict[str, object], key: str, default: bool) -> bool:
    raw = payload.get(key, default)
    return raw if isinstance(raw, bool) else default


def _merge_activation_intent(
    overrides: dict[str, object],
    intent: ActivationIntent,
) -> None:
    """Merge activation intent constraints into the overrides dict in-place.

    Activation policy constraints take precedence over workunit-level overrides
    because the policy layer is evaluated before scoring.
    """
    if intent.preferred_slots:
        overrides["preferred_slots"] = list(intent.preferred_slots)
    if intent.deny_slots:
        overrides["deny_slots"] = list(intent.deny_slots)
    if intent.deny_providers:
        overrides["deny_providers"] = list(intent.deny_providers)
    if intent.max_cost_class:
        overrides["max_cost_class"] = intent.max_cost_class
    if intent.topology:
        overrides["topology"] = intent.topology
    if intent.requires_foreground_approval:
        overrides["requires_foreground_approval"] = True


def _apply_subagent_policy(
    slots: tuple[AgentSlot, ...],
    *,
    routing_cfg: object,
    overrides: dict[str, object],
) -> tuple[AgentSlot, ...]:
    policy = getattr(routing_cfg, "subagent_policy", {}) if routing_cfg is not None else {}
    if not isinstance(policy, dict):
        policy = {}

    deny_providers = set(_tuple_field(policy, "deny_providers")) | set(
        _tuple_field(overrides, "deny_providers")
    )
    allow_providers = set(_tuple_field(policy, "allow_providers")) | set(
        _tuple_field(overrides, "allow_providers")
    )
    deny_slots = set(_tuple_field(policy, "deny_slots")) | set(_tuple_field(overrides, "deny_slots"))
    allow_slots = set(_tuple_field(policy, "allow_slots")) | set(_tuple_field(overrides, "allow_slots"))
    preferred_slots = set(_tuple_field(overrides, "preferred_slots"))
    deny_cost_classes = set(_tuple_field(policy, "deny_cost_classes")) | set(
        _tuple_field(overrides, "deny_cost_classes")
    )
    max_cost_class = str(overrides.get("max_cost_class") or policy.get("max_cost_class") or "")

    filtered: list[AgentSlot] = []
    for slot in slots:
        if not slot.allow_subagent:
            continue
        if allow_slots and slot.name not in allow_slots:
            continue
        if slot.name in deny_slots:
            continue
        if allow_providers and slot.provider not in allow_providers:
            continue
        if slot.provider in deny_providers:
            continue
        if slot.cost_class in deny_cost_classes:
            continue
        if max_cost_class and _COST_RANK.get(slot.cost_class, 99) > _COST_RANK.get(max_cost_class, 99):
            continue
        filtered.append(slot)

    if preferred_slots:
        preferred = [slot for slot in filtered if slot.name in preferred_slots]
        rest = [slot for slot in filtered if slot.name not in preferred_slots]
        filtered = [*preferred, *rest]

    return tuple(filtered)
