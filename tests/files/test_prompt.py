"""Tests for shared media prompt building."""

from __future__ import annotations

from pathlib import Path

from controlmesh.files.prompt import MediaInfo, build_media_prompt


class TestBuildMediaPrompt:
    def test_basic_prompt(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        file_path = workspace / "files" / "2025-06-15" / "photo_abc.jpg"
        file_path.parent.mkdir(parents=True)
        file_path.touch()

        info = MediaInfo(
            path=file_path,
            media_type="image/jpeg",
            file_name="photo_abc.jpg",
            caption=None,
            original_type="photo",
        )
        prompt = build_media_prompt(info, workspace)

        assert "[INCOMING FILE]" in prompt
        expected_rel = str(Path("files/2025-06-15/photo_abc.jpg"))
        assert expected_rel in prompt
        assert "image/jpeg" in prompt

    def test_transport_label_included(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "photo.jpg",
            media_type="image/jpeg",
            file_name="photo.jpg",
            caption=None,
            original_type="photo",
        )
        prompt = build_media_prompt(info, tmp_path, transport="Telegram")
        assert "via Telegram" in prompt

    def test_transport_label_api(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "photo.jpg",
            media_type="image/jpeg",
            file_name="photo.jpg",
            caption=None,
            original_type="photo",
        )
        prompt = build_media_prompt(info, tmp_path, transport="API")
        assert "via API" in prompt

    def test_no_transport_label(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "photo.jpg",
            media_type="image/jpeg",
            file_name="photo.jpg",
            caption=None,
            original_type="photo",
        )
        prompt = build_media_prompt(info, tmp_path)
        assert "sent you a file." in prompt
        assert "via" not in prompt.split("file.")[0]

    def test_voice_prompt_includes_transcription_hint(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "voice.ogg",
            media_type="audio/ogg",
            file_name="voice.ogg",
            caption=None,
            original_type="voice",
        )
        prompt = build_media_prompt(info, tmp_path)
        assert "transcribe_audio.py" in prompt

    def test_video_prompt_includes_process_hint(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "video.mp4",
            media_type="video/mp4",
            file_name="video.mp4",
            caption=None,
            original_type="video",
        )
        prompt = build_media_prompt(info, tmp_path)
        assert "process_video.py" in prompt

    def test_caption_included(self, tmp_path: Path) -> None:
        info = MediaInfo(
            path=tmp_path / "photo.jpg",
            media_type="image/jpeg",
            file_name="photo.jpg",
            caption="Look at this!",
            original_type="photo",
        )
        prompt = build_media_prompt(info, tmp_path)
        assert "User message: Look at this!" in prompt

    def test_relative_path(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        file_path = workspace / "files" / "photo.jpg"

        info = MediaInfo(
            path=file_path,
            media_type="image/jpeg",
            file_name="photo.jpg",
            caption=None,
            original_type="photo",
        )
        prompt = build_media_prompt(info, workspace)

        assert str(workspace) not in prompt
        expected_rel = str(Path("files/photo.jpg"))
        assert expected_rel in prompt
