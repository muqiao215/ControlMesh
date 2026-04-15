"""Codex native-hook capability mapping for ControlMesh.

This module does not execute hooks. It documents and exposes the current
capability matrix so ControlMesh can reason explicitly about which lifecycle
surfaces are native, partially native, fallback-only, or unsupported.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from controlmesh.config import CodexHooksConfig

HookExecutionMode = Literal[
    "native",
    "native_partial",
    "runtime_fallback",
    "not_supported",
]


@dataclass(frozen=True, slots=True)
class CodexHookCapability:
    """One Codex lifecycle surface and how ControlMesh currently expects to handle it."""

    event: str
    mode: HookExecutionMode
    native_source: str | None = None
    fallback_owner: str | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CodexHookPaths:
    """Resolved Codex hook paths for one project root."""

    project_root: Path
    config_path: Path
    hooks_path: Path


@dataclass(frozen=True, slots=True)
class CodexHookStatus:
    """Project-level native hook readiness derived from config and files."""

    paths: CodexHookPaths
    controlmesh_enabled: bool
    prefer_native: bool
    config_exists: bool
    hooks_exist: bool
    native_feature_enabled: bool

    @property
    def native_hooks_available(self) -> bool:
        """Whether the Codex feature flag is present and enabled."""
        return self.config_exists and self.native_feature_enabled

    @property
    def native_hooks_configured(self) -> bool:
        """Whether the repo has the feature flag enabled and a hooks file present."""
        return self.native_hooks_available and self.hooks_exist

    @property
    def effective_mode(self) -> Literal["native_preferred", "runtime_fallback"]:
        """Return how ControlMesh should treat this project today."""
        if self.controlmesh_enabled and self.prefer_native and self.native_hooks_configured:
            return "native_preferred"
        return "runtime_fallback"

    def readiness_issues(self) -> tuple[str, ...]:
        """Return concrete blockers that keep native hooks from being usable."""
        issues: list[str] = []
        if not self.controlmesh_enabled:
            issues.append("codex_hooks.enabled is false")
        if not self.prefer_native:
            issues.append("codex_hooks.prefer_native is false")
        if not self.config_exists:
            issues.append(f"missing config file: {self.paths.config_path}")
        elif not self.native_feature_enabled:
            issues.append("missing [features].codex_hooks = true")
        if not self.hooks_exist:
            issues.append(f"missing hooks file: {self.paths.hooks_path}")
        return tuple(issues)


DEFAULT_CODEX_HOOK_CAPABILITIES: tuple[CodexHookCapability, ...] = (
    CodexHookCapability(
        event="session-start",
        mode="native",
        native_source="SessionStart",
        notes="Suitable for startup bookkeeping and initial context restoration.",
    ),
    CodexHookCapability(
        event="keyword-detector",
        mode="native",
        native_source="UserPromptSubmit",
        notes="Suitable for lightweight prompt-side context activation.",
    ),
    CodexHookCapability(
        event="pre-tool-use",
        mode="native_partial",
        native_source="PreToolUse",
        fallback_owner="orchestrator/hooks.py",
        notes="Current Codex native tool hooks are Bash-centric, so non-Bash coverage still needs fallback logic.",
    ),
    CodexHookCapability(
        event="post-tool-use",
        mode="native_partial",
        native_source="PostToolUse",
        fallback_owner="orchestrator/hooks.py",
        notes="Post-tool guidance can be partially native, but richer recovery remains a runtime concern.",
    ),
    CodexHookCapability(
        event="stop",
        mode="native_partial",
        native_source="Stop",
        fallback_owner="orchestrator/hooks.py",
        notes="Stop continuation exists natively, but ControlMesh-specific continuation policy still needs orchestrator ownership.",
    ),
    CodexHookCapability(
        event="ask-user-question",
        mode="runtime_fallback",
        fallback_owner="tasks/hub.py",
        notes="ControlMesh already has a parent-question path through TaskHub rather than a Codex-native surface.",
    ),
    CodexHookCapability(
        event="post-tool-use-failure",
        mode="runtime_fallback",
        fallback_owner="orchestrator/hooks.py",
        notes="Treat as fallback until Codex exposes a first-class native failure hook.",
    ),
    CodexHookCapability(
        event="non-bash-tool-interception",
        mode="runtime_fallback",
        fallback_owner="orchestrator/hooks.py",
        notes="Current Codex native tool interception scope is narrower than ControlMesh's overall tool model.",
    ),
    CodexHookCapability(
        event="session-end",
        mode="runtime_fallback",
        fallback_owner="bus/bus.py",
        notes="Best modeled through ControlMesh runtime or gateway delivery for now.",
    ),
    CodexHookCapability(
        event="session-idle",
        mode="runtime_fallback",
        fallback_owner="bus/bus.py",
        notes="Idle detection remains runtime-owned in ControlMesh today.",
    ),
    CodexHookCapability(
        event="subagent-stop",
        mode="not_supported",
        notes="No Codex-native equivalent exists today for ControlMesh's multi-agent lifecycle edge.",
    ),
)


def capability_map() -> dict[str, CodexHookCapability]:
    """Return the default matrix keyed by event name."""
    return {cap.event: cap for cap in DEFAULT_CODEX_HOOK_CAPABILITIES}


def capabilities_by_mode() -> dict[HookExecutionMode, tuple[str, ...]]:
    """Return event names grouped by execution mode."""
    grouped: dict[HookExecutionMode, list[str]] = {
        "native": [],
        "native_partial": [],
        "runtime_fallback": [],
        "not_supported": [],
    }
    for cap in DEFAULT_CODEX_HOOK_CAPABILITIES:
        grouped[cap.mode].append(cap.event)
    return {mode: tuple(items) for mode, items in grouped.items()}


def resolve_codex_hook_paths(
    project_root: str | Path,
    config: CodexHooksConfig | None = None,
) -> CodexHookPaths:
    """Resolve Codex hook file paths relative to a project root."""
    settings = config or CodexHooksConfig()
    root = Path(project_root).expanduser().resolve()
    return CodexHookPaths(
        project_root=root,
        config_path=_resolve_project_path(root, settings.config_file),
        hooks_path=_resolve_project_path(root, settings.hooks_file),
    )


def inspect_codex_hook_status(
    project_root: str | Path,
    config: CodexHooksConfig | None = None,
) -> CodexHookStatus:
    """Inspect whether native Codex hooks are available/configured for a repo."""
    settings = config or CodexHooksConfig()
    paths = resolve_codex_hook_paths(project_root, settings)
    config_exists = paths.config_path.is_file()
    hooks_exist = paths.hooks_path.is_file()
    native_feature_enabled = _codex_feature_enabled(paths.config_path) if config_exists else False
    return CodexHookStatus(
        paths=paths,
        controlmesh_enabled=settings.enabled,
        prefer_native=settings.prefer_native,
        config_exists=config_exists,
        hooks_exist=hooks_exist,
        native_feature_enabled=native_feature_enabled,
    )


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return project_root / candidate


def _codex_feature_enabled(config_path: Path) -> bool:
    """Return True when ``[features].codex_hooks`` is explicitly enabled."""
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False

    features = data.get("features")
    if not isinstance(features, dict):
        return False
    return features.get("codex_hooks") is True
