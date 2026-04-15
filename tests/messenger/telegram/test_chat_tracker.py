"""Tests for ChatTracker persistence and record management."""

from __future__ import annotations

from pathlib import Path

from controlmesh.messenger.telegram.chat_tracker import ChatRecord, ChatTracker


class TestChatTracker:
    """ChatTracker: record, persist, load, get_all."""

    def test_record_join_creates_entry(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_join(-1001, "supergroup", "Dev Group", allowed=True)

        records = tracker.get_all()
        assert len(records) == 1
        assert records[0].chat_id == -1001
        assert records[0].chat_type == "supergroup"
        assert records[0].title == "Dev Group"
        assert records[0].status == "active"
        assert records[0].allowed is True

    def test_record_join_updates_existing(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_join(-1001, "group", "Old Name", allowed=True)
        tracker.record_join(-1001, "supergroup", "New Name", allowed=True)

        records = tracker.get_all()
        assert len(records) == 1
        assert records[0].chat_type == "supergroup"
        assert records[0].title == "New Name"

    def test_record_leave(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_join(-1001, "group", "Group", allowed=True)
        tracker.record_leave(-1001, "kicked")

        records = tracker.get_all()
        assert records[0].status == "kicked"

    def test_record_leave_unknown_chat(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_leave(-9999, "left")

        records = tracker.get_all()
        assert len(records) == 1
        assert records[0].status == "left"

    def test_record_rejected(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_rejected(-1001, "group", "Spam Group")
        tracker.record_rejected(-1001, "group", "Spam Group")

        records = tracker.get_all()
        assert len(records) == 1
        assert records[0].rejected_count == 2
        assert records[0].allowed is False

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "chat.json"
        tracker = ChatTracker(path)
        tracker.record_join(-1001, "supergroup", "Persistent Group", allowed=True)
        tracker.record_rejected(-2002, "group", "Bad Group")

        # Load a fresh tracker from the same file
        tracker2 = ChatTracker(path)
        records = tracker2.get_all()
        assert len(records) == 2
        ids = {r.chat_id for r in records}
        assert ids == {-1001, -2002}

    def test_get_all_sorted_by_last_seen(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "chat.json")
        tracker.record_join(-1, "group", "First", allowed=True)
        tracker.record_join(-2, "group", "Second", allowed=True)

        # Manually set different timestamps to guarantee order
        tracker._records[-1].last_seen = "2025-01-01T00:00:00+00:00"
        tracker._records[-2].last_seen = "2025-01-01T00:00:01+00:00"

        records = tracker.get_all()
        assert records[0].chat_id == -2  # newer
        assert records[1].chat_id == -1  # older

    def test_empty_file_loads_cleanly(self, tmp_path: Path) -> None:
        path = tmp_path / "chat.json"
        path.write_text("{}")
        tracker = ChatTracker(path)
        assert tracker.get_all() == []

    def test_missing_file_loads_cleanly(self, tmp_path: Path) -> None:
        tracker = ChatTracker(tmp_path / "nonexistent.json")
        assert tracker.get_all() == []


class TestChatRecord:
    """ChatRecord dataclass defaults."""

    def test_defaults(self) -> None:
        rec = ChatRecord(chat_id=42)
        assert rec.chat_type == "private"
        assert rec.title == ""
        assert rec.status == "active"
        assert rec.allowed is True
        assert rec.rejected_count == 0
