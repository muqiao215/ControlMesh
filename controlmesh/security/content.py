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
]

_FULLWIDTH_RE = re.compile(r"[\uFF21-\uFF3A\uFF41-\uFF5A\uFF1C\uFF1E]")
_FULLWIDTH_ASCII_OFFSET = 0xFEE0


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


def detect_suspicious_patterns(text: str) -> list[str]:
    """Scan text for prompt injection patterns. Empty list = clean."""
    folded = _fold_fullwidth(text)
    found = [name for pattern, name in _SUSPICIOUS_PATTERNS if pattern.search(folded)]
    if found:
        logger.warning("Suspicious patterns detected patterns=%s", found)
    else:
        logger.debug("Content scan clean")
    return found
