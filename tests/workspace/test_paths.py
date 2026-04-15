"""Tests for ControlMeshPaths and resolve_paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths


def test_workspace_property() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.workspace == Path("/home/test/.controlmesh/workspace")


def test_config_path() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.config_path == Path("/home/test/.controlmesh/config/config.json")


def test_sessions_path() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.sessions_path == Path("/home/test/.controlmesh/sessions.json")


def test_transcripts_dir() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.transcripts_dir == Path("/home/test/.controlmesh/transcripts")


def test_runtime_events_dir() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.runtime_events_dir == Path("/home/test/.controlmesh/runtime-events")
    assert paths.runtime_events_dir != paths.transcripts_dir


def test_history_index_path() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.history_index_path == Path("/home/test/.controlmesh/workspace/.history/index.sqlite3")


def test_team_control_snapshots_dir() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.team_control_snapshots_dir == Path("/home/test/.controlmesh/workspace/.team-snapshots")


def test_logs_dir() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.logs_dir == Path("/home/test/.controlmesh/logs")


def test_team_state_dir() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/home/test/.controlmesh"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.team_state_dir == Path("/home/test/.controlmesh/workspace/team-state")


def test_home_defaults() -> None:
    paths = ControlMeshPaths(
        controlmesh_home=Path("/x"),
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    assert paths.home_defaults == Path("/opt/controlmesh/workspace")


def test_resolve_paths_explicit() -> None:
    paths = resolve_paths(controlmesh_home="/tmp/test_home", framework_root="/tmp/test_fw")
    assert paths.controlmesh_home == Path("/tmp/test_home").resolve()
    assert paths.framework_root == Path("/tmp/test_fw").resolve()


def test_resolve_paths_env_vars() -> None:
    with patch.dict(
        os.environ, {"CONTROLMESH_HOME": "/tmp/env_home", "CONTROLMESH_FRAMEWORK_ROOT": "/tmp/env_fw"}
    ):
        paths = resolve_paths()
        assert paths.controlmesh_home == Path("/tmp/env_home").resolve()
        assert paths.framework_root == Path("/tmp/env_fw").resolve()


def test_resolve_paths_defaults() -> None:
    with patch.dict(os.environ, {}, clear=True):
        env_clean = {
            k: v for k, v in os.environ.items() if k not in ("CONTROLMESH_HOME", "CONTROLMESH_FRAMEWORK_ROOT")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            paths = resolve_paths()
            assert paths.controlmesh_home == (Path.home() / ".controlmesh").resolve()
