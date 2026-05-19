"""Injection defense: detect suspicious patterns and wrap external content."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_SUSPICIOUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)", re.IGNORECASE
        ),
        "instruction_override",
    ),
    (
        re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
        "instruction_override",
    ),
    (
        re.compile(r"forget\s+(everything|all|your)\s+(instructions?|rules?)", re.IGNORECASE),
        "instruction_override",
    ),
    (
        re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.IGNORECASE),
        "role_hijack",
    ),
    (
        re.compile(r"new\s+instructions?:", re.IGNORECASE),
        "role_hijack",
    ),
    (
        re.compile(r"system\s*:\s*prompt", re.IGNORECASE),
        "fake_system_prompt",
    ),
    (
        re.compile(r"<\|(?:im_start|im_end|system|endoftext)\|>", re.IGNORECASE),
        "special_token",
    ),
    (
        re.compile(r"\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>", re.IGNORECASE),
        "llama_markers",
    ),
    (
        re.compile(r"(?:^|\n)\s*(?:Human|Assistant|System)\s*:", re.IGNORECASE),
        "anthropic_markers",
    ),
    (
        re.compile(
            r"GROUND_RULES|(?:AGENT_)?SOUL\.md|(?:AGENT_)?SYSTEM\.md"
            r"|BOOTSTRAP\.md|(?:AGENT_)?IDENTITY\.md",
            re.IGNORECASE,
        ),
        "internal_file_ref",
    ),
    (
        re.compile(r"mem_add\.py|mem_edit\.py|mem_delete\.py|task_add\.py", re.IGNORECASE),
        "tool_injection",
    ),
    (
        re.compile(r"--system-prompt|--append-system-prompt|--permission-mode", re.IGNORECASE),
        "cli_flag_injection",
    ),
    (
        re.compile(r"<file:[^>]+>", re.IGNORECASE),
        "file_tag_injection",
    ),
    (
        re.compile(
            r'(?:^|\n)\s*(?:\{)?\"type\"\s*:\s*\"(?:thread\.started|turn\.started|item\.(?:started|updated|completed))\"',
            re.IGNORECASE,
        ),
        "raw_agent_event_stream",
    ),
]

_FULLWIDTH_RE = re.compile(r"[\uFF21-\uFF3A\uFF41-\uFF5A\uFF1C\uFF1E]")
_FULLWIDTH_ASCII_OFFSET = 0xFEE0
_CHAT_TRANSCRIPT_LABEL_RE = re.compile(r"^\s*([^:\n]{1,40})\s*:\s*$")


def _fold_fullwidth_char(match: re.Match[str]) -> str:
    code = ord(match.group())
    if (0xFF21 <= code <= 0xFF3A) or (0xFF41 <= code <= 0xFF5A):
        return chr(code - _FULLWIDTH_ASCII_OFFSET)
    if code == 0xFF1C:
        return "<"
    if code == 0xFF1E:
        return ">"
    return match.group()  # pragma: no cover


def _fold_fullwidth(text: str) -> str:
    return _FULLWIDTH_RE.sub(_fold_fullwidth_char, text)


def extract_pasted_chat_transcript_message(text: str) -> str | None:
    """Extract the last actual message from a pasted multi-speaker transcript."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return None

    speakers: set[str] = set()
    labeled_lines = 0
    last_label_index: int | None = None
    for idx, line in enumerate(lines):
        match = _CHAT_TRANSCRIPT_LABEL_RE.match(line)
        if match is None:
            continue
        speaker = match.group(1).strip()
        if not speaker:
            continue
        if speaker.startswith(("http", "@", "/", "#")):
            continue
        if any(ch in speaker for ch in "<>{}[]|"):
            continue
        if idx + 1 >= len(lines) or _CHAT_TRANSCRIPT_LABEL_RE.match(lines[idx + 1]):
            continue
        speakers.add(speaker)
        labeled_lines += 1
        last_label_index = idx

    if labeled_lines < 2 or len(speakers) < 2 or last_label_index is None:
        return None
    payload = "\n".join(lines[last_label_index + 1 :]).strip()
    return payload or None


def looks_like_pasted_chat_transcript(text: str) -> bool:
    """Return True when text looks like a pasted multi-speaker transcript."""
    return extract_pasted_chat_transcript_message(text) is not None


def classify_inbound_text(text: str) -> str:
    """Classify inbound Telegram text for mailbox routing."""
    stripped = text.strip()
    if not stripped:
        return "quarantine"
    if stripped.startswith("/"):
        return "control_command"
    if extract_pasted_chat_transcript_message(stripped) is not None:
        return "pasted_transcript_extractable"
    if detect_suspicious_patterns(stripped):
        return "quarantine"
    return "normal_chat"


def detect_suspicious_patterns(text: str) -> list[str]:
    """Scan text for prompt injection patterns. Empty list = clean."""
    folded = _fold_fullwidth(text)
    found = [name for pattern, name in _SUSPICIOUS_PATTERNS if pattern.search(folded)]
    if found:
        logger.warning("Suspicious patterns detected patterns=%s", found)
    else:
        logger.debug("Content scan clean")
    return found
