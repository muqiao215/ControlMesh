"""Shared fixtures for orchestrator tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.cli.auth import AuthResult, AuthStatus
from controlmesh.config import AgentConfig
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.workspace.init import init_workspace
from controlmesh.workspace.paths import ControlMeshPaths


def setup_framework(fw_root: Path) -> None:
    """Create minimal home-defaults template for testing."""
    ws = fw_root / "workspace"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("# ControlMesh Home")

    config_dir = ws / "config"
    config_dir.mkdir()

    inner = ws / "workspace"
    inner.mkdir()
    (inner / "CLAUDE.md").write_text("# Framework CLAUDE.md")

    for subdir in ("cron_tasks", "output_to_user", "telegram_files"):
        d = inner / subdir
        d.mkdir()
        (d / "CLAUDE.md").write_text(f"# {subdir}")

    tools = inner / "tools"
    tools.mkdir()
    (tools / "CLAUDE.md").write_text("# Tools")

    (fw_root / "config.example.json").write_text('{"provider": "claude", "model": "opus"}')


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[ControlMeshPaths, AgentConfig]:
    """Fully initialized workspace with models and config."""
    fw_root = tmp_path / "fw"
    setup_framework(fw_root)
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / "home", home_defaults=fw_root / "workspace", framework_root=fw_root
    )
    init_workspace(paths)
    config = AgentConfig()
    return paths, config


@pytest.fixture(autouse=True)
def _mock_authenticated_providers() -> Generator[None, None, None]:
    """Keep orchestrator workspace setup independent from local CLI auth."""
    auth = {
        "claude": AuthResult(provider="claude", status=AuthStatus.AUTHENTICATED),
        "codex": AuthResult(provider="codex", status=AuthStatus.AUTHENTICATED),
        "gemini": AuthResult(provider="gemini", status=AuthStatus.AUTHENTICATED),
    }
    with patch("controlmesh.cli.auth.check_all_auth", return_value=auth):
        yield


@pytest.fixture
def orch(workspace: tuple[ControlMeshPaths, AgentConfig]) -> Orchestrator:
    """Orchestrator with mocked CLIService."""
    paths, config = workspace
    o = Orchestrator(config, paths)
    mock_cli = MagicMock()
    mock_cli.execute = AsyncMock()
    mock_cli.execute_streaming = AsyncMock()
    object.__setattr__(o, "_cli_service", mock_cli)
    return o
