"""Tests for Feishu outbound media metadata helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


def _box(kind: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def test_parse_ogg_opus_duration_from_last_granule() -> None:
    from controlmesh.messenger.feishu.media_meta import parse_ogg_opus_duration

    granule = 96_000
    data = b"prefixOggS\x00\x00" + granule.to_bytes(8, "little") + b"tail"

    assert parse_ogg_opus_duration(data) == 2000


def test_parse_mp4_duration_from_mvhd() -> None:
    from controlmesh.messenger.feishu.media_meta import parse_mp4_duration

    mvhd_payload = (
        b"\x00\x00\x00\x00"
        + (0).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
        + (1000).to_bytes(4, "big")
        + (2500).to_bytes(4, "big")
    )
    data = _box(b"moov", _box(b"mvhd", mvhd_payload))

    assert parse_mp4_duration(data) == 2500


def test_prepare_audio_upload_native_opus_reads_duration(tmp_path: Path) -> None:
    from controlmesh.messenger.feishu.media_meta import prepare_audio_upload

    path = tmp_path / "voice.ogg"
    path.write_bytes(b"OggS\x00\x00" + (48_000).to_bytes(8, "little"))

    result = prepare_audio_upload(path, "audio/ogg")

    assert result.path == path
    assert result.duration_ms == 1000
    assert result.cleanup_path is None


def test_prepare_audio_upload_common_audio_requires_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from controlmesh.messenger.feishu.media_meta import prepare_audio_upload

    path = tmp_path / "voice.mp3"
    path.write_bytes(b"mp3")
    monkeypatch.setattr("controlmesh.messenger.feishu.media_meta.shutil.which", lambda _cmd: None)

    with pytest.raises(RuntimeError, match="ffmpeg not available"):
        prepare_audio_upload(path, "audio/mpeg")
