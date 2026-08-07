"""Repository-level requirements and handoff contract tests."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FILES = (
    "REQUIREMENTS.md",
    "IMPLEMENTATION.md",
    "HANDOFF.md",
    "AGENTS.md",
)


def test_repository_coordination_files_exist_and_are_linked() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for relative_path in CANONICAL_FILES:
        assert (REPO_ROOT / relative_path).is_file()
        assert f"({relative_path})" in readme


def test_requirements_have_unique_stable_ids() -> None:
    requirements = (REPO_ROOT / "REQUIREMENTS.md").read_text(encoding="utf-8")
    requirement_ids = re.findall(r"\| ([A-Z]{2,3}-\d{3}) \|", requirements)

    assert len(requirement_ids) >= 20
    assert len(requirement_ids) == len(set(requirement_ids))


def test_handoff_contains_takeover_sections() -> None:
    handoff = (REPO_ROOT / "HANDOFF.md").read_text(encoding="utf-8")

    for heading in (
        "## Objective",
        "## Current State",
        "## Worktree Context",
        "## Last Verified Gates",
        "## Known Risks",
        "## Next Work",
        "## Local Processes",
    ):
        assert heading in handoff


def test_canonical_collaboration_files_are_not_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *CANONICAL_FILES, "uv.lock"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout


def test_gitignore_keeps_secrets_and_generated_dependencies_local() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (".env", ".env.*", ".venv/", "node_modules/", "*.log", "dist/"):
        assert pattern in gitignore
