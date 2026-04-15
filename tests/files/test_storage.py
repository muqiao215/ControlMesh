"""Tests for shared file storage utilities."""

from __future__ import annotations

from pathlib import Path

from controlmesh.files.storage import prepare_destination, sanitize_filename


class TestSanitizeFilename:
    def test_removes_slashes(self) -> None:
        assert sanitize_filename("path/to/file.txt") == "path_to_file.txt"

    def test_removes_null_bytes(self) -> None:
        assert sanitize_filename("file\x00name.txt") == "file_name.txt"

    def test_collapses_underscores(self) -> None:
        assert sanitize_filename("a___b.txt") == "a_b.txt"

    def test_truncates_long_names(self) -> None:
        result = sanitize_filename("x" * 200)
        assert len(result) <= 120

    def test_empty_returns_file(self) -> None:
        assert sanitize_filename("...") == "file"

    def test_backslashes(self) -> None:
        assert sanitize_filename("C:\\Users\\file.txt") == "C_Users_file.txt"

    def test_windows_illegal_chars(self) -> None:
        assert sanitize_filename("file<script>.txt") == "file_script_.txt"
        assert sanitize_filename("data|pipe.csv") == "data_pipe.csv"
        assert sanitize_filename('note"s.txt') == "note_s.txt"
        assert sanitize_filename("who?.txt") == "who_.txt"
        assert sanitize_filename("star*.log") == "star_.log"


class TestPrepareDestination:
    def test_creates_date_dir(self, tmp_path: Path) -> None:
        dest = prepare_destination(tmp_path, "test.jpg")
        assert dest.parent.exists()
        assert len(dest.parent.name) == 10
        assert dest.parent.name[4] == "-"

    def test_collision_avoidance(self, tmp_path: Path) -> None:
        dest1 = prepare_destination(tmp_path, "test.jpg")
        dest1.touch()

        dest2 = prepare_destination(tmp_path, "test.jpg")
        assert dest2 != dest1
        assert "test_1.jpg" in dest2.name

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        dest1 = prepare_destination(tmp_path, "file.pdf")
        dest1.touch()

        dest2 = prepare_destination(tmp_path, "file.pdf")
        dest2.touch()

        dest3 = prepare_destination(tmp_path, "file.pdf")
        assert dest3.name == "file_2.pdf"
