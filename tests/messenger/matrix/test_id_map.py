"""Tests for matrix/id_map.py: room_id ↔ int mapping."""

from __future__ import annotations

from pathlib import Path

from controlmesh.messenger.matrix.id_map import MatrixIdMap


class TestMatrixIdMap:
    def test_room_to_int_deterministic(self, tmp_path: Path) -> None:
        m = MatrixIdMap(tmp_path)
        a = m.room_to_int("!abc:server")
        b = m.room_to_int("!abc:server")
        assert a == b

    def test_different_rooms_different_ids(self, tmp_path: Path) -> None:
        m = MatrixIdMap(tmp_path)
        a = m.room_to_int("!room1:server")
        b = m.room_to_int("!room2:server")
        assert a != b

    def test_int_to_room_roundtrip(self, tmp_path: Path) -> None:
        m = MatrixIdMap(tmp_path)
        int_id = m.room_to_int("!test:example.com")
        assert m.int_to_room(int_id) == "!test:example.com"

    def test_int_to_room_unknown(self, tmp_path: Path) -> None:
        m = MatrixIdMap(tmp_path)
        assert m.int_to_room(999999) is None

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        m1 = MatrixIdMap(tmp_path)
        int_id = m1.room_to_int("!persist:server")

        m2 = MatrixIdMap(tmp_path)
        assert m2.room_to_int("!persist:server") == int_id
        assert m2.int_to_room(int_id) == "!persist:server"

    def test_corrupt_file_starts_fresh(self, tmp_path: Path) -> None:
        (tmp_path / "room_id_map.json").write_text("{bad json", encoding="utf-8")
        m = MatrixIdMap(tmp_path)
        int_id = m.room_to_int("!new:server")
        assert isinstance(int_id, int)

    def test_multiple_rooms_all_unique(self, tmp_path: Path) -> None:
        m = MatrixIdMap(tmp_path)
        ids = {m.room_to_int(f"!room{i}:server") for i in range(50)}
        assert len(ids) == 50
