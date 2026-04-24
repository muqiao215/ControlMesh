"""Inbound media/context helpers for the direct official QQ runtime."""

from __future__ import annotations

import base64
import json
import re
from typing import Any

_FACE_TAG_RE = re.compile(r'<faceType=\d+,faceId="[^"]*",ext="([^"]*)">')


def build_inbound_text(
    base_text: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
    quoted_element: dict[str, Any] | None = None,
) -> str:
    """Build the narrowest useful inbound text context from QQ payload fields."""
    sections: list[str] = []

    quoted = _format_quoted_element(quoted_element)
    if quoted:
        sections.append(f"Quoted message:\n{quoted}")

    cleaned = _clean_text(_parse_face_tags(base_text))
    if cleaned:
        sections.append(cleaned)

    attachment_context = _format_attachments(attachments)
    if attachment_context:
        sections.append(attachment_context)

    return "\n\n".join(section for section in sections if section)


def extract_quoted_element(
    payload: dict[str, Any],
    *,
    ref_msg_idx: str | None,
) -> dict[str, Any] | None:
    """Return the best quoted message element from msg_elements when present."""
    raw = payload.get("msg_elements")
    if not isinstance(raw, list):
        return None

    if ref_msg_idx:
        matched = _find_msg_element(raw, ref_msg_idx)
        if matched is not None:
            return matched

    first = raw[0] if raw else None
    return first if isinstance(first, dict) else None


def _format_quoted_element(element: dict[str, Any] | None) -> str:
    if not isinstance(element, dict):
        return ""

    lines = _collect_msg_element_lines(element, seen=set())
    return "\n".join(dict.fromkeys(line for line in lines if line)).strip()


def _find_msg_element(elements: list[Any], ref_msg_idx: str) -> dict[str, Any] | None:
    for item in elements:
        if not isinstance(item, dict):
            continue
        if item.get("msg_idx") == ref_msg_idx:
            return item
        nested = item.get("msg_elements")
        if isinstance(nested, list):
            matched = _find_msg_element(nested, ref_msg_idx)
            if matched is not None:
                return matched
    return None


def _collect_msg_element_lines(
    element: dict[str, Any],
    *,
    seen: set[int],
    depth: int = 0,
    max_depth: int = 4,
) -> list[str]:
    marker = id(element)
    if marker in seen or depth > max_depth:
        return []
    seen.add(marker)

    lines: list[str] = []
    content = _clean_text(_parse_face_tags(element.get("content")))
    if content:
        lines.append(content)

    attachments = element.get("attachments")
    if isinstance(attachments, list):
        attachment_summary = _format_attachments(attachments)
        if attachment_summary:
            lines.extend(line for line in attachment_summary.splitlines() if line)

    nested = element.get("msg_elements")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                lines.extend(
                    _collect_msg_element_lines(
                        item,
                        seen=seen,
                        depth=depth + 1,
                        max_depth=max_depth,
                    )
                )
    return lines


def _format_attachments(attachments: list[dict[str, Any]] | None) -> str:
    if not attachments:
        return ""

    lines: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue

        asr_text = _clean_text(item.get("asr_refer_text"))
        if asr_text:
            lines.append(f"Voice transcript: {asr_text}")

        url = item.get("voice_wav_url") or item.get("url")
        content_type = _clean_text(item.get("content_type"))
        filename = _clean_text(item.get("filename"))
        if not isinstance(url, str) or not url:
            fallback = _format_attachment_without_url(
                content_type=content_type,
                filename=filename,
                transcript=asr_text,
            )
            if fallback:
                lines.append(fallback)
            continue

        label = filename or content_type or "attachment"
        if content_type and filename:
            label = f"{filename} ({content_type})"
        lines.append(f"Attachment: {label} {url}")

    return "\n".join(dict.fromkeys(lines))


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _parse_face_tags(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""

    def _replace(match: re.Match[str]) -> str:
        ext = match.group(1)
        try:
            decoded = base64.b64decode(ext).decode("utf-8")
            parsed = json.loads(decoded)
        except Exception:
            return match.group(0)
        text = parsed.get("text") if isinstance(parsed, dict) else None
        if not isinstance(text, str) or not text:
            return match.group(0)
        return f"【表情: {text}】"

    return _FACE_TAG_RE.sub(_replace, value)


def _format_attachment_without_url(
    *,
    content_type: str,
    filename: str,
    transcript: str,
) -> str:
    lowered = content_type.casefold()
    if lowered.startswith("image/"):
        return f"[图片: {filename}]" if filename else "[图片]"
    if (
        lowered == "voice"
        or lowered.startswith("audio/")
        or "silk" in lowered
        or "amr" in lowered
    ):
        if transcript:
            return f'[语音消息（内容: "{transcript}"）]'
        return "[语音消息]"
    if lowered.startswith("video/"):
        return f"[视频: {filename}]" if filename else "[视频]"
    if lowered.startswith("application/") or lowered.startswith("text/"):
        return f"[文件: {filename}]" if filename else "[文件]"
    if filename:
        return f"[附件: {filename}]"
    return "[附件]"
