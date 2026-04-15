"""Tests for atomic file write primitives."""

from __future__ import annotations

from pathlib import Path

from controlmesh.infra.atomic_io import atomic_bytes_save, atomic_text_save


class TestAtomicTextSave:
    def test_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        atomic_text_save(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested" / "file.txt"
        atomic_text_save(target, "content")
        assert target.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        target.write_text("old", encoding="utf-8")
        atomic_text_save(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_leftover_temp_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.txt"
        atomic_text_save(target, "data")
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.txt"

    def test_empty_content(self, tmp_path: Path) -> None:
        target = tmp_path / "empty.txt"
        atomic_text_save(target, "")
        assert target.read_text(encoding="utf-8") == ""

    def test_unicode_content(self, tmp_path: Path) -> None:
        target = tmp_path / "unicode.txt"
        atomic_text_save(target, "Ähre wem Ähre gebührt — Ölgötze")
        assert target.read_text(encoding="utf-8") == "Ähre wem Ähre gebührt — Ölgötze"


class TestAtomicBytesSave:
    def test_writes_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        atomic_bytes_save(target, b"hello")
        assert target.read_bytes() == b"hello"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "file.bin"
        atomic_bytes_save(target, b"data")
        assert target.read_bytes() == b"data"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        target.write_bytes(b"old")
        atomic_bytes_save(target, b"new")
        assert target.read_bytes() == b"new"

    def test_no_leftover_temp_file(self, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        atomic_bytes_save(target, b"data")
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.bin"
