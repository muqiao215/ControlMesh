from __future__ import annotations

from pathlib import Path


def test_wheel_packages_include_controlmesh_runtime() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    assert 'packages = ["controlmesh", "controlmesh_runtime"]' in text
