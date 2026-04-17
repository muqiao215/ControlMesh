from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


def test_pyproject_exposes_controlmesh_public_branding() -> None:
    legacy_brand = "du" "ctor"
    payload = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]

    assert project["name"] == "controlmesh"
    assert project["scripts"] == {"controlmesh": "controlmesh.__main__:main"}
    assert project["urls"]["Repository"] == "https://github.com/muqiao215/ControlMesh"
    assert project["urls"]["Issues"] == "https://github.com/muqiao215/ControlMesh/issues"
    assert project["urls"]["Changelog"] == "https://github.com/muqiao215/ControlMesh/releases"

    branded_values = [
        project["description"],
        *project["keywords"],
        *project["urls"].values(),
    ]
    assert all(legacy_brand not in str(value).lower() for value in branded_values)


def test_resolve_paths_defaults_to_controlmesh_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CONTROLMESH_HOME", raising=False)

    from controlmesh.workspace.paths import ControlMeshPaths, resolve_paths

    default_paths = resolve_paths()
    assert isinstance(default_paths, ControlMeshPaths)
    assert default_paths.controlmesh_home == (tmp_path / ".controlmesh").resolve()

    custom_home = tmp_path / "custom-home"
    monkeypatch.setenv("CONTROLMESH_HOME", str(custom_home))
    overridden_paths = resolve_paths()
    assert overridden_paths.controlmesh_home == custom_home.resolve()


@pytest.mark.parametrize("path_str", ["README.md"])
def test_root_docs_use_controlmesh_branding(path_str: str) -> None:
    legacy_brand = "du" "ctor"
    text = Path(path_str).read_text(encoding="utf-8")

    assert "ControlMesh" in text
    assert legacy_brand not in text.lower()
