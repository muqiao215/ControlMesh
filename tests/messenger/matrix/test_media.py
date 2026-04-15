"""Tests for Matrix media download and prompt building."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from controlmesh.messenger.matrix.media import (
    _mime_from_msgtype,
    _original_type_from_msgtype,
    build_media_prompt,
    download_matrix_media,
    resolve_matrix_media,
)

# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestMimeFromMsgtype:
    def test_image(self) -> None:
        assert _mime_from_msgtype("m.image", "photo.jpg") == "image/png"

    def test_audio(self) -> None:
        assert _mime_from_msgtype("m.audio", "voice.ogg") == "audio/ogg"

    def test_video(self) -> None:
        assert _mime_from_msgtype("m.video", "clip.mp4") == "video/mp4"

    def test_file_guesses_from_name(self) -> None:
        mime = _mime_from_msgtype("m.file", "report.pdf")
        assert mime == "application/pdf"

    def test_unknown_fallback(self) -> None:
        mime = _mime_from_msgtype("m.file", "data_no_ext")
        assert mime == "application/octet-stream"


class TestOriginalTypeFromMsgtype:
    def test_image(self) -> None:
        assert _original_type_from_msgtype("m.image") == "photo"

    def test_audio(self) -> None:
        assert _original_type_from_msgtype("m.audio") == "audio"

    def test_video(self) -> None:
        assert _original_type_from_msgtype("m.video") == "video"

    def test_file(self) -> None:
        assert _original_type_from_msgtype("m.file") == "document"

    def test_unknown_defaults_to_document(self) -> None:
        assert _original_type_from_msgtype("m.whatever") == "document"


class TestBuildMediaPrompt:
    def test_returns_string_with_file_info(self, tmp_path: Path) -> None:
        from controlmesh.files.prompt import MediaInfo

        info = MediaInfo(
            path=tmp_path / "test.pdf",
            media_type="application/pdf",
            file_name="test.pdf",
            caption=None,
            original_type="document",
        )
        result = build_media_prompt(info, tmp_path)
        assert "[INCOMING FILE" in result
        assert "test.pdf" in result
        assert "Matrix" in result


# ---------------------------------------------------------------------------
# Download tests
# ---------------------------------------------------------------------------


class TestDownloadMatrixMedia:
    async def test_returns_none_when_no_url(self) -> None:
        client = AsyncMock()
        event = MagicMock(spec=["body", "source"])
        event.url = None
        event.body = ""
        event.source = {}

        result = await download_matrix_media(client, event, Path("/tmp"))
        assert result is None

    async def test_returns_none_on_download_error(self, tmp_path: Path) -> None:
        """Test that a DownloadError from nio returns None."""
        client = AsyncMock()
        event = MagicMock()
        event.url = "mxc://server/media123"
        event.body = "test.txt"
        event.source = {"content": {"info": {"mimetype": "text/plain"}, "msgtype": "m.file"}}

        # Create a class that nio.DownloadError isinstance checks will match
        class FakeDownloadError:
            message = "Not found"

        error_resp = FakeDownloadError()
        client.download.return_value = error_resp

        with patch(
            "controlmesh.messenger.matrix.media._nio_download_error_type",
            return_value=FakeDownloadError,
        ):
            result = await download_matrix_media(client, event, tmp_path)

        assert result is None

    async def test_successful_download(self, tmp_path: Path) -> None:
        client = AsyncMock()
        event = MagicMock()
        event.url = "mxc://server/media123"
        event.body = "report.pdf"
        event.source = {"content": {"info": {"mimetype": "application/pdf"}, "msgtype": "m.file"}}

        # Mock successful download response
        resp = MagicMock()
        resp.message = None
        client.download.return_value = resp

        with patch(
            "controlmesh.messenger.matrix.media._prepare_destination",
            return_value=tmp_path / "report.pdf",
        ):
            result = await download_matrix_media(client, event, tmp_path)

        assert result is not None
        assert result.file_name == "report.pdf"
        assert result.media_type == "application/pdf"
        assert result.original_type == "document"


# ---------------------------------------------------------------------------
# Resolve matrix media (integration)
# ---------------------------------------------------------------------------


class TestResolveMatrixMedia:
    async def test_returns_none_on_exception(self, tmp_path: Path) -> None:
        client = AsyncMock()
        event = MagicMock()
        event.url = "mxc://server/test"
        callback = AsyncMock()

        with patch(
            "controlmesh.messenger.matrix.media.download_matrix_media",
            side_effect=OSError("disk full"),
        ):
            result = await resolve_matrix_media(
                client,
                event,
                tmp_path,
                tmp_path,
                error_callback=callback,
            )

        assert result is None
        callback.assert_awaited_once_with("Could not download that file.")

    async def test_returns_none_when_error_callback_raises(self, tmp_path: Path) -> None:
        """error_callback failure must not propagate."""
        client = AsyncMock()
        event = MagicMock()
        event.url = "mxc://server/test"
        callback = AsyncMock(side_effect=OSError("send failed"))

        with patch(
            "controlmesh.messenger.matrix.media.download_matrix_media",
            side_effect=RuntimeError("boom"),
        ):
            result = await resolve_matrix_media(
                client,
                event,
                tmp_path,
                tmp_path,
                error_callback=callback,
            )

        assert result is None
        callback.assert_awaited_once()

    async def test_returns_none_when_download_returns_none(self, tmp_path: Path) -> None:
        client = AsyncMock()
        event = MagicMock()

        with patch(
            "controlmesh.messenger.matrix.media.download_matrix_media",
            return_value=None,
        ):
            result = await resolve_matrix_media(client, event, tmp_path, tmp_path)

        assert result is None

    async def test_returns_prompt_on_success(self, tmp_path: Path) -> None:
        from controlmesh.files.prompt import MediaInfo

        client = AsyncMock()
        event = MagicMock()
        info = MediaInfo(
            path=tmp_path / "test.jpg",
            media_type="image/jpeg",
            file_name="test.jpg",
            caption=None,
            original_type="photo",
        )

        with (
            patch(
                "controlmesh.messenger.matrix.media.download_matrix_media",
                return_value=info,
            ),
            patch(
                "controlmesh.messenger.matrix.media._update_index",
            ),
        ):
            result = await resolve_matrix_media(client, event, tmp_path, tmp_path)

        assert result is not None
        assert "[INCOMING FILE" in result
