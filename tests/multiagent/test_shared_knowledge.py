"""Tests for multiagent/shared_knowledge.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh.multiagent.shared_knowledge import (
    _END_MARKER,
    _LEGACY_END,
    _LEGACY_START,
    _START_MARKER,
    _find_markers,
    _sync_agent_files,
    _sync_agent_io,
)


class TestFindMarkers:
    def test_finds_new_markers(self) -> None:
        text = f"before\n{_START_MARKER}\ncontent\n{_END_MARKER}\nafter"
        assert _find_markers(text) == (_START_MARKER, _END_MARKER)

    def test_finds_legacy_markers(self) -> None:
        text = f"before\n{_LEGACY_START}\ncontent\n{_LEGACY_END}\nafter"
        assert _find_markers(text) == (_LEGACY_START, _LEGACY_END)

    def test_returns_none_without_markers(self) -> None:
        assert _find_markers("plain text") is None


class TestSyncAgentIO:
    @pytest.fixture
    def shared_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "SHAREDMEMORY.md"
        p.write_text("Shared content here", encoding="utf-8")
        return p

    @pytest.fixture
    def authority_memory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "MEMORY.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# ControlMesh Memory\n\n"
            "## Durable Memory\n\n"
            "### Fact\n\n"
            "User-specific durable notes.\n",
            encoding="utf-8",
        )
        return p

    def test_injects_into_memory_without_overwriting_user_content(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is True

        content = authority_memory_path.read_text(encoding="utf-8")
        assert content.startswith("# ControlMesh Memory\n")
        assert "User-specific durable notes." in content
        assert _START_MARKER in content
        assert _END_MARKER in content
        assert "Shared content here" in content

    def test_replaces_existing_markers(self, shared_path: Path, authority_memory_path: Path) -> None:
        _sync_agent_io(shared_path, authority_memory_path)

        shared_path.write_text("Updated shared content", encoding="utf-8")
        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is True

        content = authority_memory_path.read_text(encoding="utf-8")
        assert "Updated shared content" in content
        assert "Shared content here" not in content
        assert content.count(_START_MARKER) == 1
        assert content.count(_END_MARKER) == 1

    def test_migrates_legacy_markers(self, shared_path: Path, authority_memory_path: Path) -> None:
        authority_memory_path.write_text(
            f"# ControlMesh Memory\n{_LEGACY_START}\nold content\n{_LEGACY_END}\n",
            encoding="utf-8",
        )

        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is True

        content = authority_memory_path.read_text(encoding="utf-8")
        assert _START_MARKER in content
        assert _END_MARKER in content
        assert _LEGACY_START not in content
        assert _LEGACY_END not in content
        assert "Shared content here" in content

    def test_returns_false_when_shared_missing(
        self, tmp_path: Path, authority_memory_path: Path
    ) -> None:
        assert _sync_agent_io(tmp_path / "missing.md", authority_memory_path) is False

    def test_returns_false_when_memory_missing(self, shared_path: Path, tmp_path: Path) -> None:
        assert _sync_agent_io(shared_path, tmp_path / "missing.md") is False

    def test_returns_false_when_content_unchanged(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        _sync_agent_io(shared_path, authority_memory_path)
        assert _sync_agent_io(shared_path, authority_memory_path) is False


class TestSyncAgentFiles:
    @pytest.fixture
    def shared_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "SHAREDMEMORY.md"
        p.write_text("Shared content here", encoding="utf-8")
        return p

    @pytest.fixture
    def authority_memory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "MEMORY.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# ControlMesh Memory\n\n## Durable Memory\n", encoding="utf-8")
        return p

    def test_syncs_authority_target(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        written = _sync_agent_files(shared_path, authority_memory_path)
        assert written == (authority_memory_path,)
        assert "Shared content here" in authority_memory_path.read_text(encoding="utf-8")

    def test_skips_missing_authority_target(self, shared_path: Path, tmp_path: Path) -> None:
        written = _sync_agent_files(shared_path, tmp_path / "workspace" / "MEMORY.md")
        assert written == ()

    def test_returns_empty_tuple_when_nothing_changed(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        _sync_agent_files(shared_path, authority_memory_path)
        assert _sync_agent_files(shared_path, authority_memory_path) == ()
