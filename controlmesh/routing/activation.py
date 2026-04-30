"""Activation policy layer: strict routing rules evaluated before capability scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Policy dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivationPolicy:
    """A strong activation rule evaluated before capability scoring.

    Policies are matched against the task submission context (workunit kind,
    command, prompt, name, phase metadata).  When matched, the policy's
    intent is resolved and passed to the routing layer to constrain or
    override the normal capability-based scoring.

    Fields:
        execution:          background_required | background_preferred | foreground_required
        preferred_slots:    slot names to deprioritize others
        deny_slots:         slot names that cannot be selected
        deny_providers:     provider names that cannot be selected
        max_cost_class:     cheapest acceptable cost class
        topology:           forced topology override
        requires_foreground_approval: force evaluator requirement
        allow_explicit_override: if False, policy cannot be bypassed by explicit route=
    """

    name: str
    execution: str = "background_preferred"  # background_required | background_preferred | foreground_required
    match: dict[str, Any] = field(default_factory=dict)  # criteria for matching
    preferred_slots: tuple[str, ...] = ()
    deny_slots: tuple[str, ...] = ()
    deny_providers: tuple[str, ...] = ()
    max_cost_class: str = ""  # cheap | standard | premium
    topology: str = ""
    requires_foreground_approval: bool = False
    allow_explicit_override: bool = True


# ---------------------------------------------------------------------------
# Intent (resolved policy output)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivationIntent:
    """Resolved activation policy intent — applied to routing before scoring.

    Returned by :func:`resolve_activation_intent`.  Carries the matched
    policy name and the routing constraints to apply.
    """

    matched_policy: str = ""
    execution_mode: str = "background_preferred"
    preferred_slots: tuple[str, ...] = ()
    deny_slots: tuple[str, ...] = ()
    deny_providers: tuple[str, ...] = ()
    max_cost_class: str = ""
    topology: str = ""
    requires_foreground_approval: bool = False
    allow_explicit_override: bool = True

    # Convenience: was an explicit user directive (e.g. route=foreground) seen?
    explicit_route: str = ""


# ---------------------------------------------------------------------------
# Policy loader
# ---------------------------------------------------------------------------


def load_activation_policies(path: str | Path) -> tuple[ActivationPolicy, ...]:
    """Load activation policies from a YAML file.

    If the file does not exist or is malformed, returns an empty tuple.
    """
    registry_path = Path(path).expanduser()
    if not registry_path.is_file():
        return ()

    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ()

    if not isinstance(raw, dict):
        return ()

    policies: list[ActivationPolicy] = []
    raw_policies = raw.get("activation_policies", {})
    if not isinstance(raw_policies, dict):
        return ()

    for name, payload in raw_policies.items():
        if not isinstance(name, str) or not isinstance(payload, dict):
            continue
        policy = _policy_from_mapping(name, payload)
        if policy is not None:
            policies.append(policy)

    return tuple(policies)


def _policy_from_mapping(name: str, payload: dict[str, Any]) -> ActivationPolicy | None:
    """Build an ActivationPolicy from a YAML mapping."""
    execution = str(payload.get("execution", "background_preferred"))
    if execution not in {"background_required", "background_preferred", "foreground_required"}:
        execution = "background_preferred"

    match_criteria = payload.get("match", {})
    if not isinstance(match_criteria, dict):
        match_criteria = {}

    preferred_slots = _parse_tuple_field(payload.get("preferred_slots"))
    deny_slots = _parse_tuple_field(payload.get("deny_slots"))
    deny_providers = _parse_tuple_field(payload.get("deny_providers"))

    return ActivationPolicy(
        name=name,
        execution=execution,
        match=match_criteria,
        preferred_slots=preferred_slots,
        deny_slots=deny_slots,
        deny_providers=deny_providers,
        max_cost_class=str(payload.get("max_cost_class", "")),
        topology=str(payload.get("topology", "")),
        requires_foreground_approval=bool(payload.get("requires_foreground_approval", False)),
        allow_explicit_override=bool(payload.get("allow_explicit_override", True)),
    )


def _parse_tuple_field(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw if str(item))
    return ()


# ---------------------------------------------------------------------------
# Policy matching
# ---------------------------------------------------------------------------


def resolve_activation_intent(
    policies: tuple[ActivationPolicy, ...],
    *,
    workunit_kind: str = "",
    command: str = "",
    prompt: str = "",
    name: str = "",
    phase_id: str = "",
    phase_title: str = "",
    plan_id: str = "",
    explicit_route: str = "",
) -> ActivationIntent:
    """Evaluate activation policies in priority order and return the first match.

    Priority order:
    1. safety/security reject (not yet implemented)
    2. explicit user directive (handled by caller via explicit_route)
    3. repo-local policy (first match wins among repo policies)
    4. user activation policy (first match wins among user policies)
    5. agent activation rules (first match wins)

    Currently implemented: flat scan of all policies in order. When an
    explicit route is present, it bypasses only policies that allow it.
    """
    if not policies:
        return ActivationIntent(explicit_route=explicit_route)

    for policy in policies:
        if _policy_matches(policy, workunit_kind, command, prompt, name, phase_id, phase_title, plan_id):
            # Explicit routes bypass only policies that allow override.
            if policy.allow_explicit_override and explicit_route:
                return ActivationIntent(explicit_route=explicit_route)
            return ActivationIntent(
                matched_policy=policy.name,
                execution_mode=policy.execution,
                preferred_slots=policy.preferred_slots,
                deny_slots=policy.deny_slots,
                deny_providers=policy.deny_providers,
                max_cost_class=policy.max_cost_class,
                topology=policy.topology,
                requires_foreground_approval=policy.requires_foreground_approval,
                allow_explicit_override=policy.allow_explicit_override,
                explicit_route=explicit_route,
            )

    return ActivationIntent(explicit_route=explicit_route)


def _policy_matches(
    policy: ActivationPolicy,
    workunit_kind: str,
    command: str,
    prompt: str,
    name: str,
    phase_id: str,
    phase_title: str,
    plan_id: str,
) -> bool:
    """Return True if the policy's match criteria are satisfied."""
    criteria = policy.match
    if not criteria:
        return False

    # workunit_kind match
    kinds = criteria.get("workunit_kinds", [])
    if kinds:
        kind_list = [kinds] if isinstance(kinds, str) else list(kinds)
        if not workunit_kind or workunit_kind not in kind_list:
            return False

    # command regex match
    command_patterns = criteria.get("command_patterns", [])
    if command_patterns:
        patterns = [command_patterns] if isinstance(command_patterns, str) else command_patterns
        if command:
            if not any(_safe_regex_search(p, command) for p in patterns):
                return False
        else:
            return False

    # prompt substring match
    prompt_substrings = criteria.get("prompt_contains", [])
    if prompt_substrings:
        substrings = [prompt_substrings] if isinstance(prompt_substrings, str) else prompt_substrings
        if not any(sub.lower() in prompt.lower() for sub in substrings):
            return False

    # name prefix/suffix/exact match
    name_match = criteria.get("name_starts_with", "")
    if name_match and not name.startswith(name_match):
        return False
    name_match = criteria.get("name_ends_with", "")
    if name_match and not name.endswith(name_match):
        return False
    name_match = criteria.get("name_equals", "")
    if name_match and name != name_match:
        return False

    # phase metadata
    if phase_id:
        phase_ids = criteria.get("phase_ids", [])
        if phase_ids:
            ids = [phase_ids] if isinstance(phase_ids, str) else list(phase_ids)
            if phase_id not in ids:
                return False
    elif criteria.get("phase_ids", []):
        return False

    phase_titles = criteria.get("phase_titles", [])
    if phase_titles:
        titles = [phase_titles] if isinstance(phase_titles, str) else list(phase_titles)
        if not phase_title or not any(t.lower() in phase_title.lower() for t in titles):
            return False

    plan_ids = criteria.get("plan_ids", [])
    if plan_ids:
        ids = [plan_ids] if isinstance(plan_ids, str) else list(plan_ids)
        if not plan_id or plan_id not in ids:
            return False

    return True


def _safe_regex_search(pattern: str, text: str) -> bool:
    """Safely compile and match a regex, returning False on any error."""
    try:
        return bool(re.search(pattern, text, re.IGNORECASE))
    except re.error:
        return False


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------


def resolve_activation_policy_path(config: object, home: Path) -> Path:
    """Resolve the activation policy file path from config.

    Relative paths are resolved against ``home``.
    """
    routing_cfg = getattr(config, "agent_routing", None)
    filename = str(getattr(routing_cfg, "activation_policy_file", "") or "")
    if not filename:
        return Path()
    if Path(filename).is_absolute():
        return Path(filename)
    return home / filename
