"""Media metadata helpers for Feishu outbound uploads."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from os import close
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PreparedAudioUpload:
    """Resolved audio upload payload."""

    path: Path
    duration_ms: int | None
    cleanup_path: Path | None = None


def parse_ogg_opus_duration(data: bytes) -> int | None:
    """Parse OGG/Opus duration from the last Ogg page granule position."""
    marker = b"OggS"
    offset = data.rfind(marker)
    if offset < 0:
        return None
    granule_offset = offset + 6
    if granule_offset + 8 > len(data):
        return None
    lo = int.from_bytes(data[granule_offset : granule_offset + 4], "little")
    hi = int.from_bytes(data[granule_offset + 4 : granule_offset + 8], "little")
    granule = (hi << 32) | lo
    if granule <= 0:
        return None
    return ((granule * 1000) + 47_999) // 48_000


def parse_mp4_duration(data: bytes) -> int | None:
    """Parse MP4 duration from the `mvhd` box."""
    moov = _find_box(data, 0, len(data), b"moov")
    mvhd = _find_box(data, moov[0], moov[1], b"mvhd") if moov is not None else None
    payload = _read_mp4_mvhd_payload(data, mvhd[0]) if mvhd is not None else None
    if payload is None:
        return None
    timescale, duration = payload
    return round((duration / timescale) * 1000) if timescale > 0 and duration > 0 else None


def prepare_audio_upload(path: Path, mime: str) -> PreparedAudioUpload:
    """Return an audio upload payload, transcoding to Opus when needed."""
    suffix = path.suffix.lower()
    if suffix in {".ogg", ".opus"}:
        return PreparedAudioUpload(path=path, duration_ms=parse_ogg_opus_duration(path.read_bytes()))
    if mime.startswith("audio/") and suffix in {".mp3", ".wav", ".m4a"}:
        converted = transcode_audio_to_opus(path)
        duration_ms = parse_ogg_opus_duration(converted.read_bytes())
        return PreparedAudioUpload(
            path=converted,
            duration_ms=duration_ms,
            cleanup_path=converted if converted != path else None,
        )
    return PreparedAudioUpload(path=path, duration_ms=None)


def transcode_audio_to_opus(path: Path) -> Path:
    """Transcode common audio formats to OGG/Opus using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        msg = "ffmpeg not available for Feishu audio transcode"
        raise RuntimeError(msg)
    fd, temp_name = tempfile.mkstemp(prefix="controlmesh-feishu-audio-", suffix=".ogg")
    output_path = Path(temp_name)
    close(fd)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-c:a",
                "libopus",
                "-vn",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        output_path.unlink(missing_ok=True)
        msg = result.stderr.strip() or "ffmpeg transcode failed"
        raise RuntimeError(msg)
    return output_path


def _find_box(data: bytes, start: int, end: int, target: bytes) -> tuple[int, int] | None:
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        if size == 0:
            box_end = end
            data_start = offset + 8
        elif size == 1:
            if offset + 16 > end:
                return None
            box_end = offset + int.from_bytes(data[offset + 8 : offset + 16], "big")
            data_start = offset + 16
        else:
            if size < 8:
                return None
            box_end = offset + size
            data_start = offset + 8
        if box_type == target:
            return data_start, min(box_end, end)
        if box_end <= offset:
            return None
        offset = box_end
    return None


def _read_mp4_mvhd_payload(data: bytes, offset: int) -> tuple[int, int] | None:
    if offset + 1 > len(data):
        return None
    version = data[offset]
    if version == 0:
        if offset + 20 > len(data):
            return None
        return (
            int.from_bytes(data[offset + 12 : offset + 16], "big"),
            int.from_bytes(data[offset + 16 : offset + 20], "big"),
        )
    if offset + 32 > len(data):
        return None
    return (
        int.from_bytes(data[offset + 20 : offset + 24], "big"),
        int.from_bytes(data[offset + 24 : offset + 32], "big"),
    )
