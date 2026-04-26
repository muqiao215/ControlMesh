"""Helpers for packaging oversized frontstage chat replies."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from controlmesh.files.tags import FILE_PATH_RE
from controlmesh.text.response_format import SEP, compact_transport_text, fmt

FRONTSTAGE_ATTACHMENT_MIN_CHARS = 3500
FRONTSTAGE_ATTACHMENT_MIN_LINES = 40
FRONTSTAGE_PREVIEW_MAX_CHARS = 1600
FRONTSTAGE_PREVIEW_MAX_LINES = 24


def prepare_frontstage_text(
    text: str,
    *,
    output_dir: Path | None,
    supports_attachments: bool = True,
    filename_prefix: str = "controlmesh-reply",
) -> str:
    """Convert oversized replies into preview-first frontstage text.

    Short replies pass through unchanged. Oversized replies are compacted for
    chat, and when attachments are supported the full body is written to
    ``output_dir`` and referenced via a ``<file:...>`` tag.
    """
    clean = (text or "").strip()
    if not clean or FILE_PATH_RE.search(clean):
        return text
    if not _should_attach(clean):
        return text

    preview = compact_transport_text(
        clean,
        max_chars=FRONTSTAGE_PREVIEW_MAX_CHARS,
        max_lines=FRONTSTAGE_PREVIEW_MAX_LINES,
        include_note=False,
    )
    if not supports_attachments or output_dir is None:
        return fmt(preview, SEP, "Output trimmed for chat view. Ask for the full result if you need it.")

    artifact_path = _write_full_output_artifact(
        output_dir=output_dir,
        text=clean,
        filename_prefix=filename_prefix,
    )
    return fmt(preview, SEP, "Full output attached.", f"<file:{artifact_path}>")


def _should_attach(text: str) -> bool:
    lines = text.splitlines()
    return len(text) > FRONTSTAGE_ATTACHMENT_MIN_CHARS or len(lines) > FRONTSTAGE_ATTACHMENT_MIN_LINES


def _write_full_output_artifact(
    *,
    output_dir: Path,
    text: str,
    filename_prefix: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    digest = sha256(text.encode("utf-8")).hexdigest()[:8]
    path = output_dir / f"{filename_prefix}-{stamp}-{digest}.md"
    path.write_text(text, encoding="utf-8")
    return path
