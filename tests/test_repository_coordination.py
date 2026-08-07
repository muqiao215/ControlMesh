"""Progressive project-memory contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_FILES = (
    "PROJECT.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/ARCHITECTURE.md",
    "docs/DECISIONS.md",
)
SUPERSEDED_ROOT_FILES = (
    "REQUIREMENTS.md",
    "IMPLEMENTATION.md",
    "HANDOFF.md",
)


def test_project_memory_files_exist_and_readme_links_the_knowledge_map() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    for relative_path in MEMORY_FILES:
        assert (REPO_ROOT / relative_path).is_file()

    for relative_path in (
        "PROJECT.md",
        "AGENTS.md",
        "docs/ARCHITECTURE.md",
        "docs/DECISIONS.md",
    ):
        assert f"({relative_path})" in readme


def test_agents_file_defines_progressive_loading_and_memory_ownership() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "First read:" in agents
    assert "`PROJECT.md`" in agents
    assert "`docs/ARCHITECTURE.md`" in agents
    assert "`docs/DECISIONS.md`" in agents
    assert "`plans/<task>/task_plan.md`" in agents
    assert "Do not load unrelated documentation by default" in agents


def test_claude_file_is_only_a_compatibility_entrypoint() -> None:
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert claude == "@AGENTS.md\n"


def test_superseded_parallel_authority_files_are_absent() -> None:
    for relative_path in SUPERSEDED_ROOT_FILES:
        assert not (REPO_ROOT / relative_path).exists()

    assert not (REPO_ROOT / "docs/architecture.md").exists()


def test_active_complex_task_has_complete_memory_trio() -> None:
    task_dir = REPO_ROOT / "plans" / "project-memory-v1"

    for name in ("task_plan.md", "findings.md", "progress.md"):
        assert (task_dir / name).is_file()


def test_project_memory_and_lockfiles_are_not_ignored() -> None:
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            *MEMORY_FILES,
            "plans/project-memory-v1/task_plan.md",
            "plans/project-memory-v1/findings.md",
            "plans/project-memory-v1/progress.md",
            "uv.lock",
            "pnpm-lock.yaml",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout


def test_gitignore_keeps_secrets_dependencies_and_local_agent_state_local() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in (
        ".env",
        ".env.*",
        ".venv/",
        "node_modules/",
        "*.log",
        "dist/",
        "/.omo/",
    ):
        assert pattern in gitignore
