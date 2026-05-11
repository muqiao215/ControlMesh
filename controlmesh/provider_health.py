"""Structured provider compatibility, readiness, and bootstrap health helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from controlmesh.cli.auth import AuthResult, AuthStatus
from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.provider_binding import normalize_provider_name, validate_provider_model_binding


class CompatibilityStatus(StrEnum):
    """Provider/model compatibility result."""

    OK = "ok"
    INVALID = "invalid"


class ReadinessStatus(StrEnum):
    """Runtime readiness status for one provider binding."""

    READY = "ready"
    DEGRADED = "degraded"
    NOT_READY = "not_ready"


@dataclass(frozen=True, slots=True)
class ConfigMigrationEvent:
    """One explicit config normalization or migration event."""

    field: str
    before: str
    after: str
    reason: str
    applied: bool = True


@dataclass(frozen=True, slots=True)
class ProviderCheck:
    """One structured compatibility or readiness check."""

    name: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class CompatibilityAssessment:
    """Structured provider/model compatibility assessment."""

    requested_provider: str
    requested_model: str
    normalized_provider: str
    normalized_model: str
    inferred_provider: str
    status: CompatibilityStatus
    checks: tuple[ProviderCheck, ...]
    summary: str
    suggested_fix: str = ""
    suggested_provider: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status == CompatibilityStatus.OK


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """Structured readiness state for one configured provider binding."""

    provider: str
    model: str
    compatibility: CompatibilityAssessment
    auth_result: AuthResult | None
    status: ReadinessStatus
    checks: tuple[ProviderCheck, ...]
    summary: str
    suggested_fixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BootstrapHealth:
    """Top-level startup health used by runtime gating and doctor output."""

    status: ReadinessStatus
    configured_provider: str
    configured_model: str
    default_provider: str
    default_model: str
    readiness: ProviderReadiness
    fallback_provider: str = ""
    fallback_model: str = ""
    migration_events: tuple[ConfigMigrationEvent, ...] = ()
    checks: tuple[ProviderCheck, ...] = ()
    summary: str = ""
    user_message: str = ""

    @property
    def is_ready(self) -> bool:
        return self.status == ReadinessStatus.READY


@dataclass(frozen=True, slots=True)
class FleetDoctorHostResult:
    """One host result for fleet provider doctor surfaces."""

    host: str
    ok: bool
    output: str
    error: str = ""


FallbackSurface = Literal[
    "normal_message",
    "streaming_message",
    "background_task",
    "native_provider_command",
    "release_workunit",
    "git_write",
    "publish",
]


_COMPATIBILITY_ALLOWED_PREFIXES: dict[str, tuple[str, ...]] = {
    "claude": ("claude",),
    "claw": ("claude",),
    "codex": ("codex",),
    "gemini": ("gemini",),
}


def assess_provider_model_binding(
    provider: str | None,
    model: str | None,
    *,
    model_provider_resolver,
) -> CompatibilityAssessment:
    """Return structured compatibility for one provider/model pair."""
    requested_provider = (provider or "").strip()
    requested_model = (model or "").strip()
    normalized_provider = normalize_provider_name(provider)
    normalized_model = requested_model
    inferred_provider = (
        model_provider_resolver(normalized_model) if normalized_model else normalized_provider
    )
    if "/" in normalized_model and normalized_provider in {"claude", "claw", "codex", "gemini"}:
        inferred_provider = "opencode"

    try:
        normalized_provider, normalized_model = validate_provider_model_binding(
            normalized_provider,
            normalized_model,
            model_provider_resolver=model_provider_resolver,
        )
    except ValueError as exc:
        suggested_provider = _suggest_provider_for_mismatch(normalized_provider, inferred_provider)
        suggested_fix = ""
        if suggested_provider:
            suggested_fix = (
                f"Set provider={suggested_provider} for model={requested_model or normalized_model}."
            )
        return CompatibilityAssessment(
            requested_provider=requested_provider,
            requested_model=requested_model,
            normalized_provider=normalized_provider,
            normalized_model=normalized_model,
            inferred_provider=inferred_provider,
            status=CompatibilityStatus.INVALID,
            checks=(
                ProviderCheck(
                    name="provider_model_binding",
                    status="failed",
                    message=str(exc),
                ),
            ),
            summary=(
                f"Configured provider/model binding is invalid: "
                f"{requested_provider or '<empty>'} + {requested_model or '<empty>'}."
            ),
            suggested_fix=suggested_fix,
            suggested_provider=suggested_provider,
        )

    allowed_prefixes = _COMPATIBILITY_ALLOWED_PREFIXES.get(normalized_provider)
    if allowed_prefixes is not None and inferred_provider not in allowed_prefixes:
        suggested_provider = _suggest_provider_for_mismatch(normalized_provider, inferred_provider)
        suggested_fix = ""
        if suggested_provider:
            suggested_fix = (
                f"Set provider={suggested_provider} for model={normalized_model or requested_model}."
            )
        return CompatibilityAssessment(
            requested_provider=requested_provider,
            requested_model=requested_model,
            normalized_provider=normalized_provider,
            normalized_model=normalized_model,
            inferred_provider=inferred_provider,
            status=CompatibilityStatus.INVALID,
            checks=(
                ProviderCheck(
                    name="provider_model_binding",
                    status="failed",
                    message=(
                        f"provider={normalized_provider} does not support model={normalized_model}; "
                        f"inferred provider={inferred_provider}"
                    ),
                ),
            ),
            summary=(
                f"Configured provider/model binding is invalid: "
                f"{normalized_provider} cannot serve {normalized_model}."
            ),
            suggested_fix=suggested_fix,
            suggested_provider=suggested_provider,
        )

    return CompatibilityAssessment(
        requested_provider=requested_provider,
        requested_model=requested_model,
        normalized_provider=normalized_provider,
        normalized_model=normalized_model,
        inferred_provider=inferred_provider,
        status=CompatibilityStatus.OK,
        checks=(
            ProviderCheck(
                name="provider_model_binding",
                status="ok",
                message=f"{normalized_provider} + {normalized_model or '<default>'}",
            ),
        ),
        summary=f"Configured provider/model binding is valid: {normalized_provider} + {normalized_model}.",
    )


def assess_provider_readiness(
    *,
    provider: str | None,
    model: str | None,
    auth_results: dict[str, AuthResult],
    model_provider_resolver,
) -> ProviderReadiness:
    """Assess effective readiness for the configured default provider binding."""
    compatibility = assess_provider_model_binding(
        provider,
        model,
        model_provider_resolver=model_provider_resolver,
    )
    checks: list[ProviderCheck] = list(compatibility.checks)
    fixes: list[str] = []
    auth_result = auth_results.get(compatibility.normalized_provider)

    if not compatibility.is_valid:
        if compatibility.suggested_fix:
            fixes.append(compatibility.suggested_fix)
        return ProviderReadiness(
            provider=compatibility.normalized_provider,
            model=compatibility.normalized_model,
            compatibility=compatibility,
            auth_result=auth_result,
            status=ReadinessStatus.NOT_READY,
            checks=tuple(checks),
            summary=compatibility.summary,
            suggested_fixes=tuple(fixes),
        )

    if auth_result is None:
        checks.append(
            ProviderCheck(
                name="provider_auth",
                status="failed",
                message=f"No auth probe result for provider={compatibility.normalized_provider}.",
            )
        )
        fixes.append(f"Run `controlmesh doctor providers` to inspect {compatibility.normalized_provider}.")
        return ProviderReadiness(
            provider=compatibility.normalized_provider,
            model=compatibility.normalized_model,
            compatibility=compatibility,
            auth_result=None,
            status=ReadinessStatus.NOT_READY,
            checks=tuple(checks),
            summary=f"{compatibility.normalized_provider} has no auth/readiness probe result.",
            suggested_fixes=tuple(fixes),
        )

    if auth_result.status == AuthStatus.AUTHENTICATED:
        checks.append(
            ProviderCheck(
                name="provider_auth",
                status="ok",
                message=f"{compatibility.normalized_provider} authenticated",
            )
        )
        return ProviderReadiness(
            provider=compatibility.normalized_provider,
            model=compatibility.normalized_model,
            compatibility=compatibility,
            auth_result=auth_result,
            status=ReadinessStatus.READY,
            checks=tuple(checks),
            summary=(
                f"Default provider is ready: {compatibility.normalized_provider} + "
                f"{compatibility.normalized_model}."
            ),
        )

    if auth_result.status == AuthStatus.INSTALLED:
        diagnostic = auth_result.diagnostic or "Provider is installed but not authenticated."
        checks.append(
            ProviderCheck(
                name="provider_auth",
                status="failed",
                message=diagnostic,
            )
        )
        fixes.append(
            f"Authenticate provider={compatibility.normalized_provider} or switch `/model` to a ready provider."
        )
        return ProviderReadiness(
            provider=compatibility.normalized_provider,
            model=compatibility.normalized_model,
            compatibility=compatibility,
            auth_result=auth_result,
            status=ReadinessStatus.NOT_READY,
            checks=tuple(checks),
            summary=(
                f"Default provider is installed but not ready: "
                f"{compatibility.normalized_provider} + {compatibility.normalized_model}."
            ),
            suggested_fixes=tuple(fixes),
        )

    checks.append(
        ProviderCheck(
            name="provider_auth",
            status="failed",
            message=f"Provider binary/auth state not found for {compatibility.normalized_provider}.",
        )
    )
    fixes.append(
        f"Install or authenticate provider={compatibility.normalized_provider}, "
        "or switch `/model` to a ready provider."
    )
    return ProviderReadiness(
        provider=compatibility.normalized_provider,
        model=compatibility.normalized_model,
        compatibility=compatibility,
        auth_result=auth_result,
        status=ReadinessStatus.NOT_READY,
        checks=tuple(checks),
        summary=(
            f"Default provider is not installed or not authenticated: "
            f"{compatibility.normalized_provider} + {compatibility.normalized_model}."
        ),
        suggested_fixes=tuple(fixes),
    )


def assess_bootstrap_health(
    *,
    configured_provider: str,
    configured_model: str,
    default_provider: str,
    default_model: str,
    auth_results: dict[str, AuthResult],
    model_provider_resolver,
    migration_events: tuple[ConfigMigrationEvent, ...] = (),
) -> BootstrapHealth:
    """Compute top-level startup health for the default agent runtime."""
    readiness = assess_provider_readiness(
        provider=default_provider,
        model=default_model,
        auth_results=auth_results,
        model_provider_resolver=model_provider_resolver,
    )
    fallback_provider = ""
    fallback_model = ""
    if readiness.status == ReadinessStatus.NOT_READY:
        fallback_provider, fallback_model = _choose_ready_fallback(
            auth_results=auth_results,
            model_provider_resolver=model_provider_resolver,
            exclude_provider=readiness.provider,
        )
        if fallback_provider and fallback_model:
            readiness = ProviderReadiness(
                provider=readiness.provider,
                model=readiness.model,
                compatibility=readiness.compatibility,
                auth_result=readiness.auth_result,
                status=ReadinessStatus.DEGRADED,
                checks=readiness.checks,
                summary=(
                    f"{readiness.summary} Falling back to {fallback_provider} + {fallback_model} "
                    "for normal chat."
                ),
                suggested_fixes=readiness.suggested_fixes,
            )
    checks: list[ProviderCheck] = list(readiness.checks)
    if migration_events:
        checks.extend(
            ProviderCheck(
                name=f"config_migration:{event.field}",
                status="ok" if event.applied else "pending",
                message=f"{event.field}: {event.before} -> {event.after} ({event.reason})",
            )
            for event in migration_events
        )
    return BootstrapHealth(
        status=readiness.status,
        configured_provider=configured_provider,
        configured_model=configured_model,
        default_provider=default_provider,
        default_model=default_model,
        readiness=readiness,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        migration_events=migration_events,
        checks=tuple(checks),
        summary=readiness.summary,
        user_message=render_bootstrap_gate_message(
            readiness,
            configured_provider=configured_provider,
            configured_model=configured_model,
            default_provider=default_provider,
            default_model=default_model,
        ),
    )


def apply_config_migrations(raw: dict[str, object]) -> tuple[dict[str, object], tuple[ConfigMigrationEvent, ...], bool]:
    """Apply explicit, safe config normalizations and return migration events."""
    merged = dict(raw)
    changed = False
    events: list[ConfigMigrationEvent] = []

    raw_provider = raw.get("provider")
    if isinstance(raw_provider, str):
        normalized = normalize_provider_name(raw_provider)
        trimmed = normalized.strip()
        if trimmed and trimmed != raw_provider:
            merged["provider"] = trimmed
            changed = True
            events.append(
                ConfigMigrationEvent(
                    field="provider",
                    before=raw_provider,
                    after=trimmed,
                    reason="normalized provider alias",
                )
            )

    raw_model = raw.get("model")
    if isinstance(raw_model, str):
        trimmed_model = raw_model.strip()
        if trimmed_model != raw_model:
            merged["model"] = trimmed_model
            changed = True
            events.append(
                ConfigMigrationEvent(
                    field="model",
                    before=raw_model,
                    after=trimmed_model,
                    reason="trimmed model identifier",
                )
            )

    return merged, tuple(events), changed


def render_bootstrap_health_lines(health: BootstrapHealth) -> list[str]:
    """Render compact bootstrap-health lines for status and doctor surfaces."""
    lines = [
        f"Bootstrap health: {health.status.value}",
        (
            f"Configured binding: {health.configured_provider or '<empty>'} / "
            f"{health.configured_model or '<empty>'}"
        ),
        f"Default runtime: {health.default_provider} / {health.default_model or '<default>'}",
        f"Summary: {health.summary}",
    ]
    if health.fallback_provider and health.fallback_model:
        lines.append(f"Fallback runtime: {health.fallback_provider} / {health.fallback_model}")
    if health.readiness.suggested_fixes:
        lines.append("Suggested fixes:")
        lines.extend(f"  - {fix}" for fix in health.readiness.suggested_fixes)
    return lines


def render_doctor_providers_text(health: BootstrapHealth, auth_results: dict[str, AuthResult]) -> str:
    """Render the single-host `doctor providers` report."""
    readiness = health.readiness
    lines = [
        "Provider doctor",
        "",
        "provider/model matrix:",
        f"  provider: {health.configured_provider or '<empty>'}",
        f"  model: {health.configured_model or '<empty>'}",
        f"  status: {readiness.compatibility.status.value}",
    ]
    if readiness.compatibility.suggested_fix:
        lines.append(f"  suggested_fix: {readiness.compatibility.suggested_fix}")
    lines.extend(["", "auth:"])
    for provider in sorted(auth_results):
        result = auth_results[provider]
        diag = f" ({result.diagnostic})" if result.diagnostic else ""
        lines.append(f"  {provider}: {result.status.value}{diag}")
    lines.extend(
        [
            "",
            "readiness:",
            f"  default agent: {health.status.value}",
            f"  summary: {health.summary}",
        ]
    )
    if health.fallback_provider and health.fallback_model:
        lines.append(f"  fallback: {health.fallback_provider} / {health.fallback_model}")
    if health.migration_events:
        lines.extend(["", "migrations:"])
        lines.extend(
            f"  {event.field}: {event.before} -> {event.after} ({event.reason})"
            for event in health.migration_events
        )
    if readiness.suggested_fixes:
        lines.extend(["", "suggested_fixes:"])
        lines.extend(f"  - {fix}" for fix in readiness.suggested_fixes)
    return "\n".join(lines)


def render_fallback_notice(
    health: BootstrapHealth,
    *,
    surface: FallbackSurface,
) -> str:
    """Render the user-visible degraded fallback notice."""
    return (
        "Default runtime unavailable.\n"
        f"Surface: {surface}\n"
        f"Configured: {health.default_provider} / {health.default_model or '<default>'}\n"
        f"Fallback: {health.fallback_provider} / {health.fallback_model}\n"
        f"Reason: {health.readiness.summary}"
    )


def render_bootstrap_gate_message(
    readiness: ProviderReadiness,
    *,
    configured_provider: str,
    configured_model: str,
    default_provider: str,
    default_model: str,
) -> str:
    """Render the user-facing message for not-ready/degraded startup states."""
    lines = [
        "Agent default runtime is not fully ready.",
        f"Configured binding: {configured_provider or '<empty>'} / {configured_model or '<empty>'}",
        f"Default runtime: {default_provider} / {default_model or '<default>'}",
        f"Problem: {readiness.summary}",
    ]
    if readiness.status == ReadinessStatus.DEGRADED:
        lines.insert(1, "Normal chat will continue in degraded mode through a fallback provider.")
    if readiness.suggested_fixes:
        lines.append("Fix:")
        lines.extend(f"- {fix}" for fix in readiness.suggested_fixes)
    lines.append("Use `/status`, `/diagnose`, or `controlmesh doctor providers` for details.")
    return "\n".join(lines)


def _suggest_provider_for_mismatch(provider: str, inferred_provider: str) -> str:
    """Return the most conservative provider suggestion for a mismatch."""
    if inferred_provider == "opencode":
        return "opencode"
    if inferred_provider and inferred_provider != provider:
        return inferred_provider
    return ""


def bootstrap_health_to_dict(
    health: BootstrapHealth,
    *,
    fallback_policy_summary: str = "",
) -> dict[str, object]:
    """Serialize bootstrap health for runtime persistence."""
    auth_result = health.readiness.auth_result
    return {
        "status": health.status.value,
        "configured_provider": health.configured_provider,
        "configured_model": health.configured_model,
        "default_provider": health.default_provider,
        "default_model": health.default_model,
        "summary": health.summary,
        "user_message": health.user_message,
        "readiness": {
            "provider": health.readiness.provider,
            "model": health.readiness.model,
            "status": health.readiness.status.value,
            "summary": health.readiness.summary,
            "suggested_fixes": list(health.readiness.suggested_fixes),
            "compatibility": {
                "requested_provider": health.readiness.compatibility.requested_provider,
                "requested_model": health.readiness.compatibility.requested_model,
                "normalized_provider": health.readiness.compatibility.normalized_provider,
                "normalized_model": health.readiness.compatibility.normalized_model,
                "inferred_provider": health.readiness.compatibility.inferred_provider,
                "status": health.readiness.compatibility.status.value,
                "summary": health.readiness.compatibility.summary,
                "suggested_fix": health.readiness.compatibility.suggested_fix,
                "suggested_provider": health.readiness.compatibility.suggested_provider,
                "checks": [
                    {"name": check.name, "status": check.status, "message": check.message}
                    for check in health.readiness.compatibility.checks
                ],
            },
            "auth_result": (
                {
                    "provider": auth_result.provider,
                    "status": auth_result.status.value,
                    "diagnostic": auth_result.diagnostic,
                }
                if auth_result is not None
                else None
            ),
            "checks": [
                {"name": check.name, "status": check.status, "message": check.message}
                for check in health.readiness.checks
            ],
        },
        "migration_events": [
            {
                "field": event.field,
                "before": event.before,
                "after": event.after,
                "reason": event.reason,
                "applied": event.applied,
            }
            for event in health.migration_events
        ],
        "fallback_provider": health.fallback_provider,
        "fallback_model": health.fallback_model,
        "fallback_policy_summary": fallback_policy_summary,
        "checks": [
            {"name": check.name, "status": check.status, "message": check.message}
            for check in health.checks
        ],
        "updated_at": datetime.now(UTC).isoformat(),
    }


def save_bootstrap_health(
    runtime_health_path: Path,
    health: BootstrapHealth,
    *,
    fallback_policy_summary: str = "",
) -> None:
    """Persist bootstrap health into the runtime health ledger."""
    data = load_json(runtime_health_path)
    if not isinstance(data, dict):
        data = {}
    data["bootstrap"] = bootstrap_health_to_dict(
        health,
        fallback_policy_summary=fallback_policy_summary,
    )
    data["updated_at"] = datetime.now(UTC).timestamp()
    atomic_json_save(runtime_health_path, data)


def load_bootstrap_health_snapshot(runtime_health_path: Path) -> dict[str, object] | None:
    """Load persisted bootstrap health snapshot, if present."""
    data = load_json(runtime_health_path)
    if not isinstance(data, dict):
        return None
    snapshot = data.get("bootstrap")
    return snapshot if isinstance(snapshot, dict) else None


def backup_config_file(config_path: Path, backups_dir: Path) -> Path:
    """Create a timestamped backup of config.json before a migration write."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"config.{timestamp}.json"
    content = config_path.read_text(encoding="utf-8")
    atomic_text_save(target, content)
    return target


