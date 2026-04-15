"""Tests for shared file tag parsing, MIME detection, and classification."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from controlmesh.files.tags import (
    classify_mime,
    extract_file_paths,
    guess_mime,
    is_image_path,
    path_from_file_tag,
)


class TestExtractFilePaths:
    def test_single_file(self) -> None:
        assert extract_file_paths("see <file:/tmp/a.txt>") == ["/tmp/a.txt"]

    def test_multiple_files(self) -> None:
        assert extract_file_paths("<file:/a> and <file:/b>") == ["/a", "/b"]

    def test_no_files(self) -> None:
        assert extract_file_paths("no files here") == []

    def test_file_with_spaces(self) -> None:
        assert extract_file_paths("<file:/tmp/my file.txt>") == ["/tmp/my file.txt"]


class TestIsImagePath:
    def test_jpg(self) -> None:
        assert is_image_path("/tmp/photo.jpg") is True

    def test_png(self) -> None:
        assert is_image_path("/tmp/image.png") is True

    def test_gif(self) -> None:
        assert is_image_path("/tmp/anim.gif") is True

    def test_webp(self) -> None:
        assert is_image_path("/tmp/photo.webp") is True

    def test_svg_excluded(self) -> None:
        assert is_image_path("/tmp/icon.svg") is False

    def test_pdf_not_image(self) -> None:
        assert is_image_path("/tmp/doc.pdf") is False

    def test_txt_not_image(self) -> None:
        assert is_image_path("/tmp/notes.txt") is False


class TestGuessMime:
    def test_jpeg_magic_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert guess_mime(f) == "image/jpeg"

    def test_png_magic_bytes(self, tmp_path: Path) -> None:
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        assert guess_mime(f) == "image/png"

    def test_text_falls_back_to_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.txt"
        f.write_text("hello world")
        assert guess_mime(f) == "text/plain"

    def test_python_falls_back_to_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "script.py"
        f.write_text("print('hi')")
        mime = guess_mime(f)
        assert "python" in mime or mime == "text/x-python"

    def test_unknown_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xyz123"
        f.write_bytes(b"\x00" * 10)
        assert guess_mime(f) == "application/octet-stream"

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert guess_mime(str(f)) == "image/jpeg"


class TestClassifyMime:
    def test_image(self) -> None:
        assert classify_mime("image/jpeg") == "photo"

    def test_audio(self) -> None:
        assert classify_mime("audio/ogg") == "audio"

    def test_video(self) -> None:
        assert classify_mime("video/mp4") == "video"

    def test_document_pdf(self) -> None:
        assert classify_mime("application/pdf") == "document"

    def test_document_text(self) -> None:
        assert classify_mime("text/plain") == "document"

    def test_document_octet_stream(self) -> None:
        assert classify_mime("application/octet-stream") == "document"


class TestPathFromFileTag:
    def test_windows_path_slash_drive_form(self) -> None:
        with patch("controlmesh.files.tags.is_windows", return_value=True):
            path = path_from_file_tag("/C/Users/alice/out.zip")
        assert str(path).replace("\\", "/") == "C:/Users/alice/out.zip"

    def test_windows_file_uri_variants(self) -> None:
        variants = [
            "file:/C/Users/alice/out.zip",
            "file:///C:/Users/alice/out.zip",
            "file://C:/Users/alice/out.zip",
        ]
        with patch("controlmesh.files.tags.is_windows", return_value=True):
            parsed = [path_from_file_tag(v) for v in variants]
        normalized = [str(p).replace("\\", "/") for p in parsed]
        assert normalized == [
            "C:/Users/alice/out.zip",
            "C:/Users/alice/out.zip",
            "C:/Users/alice/out.zip",
        ]

    def test_windows_file_uri_decodes_spaces(self) -> None:
        with patch("controlmesh.files.tags.is_windows", return_value=True):
            path = path_from_file_tag("file:///C:/Users/alice/My%20File.zip")
        assert str(path).replace("\\", "/") == "C:/Users/alice/My File.zip"

    def test_posix_path_unchanged(self) -> None:
        with patch("controlmesh.files.tags.is_windows", return_value=False):
            path = path_from_file_tag("/tmp/out.zip")
        # On Windows Path("/tmp/out.zip") uses backslash; normalize for assertion
        assert str(path).replace("\\", "/") == "/tmp/out.zip"

    def test_docker_path_translated(self) -> None:
        with (
            patch.dict("os.environ", {"CONTROLMESH_HOME": "/home/user/.controlmesh"}),
            patch("controlmesh.files.tags.is_windows", return_value=False),
        ):
            path = path_from_file_tag("/controlmesh/workspace/output_to_user/img.png")
        assert path == Path("/home/user/.controlmesh/workspace/output_to_user/img.png")

    def test_docker_path_root(self) -> None:
        with (
            patch.dict("os.environ", {"CONTROLMESH_HOME": "/home/user/.controlmesh"}),
            patch("controlmesh.files.tags.is_windows", return_value=False),
        ):
            path = path_from_file_tag("/controlmesh/sessions.json")
        assert path == Path("/home/user/.controlmesh/sessions.json")

    def test_non_docker_path_not_translated(self) -> None:
        with patch("controlmesh.files.tags.is_windows", return_value=False):
            path = path_from_file_tag("/home/user/.controlmesh/workspace/file.txt")
        assert path == Path("/home/user/.controlmesh/workspace/file.txt")
