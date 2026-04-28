"""Tests for workspace file reader."""

from __future__ import annotations

from pathlib import Path

from controlmesh.workspace.loader import read_file, read_startup_memory_context
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    return ControlMeshPaths(
        controlmesh_home=tmp_path / "home", home_defaults=fw / "workspace", framework_root=fw
    )


# -- read_file --


def test_read_existing_file(tmp_path: Path) -> None:
    f = tmp_path / "test.md"
    f.write_text("Hello world")
    assert read_file(f) == "Hello world"


def test_read_nonexistent_file(tmp_path: Path) -> None:
    assert read_file(tmp_path / "missing.md") is None


def test_read_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.md"
    f.write_text("")
    assert read_file(f) == ""


def test_read_startup_memory_context_returns_meaningful_authority(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory\n\n## Durable Memory\n\n### Fact\n- File-backed context wins.\n",
        encoding="utf-8",
    )

    result = read_startup_memory_context(paths)

    assert "## Memory" in result
    assert "File-backed context wins." in result


def test_read_startup_memory_context_ignores_empty_authority_template(tmp_path: Path) -> None:
    paths = _make_paths(tmp_path)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory\n\n## Durable Memory\n\n### Fact\n\n### Preference\n",
        encoding="utf-8",
    )

    assert read_startup_memory_context(paths) == ""


def test_read_startup_memory_context_treats_shared_block_as_meaningful_authority(
    tmp_path: Path,
) -> None:
    paths = _make_paths(tmp_path)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    paths.authority_memory_path.write_text(
        "# ControlMesh Memory\n\n"
        "## Durable Memory\n\n"
        "### Fact\n\n"
        "--- SHARED KNOWLEDGE START ---\n"
        "Shared context only.\n"
        "--- SHARED KNOWLEDGE END ---\n",
        encoding="utf-8",
    )

    result = read_startup_memory_context(paths)
    assert "## Memory" in result
    assert "Shared context only." in result
