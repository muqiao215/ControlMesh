"""Release-contract tests for the current ControlMesh release."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "0.43.0"
WORKSPACE_VERSION = "0.42.0-alpha.1"


def test_alpha_version_is_consistent_across_release_surfaces() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    init_source = (ROOT / "controlmesh" / "__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'^__version__ = "([^"]+)"$', init_source, re.MULTILINE)

    assert pyproject["project"]["version"] == PYTHON_VERSION
    assert init_version is not None
    assert init_version.group(1) == PYTHON_VERSION
    assert "Development Status :: 4 - Beta" in pyproject["project"]["classifiers"]

    manifests = [
        ROOT / "apps" / "controlmesh-web" / "package.json",
        *sorted((ROOT / "packages").glob("*/package.json")),
    ]
    assert manifests
    for manifest in manifests:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        assert payload["version"] == WORKSPACE_VERSION, manifest

    assert (ROOT / f"docs/release-note-v{PYTHON_VERSION}.md").is_file()


def test_alpha_distribution_and_publish_contracts_are_present() -> None:
    for relative_path in (
        "controlmesh/web_static/index.html",
        "controlmesh/web_static/assets/main.js",
        "controlmesh/web_static/assets/styles.css",
    ):
        assert (ROOT / relative_path).is_file()

    publish_source = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "dashboard_hits" in publish_source
    assert "--prerelease --latest=false" in publish_source
    assert 'payload.get("releases", {}).get(expected, [])' in publish_source
    assert "if release_files:" in publish_source

    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert "alpha-smoke" in ci["jobs"]["ci-success"]["needs"]
    smoke_runs = [step.get("run", "") for step in ci["jobs"]["alpha-smoke"]["steps"]]
    assert "bash scripts/smoke_read_only_alpha.sh" in smoke_runs
