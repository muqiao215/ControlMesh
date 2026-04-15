"""Transport-agnostic media prompt building."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Metadata for a received media file (from any transport)."""

    caption: str | None
    file_name: str
    media_type: str
    original_type: str
    path: Path


def build_media_prompt(
    info: MediaInfo,
    workspace: Path,
    *,
    transport: str = "",
) -> str:
    """Build the prompt injected into the orchestrator for a received file.

    Paths are relative to *workspace* so they work in both host and Docker.
    """
    rel_path: Path | str = info.path
    with contextlib.suppress(ValueError):
        rel_path = info.path.relative_to(workspace)

    via = f" via {transport}" if transport else ""
    lines = [
        "[INCOMING FILE]",
        f"The user sent you a file{via}.",
        f"Path: {rel_path}",
        f"Type: {info.media_type}",
        f"Original filename: {info.file_name}",
        "",
        "Check tools/telegram_tools/CLAUDE.md for file handling instructions.",
    ]

    if info.original_type in ("voice", "audio"):
        lines.append(
            "This is an audio/voice message. Use "
            f"tools/telegram_tools/transcribe_audio.py --file {rel_path} "
            "to transcribe it, then respond to the content."
        )

    if info.original_type in ("video", "video_note"):
        lines.append(
            "This is a video file. Use "
            f"tools/telegram_tools/process_video.py --file {rel_path} "
            "to extract keyframes and transcribe audio, then respond to the content."
        )

    if info.caption:
        lines.append("")
        lines.append(f"User message: {info.caption}")

    return "\n".join(lines)
