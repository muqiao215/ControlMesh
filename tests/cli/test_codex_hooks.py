"""Tests for Codex hook capability mapping."""

from __future__ import annotations

from pathlib import Path

from controlmesh.cli.codex_hooks import (
    capabilities_by_mode,
    capability_map,
    inspect_codex_hook_status,
    resolve_codex_hook_paths,
)
from controlmesh.config import CodexHooksConfig


def test_capability_map_contains_expected_surfaces() -> None:
    caps = capability_map()
    assert "session-start" in caps
    assert "stop" in caps
    assert "session-end" in caps
    assert "subagent-stop" in caps


def test_capability_map_modes_match_expected_examples() -> None:
    caps = capability_map()
    assert caps["session-start"].mode == "native"
    assert caps["pre-tool-use"].mode == "native_partial"
    assert caps["session-end"].mode == "runtime_fallback"
    assert caps["subagent-stop"].mode == "not_supported"


def test_capabilities_grouped_by_mode() -> None:
    grouped = capabilities_by_mode()
    assert "session-start" in grouped["native"]
    assert "pre-tool-use" in grouped["native_partial"]
    assert "ask-user-question" in grouped["runtime_fallback"]
    assert "subagent-stop" in grouped["not_supported"]


def test_resolve_codex_hook_paths_uses_project_relative_defaults(tmp_path: Path) -> None:
    paths = resolve_codex_hook_paths(tmp_path)
    assert paths.config_path == tmp_path / ".codex/config.toml"
    assert paths.hooks_path == tmp_path / ".codex/hooks.json"


def test_inspect_codex_hook_status_reports_native_preferred_when_complete(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
    (codex_dir / "hooks.json").write_text("{}", encoding="utf-8")

    status = inspect_codex_hook_status(
        tmp_path,
        CodexHooksConfig(enabled=True, prefer_native=True),
    )

    assert status.native_hooks_available is True
    assert status.native_hooks_configured is True
    assert status.effective_mode == "native_preferred"
    assert status.readiness_issues() == ()


def test_inspect_codex_hook_status_stays_fallback_when_controlmesh_disables_native(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text("[features]\ncodex_hooks = true\n", encoding="utf-8")
    (codex_dir / "hooks.json").write_text("{}", encoding="utf-8")

    status = inspect_codex_hook_status(
        tmp_path,
        CodexHooksConfig(enabled=False, prefer_native=True),
    )

    assert status.native_hooks_configured is True
    assert status.effective_mode == "runtime_fallback"
    assert "codex_hooks.enabled is false" in status.readiness_issues()


def test_inspect_codex_hook_status_reports_missing_feature_flag(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text("[features]\nother = true\n", encoding="utf-8")

    status = inspect_codex_hook_status(
        tmp_path,
        CodexHooksConfig(enabled=True, prefer_native=True),
    )

    assert status.native_hooks_available is False
    assert status.native_hooks_configured is False
    assert status.effective_mode == "runtime_fallback"
    assert "missing [features].codex_hooks = true" in status.readiness_issues()
