"""Tests for allowed roots resolution."""

from __future__ import annotations

from pathlib import Path

from controlmesh.files.allowed_roots import resolve_allowed_roots


class TestResolveAllowedRoots:
    def test_all_returns_none(self, tmp_path: Path) -> None:
        assert resolve_allowed_roots("all", tmp_path) is None

    def test_home_returns_home_dir(self, tmp_path: Path) -> None:
        result = resolve_allowed_roots("home", tmp_path)
        assert result is not None
        assert result == [Path.home()]

    def test_workspace_returns_workspace(self, tmp_path: Path) -> None:
        result = resolve_allowed_roots("workspace", tmp_path)
        assert result == [tmp_path]

    def test_unknown_falls_back_to_workspace(self, tmp_path: Path) -> None:
        result = resolve_allowed_roots("something_else", tmp_path)
        assert result == [tmp_path]
