"""Tests for multiagent/shared_knowledge.py: marker injection and migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh.memory.compat import _COMPAT_END_MARKER, _COMPAT_START_MARKER
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
    """Test _find_markers() detection."""

    def test_finds_new_markers(self) -> None:
        text = f"before\n{_START_MARKER}\ncontent\n{_END_MARKER}\nafter"
        result = _find_markers(text)
        assert result == (_START_MARKER, _END_MARKER)

    def test_finds_legacy_markers(self) -> None:
        text = f"before\n{_LEGACY_START}\ncontent\n{_LEGACY_END}\nafter"
        result = _find_markers(text)
        assert result == (_LEGACY_START, _LEGACY_END)

    def test_prefers_new_over_legacy(self) -> None:
        """When both marker types exist, prefer new format."""
        text = f"{_START_MARKER}\n{_LEGACY_START}\ncontent\n{_LEGACY_END}\n{_END_MARKER}"
        result = _find_markers(text)
        assert result == (_START_MARKER, _END_MARKER)

    def test_returns_none_when_no_markers(self) -> None:
        assert _find_markers("plain text without markers") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _find_markers("") is None


class TestSyncAgentIO:
    """Test _sync_agent_io() file operations."""

    @pytest.fixture
    def shared_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "SHAREDMEMORY.md"
        p.write_text("Shared content here", encoding="utf-8")
        return p

    @pytest.fixture
    def mainmemory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "memory_system" / "MAINMEMORY.md"
        p.parent.mkdir(parents=True)
        p.write_text("# Main Memory\nAgent notes.\n", encoding="utf-8")
        return p

    @pytest.fixture
    def authority_memory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "MEMORY.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# ControlMesh Memory v2\n\n"
            "## Durable Memory\n\n"
            "### Fact\n\n"
            "User-specific durable notes.\n",
            encoding="utf-8",
        )
        return p

    def test_injects_into_file_without_markers(
        self, shared_path: Path, mainmemory_path: Path
    ) -> None:
        result = _sync_agent_io(shared_path, mainmemory_path)
        assert result is True

        content = mainmemory_path.read_text()
        assert _START_MARKER in content
        assert _END_MARKER in content
        assert "Shared content here" in content
        assert "# Main Memory" in content

    def test_replaces_existing_markers(self, shared_path: Path, mainmemory_path: Path) -> None:
        # First injection
        _sync_agent_io(shared_path, mainmemory_path)

        # Update shared content
        shared_path.write_text("Updated shared content", encoding="utf-8")
        result = _sync_agent_io(shared_path, mainmemory_path)
        assert result is True

        content = mainmemory_path.read_text()
        assert "Updated shared content" in content
        assert "Shared content here" not in content
        # Only one start/end marker pair
        assert content.count(_START_MARKER) == 1
        assert content.count(_END_MARKER) == 1

    def test_injects_into_authority_memory_without_overwriting_user_content(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is True

        content = authority_memory_path.read_text()
        assert content.startswith("# ControlMesh Memory v2\n")
        assert "User-specific durable notes." in content
        assert _START_MARKER in content
        assert _END_MARKER in content
        assert "Shared content here" in content

    def test_migrates_legacy_markers(self, shared_path: Path, mainmemory_path: Path) -> None:
        """Legacy markers are replaced with new-format markers on sync."""
        legacy_content = f"# Main Memory\n{_LEGACY_START}\nold content\n{_LEGACY_END}\n"
        mainmemory_path.write_text(legacy_content, encoding="utf-8")

        result = _sync_agent_io(shared_path, mainmemory_path)
        assert result is True

        content = mainmemory_path.read_text()
        assert _START_MARKER in content
        assert _END_MARKER in content
        assert _LEGACY_START not in content
        assert _LEGACY_END not in content
        assert "Shared content here" in content

    def test_returns_false_when_shared_missing(self, tmp_path: Path, mainmemory_path: Path) -> None:
        missing = tmp_path / "does_not_exist.md"
        assert _sync_agent_io(missing, mainmemory_path) is False

    def test_returns_false_when_shared_empty(self, tmp_path: Path, mainmemory_path: Path) -> None:
        empty_shared = tmp_path / "empty.md"
        empty_shared.write_text("", encoding="utf-8")
        assert _sync_agent_io(empty_shared, mainmemory_path) is False

    def test_returns_false_when_mainmemory_missing(self, shared_path: Path, tmp_path: Path) -> None:
        missing = tmp_path / "missing_mainmem.md"
        assert _sync_agent_io(shared_path, missing) is False

    def test_returns_false_when_content_unchanged(
        self, shared_path: Path, mainmemory_path: Path
    ) -> None:
        """Second sync with same content returns False (no write)."""
        _sync_agent_io(shared_path, mainmemory_path)
        result = _sync_agent_io(shared_path, mainmemory_path)
        assert result is False

    def test_preserves_content_before_and_after_markers(
        self, shared_path: Path, mainmemory_path: Path
    ) -> None:
        """Content before and after markers is preserved."""
        mainmemory_path.write_text(
            f"# Before\n{_START_MARKER}\nold\n{_END_MARKER}\n# After\n",
            encoding="utf-8",
        )
        result = _sync_agent_io(shared_path, mainmemory_path)
        assert result is True

        content = mainmemory_path.read_text()
        assert content.startswith("# Before\n")
        assert "# After" in content
        assert "Shared content here" in content

    def test_replaces_existing_markers_inside_authority_memory(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        _sync_agent_io(shared_path, authority_memory_path)

        shared_path.write_text("Updated shared content", encoding="utf-8")
        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is True

        content = authority_memory_path.read_text()
        assert "Updated shared content" in content
        assert "Shared content here" not in content
        assert "User-specific durable notes." in content
        assert content.count(_START_MARKER) == 1
        assert content.count(_END_MARKER) == 1

    def test_returns_false_when_authority_memory_content_unchanged(
        self, shared_path: Path, authority_memory_path: Path
    ) -> None:
        _sync_agent_io(shared_path, authority_memory_path)
        result = _sync_agent_io(shared_path, authority_memory_path)
        assert result is False


class TestSyncAgentFiles:
    """Test syncing shared knowledge into multiple memory targets."""

    @pytest.fixture
    def shared_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "SHAREDMEMORY.md"
        p.write_text("Shared content here", encoding="utf-8")
        return p

    @pytest.fixture
    def mainmemory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "memory_system" / "MAINMEMORY.md"
        p.parent.mkdir(parents=True)
        p.write_text("# Main Memory\n", encoding="utf-8")
        return p

    @pytest.fixture
    def authority_memory_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "workspace" / "MEMORY.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# ControlMesh Memory v2\n\n## Durable Memory\n", encoding="utf-8")
        return p

    def test_syncs_both_legacy_and_v2_targets(
        self, shared_path: Path, mainmemory_path: Path, authority_memory_path: Path
    ) -> None:
        written = _sync_agent_files(shared_path, mainmemory_path, authority_memory_path)
        assert written == (authority_memory_path, mainmemory_path)

        legacy_text = mainmemory_path.read_text()
        assert _COMPAT_START_MARKER in legacy_text
        assert _COMPAT_END_MARKER in legacy_text
        assert "Shared content here" in legacy_text
        assert "Shared content here" in authority_memory_path.read_text()

    def test_skips_missing_target_but_updates_existing_ones(
        self, shared_path: Path, mainmemory_path: Path, tmp_path: Path
    ) -> None:
        missing = tmp_path / "workspace" / "MEMORY.md"
        written = _sync_agent_files(shared_path, mainmemory_path, missing)
        assert written == ()

    def test_returns_empty_tuple_when_nothing_changed(
        self, shared_path: Path, mainmemory_path: Path, authority_memory_path: Path
    ) -> None:
        _sync_agent_files(shared_path, mainmemory_path, authority_memory_path)
        written = _sync_agent_files(shared_path, mainmemory_path, authority_memory_path)
        assert written == ()

    def test_removes_legacy_direct_shared_block_after_authority_sync(
        self, shared_path: Path, mainmemory_path: Path, authority_memory_path: Path
    ) -> None:
        mainmemory_path.write_text(
            f"# Main Memory\n\n{_START_MARKER}\nold direct block\n{_END_MARKER}\n",
            encoding="utf-8",
        )

        written = _sync_agent_files(shared_path, mainmemory_path, authority_memory_path)

        assert written == (authority_memory_path, mainmemory_path)
        legacy_text = mainmemory_path.read_text(encoding="utf-8")
        assert "old direct block" not in legacy_text
        assert legacy_text.count(_START_MARKER) == 1
        assert _COMPAT_START_MARKER in legacy_text