def append_migration_journal(
    journal_path: Path,
    *,
    config_path: Path,
    backup_path: Path | None,
    events: tuple[ConfigMigrationEvent, ...],
) -> None:
    """Append one config migration journal record."""
    if not events:
        return
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "config_path": str(config_path),
        "backup_path": str(backup_path) if backup_path is not None else "",
        "events": [
            {
                "field": event.field,
                "before": event.before,
                "after": event.after,
                "reason": event.reason,
                "applied": event.applied,
            }
            for event in events
        ],
    }
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _choose_ready_fallback(
    *,
    auth_results: dict[str, AuthResult],
    model_provider_resolver,
    exclude_provider: str,
) -> tuple[str, str]:
    candidates = (
        ("claude", "sonnet"),
        ("codex", "gpt-5.5"),
        ("gemini", "auto"),
        ("opencode", "openai/gpt-4.1"),
        ("claw", "sonnet"),
    )
    for provider, model in candidates:
        if provider == exclude_provider:
            continue
        auth = auth_results.get(provider)
        if auth is None or auth.status != AuthStatus.AUTHENTICATED:
            continue
        assessment = assess_provider_model_binding(
            provider,
            model,
            model_provider_resolver=model_provider_resolver,
        )
        if assessment.is_valid:
            return provider, model
    return "", ""
