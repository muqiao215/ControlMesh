"""Tests for Codex cache integration into orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.cli.codex_discovery import CodexModelInfo
from controlmesh.workspace.init import init_workspace
from controlmesh.workspace.paths import ControlMeshPaths


@pytest.fixture
def mock_codex_cache() -> CodexModelCache:
    """Mock Codex cache with sample models."""
    return CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-4o",
                display_name="GPT-4o",
                description="GPT-4o model",
                supported_efforts=("low", "medium", "high"),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )


def _paths(tmp_path: Path) -> ControlMeshPaths:
    fw_root = tmp_path / "fw"
    ws = fw_root / "workspace"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("# ControlMesh Home", encoding="utf-8")
    (ws / "config").mkdir()
    inner = ws / "workspace"
    inner.mkdir()
    (inner / "CLAUDE.md").write_text("# Framework CLAUDE.md", encoding="utf-8")
    for subdir in ("cron_tasks", "output_to_user", "telegram_files", "tools"):
        folder = inner / subdir
        folder.mkdir()
        (folder / "CLAUDE.md").write_text(f"# {subdir}", encoding="utf-8")
    (fw_root / "config.example.json").write_text('{"provider": "claude", "model": "opus"}', encoding="utf-8")
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw_root / "workspace",
        framework_root=fw_root,
    )
    init_workspace(paths)
    return paths


async def test_orchestrator_starts_cache_observer(
    mock_codex_cache: CodexModelCache, tmp_path: Path
) -> None:
    """Should start CodexCacheObserver during orchestrator creation."""
    from controlmesh.config import AgentConfig
    from controlmesh.orchestrator.core import Orchestrator

    mock_observer = MagicMock()
    mock_observer.start = AsyncMock()
    mock_observer.stop = AsyncMock()
    mock_observer.get_cache = MagicMock(return_value=mock_codex_cache)

    paths = _paths(tmp_path)
    mock_config = AgentConfig(controlmesh_home=str(paths.controlmesh_home))

    with (
        patch("controlmesh.orchestrator.observers.CodexCacheObserver", return_value=mock_observer),
        patch("controlmesh.orchestrator.lifecycle.resolve_paths", return_value=paths),
        patch("controlmesh.orchestrator.lifecycle.inject_runtime_environment"),
        patch("controlmesh.cli.auth.check_all_auth", return_value={}),
    ):
        orch = await Orchestrator.create(mock_config)

        # Verify observer was started
        mock_observer.start.assert_called_once()

        await orch.shutdown()


async def test_orchestrator_passes_cache_to_observers(
    mock_codex_cache: CodexModelCache,
    tmp_path: Path,
) -> None:
    """Should pass Codex cache to CronObserver and WebhookObserver."""
    from controlmesh.config import AgentConfig
    from controlmesh.orchestrator.core import Orchestrator

    mock_cache_observer = MagicMock()
    mock_cache_observer.start = AsyncMock()
    mock_cache_observer.stop = AsyncMock()
    mock_cache_observer.get_cache = MagicMock(return_value=mock_codex_cache)

    mock_cron_instance = MagicMock()
    mock_cron_instance.start = AsyncMock()
    mock_cron_instance.stop = AsyncMock()
    mock_cron_class = MagicMock(return_value=mock_cron_instance)

    mock_webhook_instance = MagicMock()
    mock_webhook_instance.start = AsyncMock()
    mock_webhook_instance.stop = AsyncMock()
    mock_webhook_class = MagicMock(return_value=mock_webhook_instance)

    paths = _paths(tmp_path)
    mock_config = AgentConfig(controlmesh_home=str(paths.controlmesh_home))

    with (
        patch(
            "controlmesh.orchestrator.observers.CodexCacheObserver", return_value=mock_cache_observer
        ),
        patch("controlmesh.orchestrator.observers.CronObserver", mock_cron_class),
        patch("controlmesh.orchestrator.observers.WebhookObserver", mock_webhook_class),
        patch("controlmesh.orchestrator.lifecycle.resolve_paths", return_value=paths),
        patch("controlmesh.orchestrator.lifecycle.inject_runtime_environment"),
        patch("controlmesh.cli.auth.check_all_auth", return_value={}),
    ):
        orch = await Orchestrator.create(mock_config)

        # Verify cache was passed to observers
        # Check call_args for codex_cache keyword argument
        assert mock_cron_class.called, "CronObserver should be instantiated"
        assert mock_webhook_class.called, "WebhookObserver should be instantiated"

        # Check if codex_cache was passed
        cron_kwargs = mock_cron_class.call_args[1]
        webhook_kwargs = mock_webhook_class.call_args[1]

        assert "codex_cache" in cron_kwargs, "CronObserver should receive codex_cache"
        assert cron_kwargs["codex_cache"] == mock_codex_cache

        assert "codex_cache" in webhook_kwargs, "WebhookObserver should receive codex_cache"
        assert webhook_kwargs["codex_cache"] == mock_codex_cache

        await orch.shutdown()


async def test_orchestrator_stops_cache_observer(
    mock_codex_cache: CodexModelCache, tmp_path: Path
) -> None:
    """Should stop CodexCacheObserver during orchestrator shutdown."""
    from controlmesh.config import AgentConfig
    from controlmesh.orchestrator.core import Orchestrator

    mock_observer = MagicMock()
    mock_observer.start = AsyncMock()
    mock_observer.stop = AsyncMock()
    mock_observer.get_cache = MagicMock(return_value=mock_codex_cache)

    paths = _paths(tmp_path)
    mock_config = AgentConfig(controlmesh_home=str(paths.controlmesh_home))

    with (
        patch("controlmesh.orchestrator.observers.CodexCacheObserver", return_value=mock_observer),
        patch("controlmesh.orchestrator.lifecycle.resolve_paths", return_value=paths),
        patch("controlmesh.orchestrator.lifecycle.inject_runtime_environment"),
        patch("controlmesh.cli.auth.check_all_auth", return_value={}),
    ):
        orch = await Orchestrator.create(mock_config)

        # Shutdown orchestrator
        await orch.shutdown()

        # Verify observer was stopped
        mock_observer.stop.assert_called_once()
