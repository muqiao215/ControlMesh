"""WorkUnit detection and topology policy."""

from __future__ import annotations

import re

from controlmesh.routing.workunit import WorkUnitKind, normalize_workunit_kind

_TEST_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(uv\s+run\s+)?pytest\b",
        r"^\s*(npm|pnpm|yarn|bun)\s+(run\s+)?test\b",
        r"^\s*playwright\s+test\b",
        r"^\s*(uv\s+run\s+)?mypy\b",
        r"^\s*(uv\s+run\s+)?ruff\b",
        r"^\s*cargo\s+test\b",
        r"^\s*go\s+test\b",
    )
)

_REVIEW_WORDS = ("review", "审查", "复查", "code review")
_PATCH_WORDS = ("fix", "修复", "patch", "改代码", "补丁")

TOPOLOGY_ALIASES: dict[str, str] = {
    "background_single": "",
    "test_lane": "",
    "review_fanout": "fanout_merge",
    "patch_lane": "director_worker",
}

DEFAULT_TOPOLOGY_BY_KIND: dict[WorkUnitKind, str] = {
    WorkUnitKind.TEST_EXECUTION: "",
    WorkUnitKind.CODE_REVIEW: "fanout_merge",
    WorkUnitKind.PATCH_CANDIDATE: "director_worker",
}


def detect_workunit_kind(
    *,
    explicit: str = "",
    command: str = "",
    prompt: str = "",
    target: str = "",
    evidence: str = "",
) -> WorkUnitKind | None:
    """Classify a task request into the MVP WorkUnit kinds."""
    explicit_kind = normalize_workunit_kind(explicit)
    if explicit_kind is not None:
        return explicit_kind
    if command and any(pattern.search(command) for pattern in _TEST_COMMAND_PATTERNS):
        return WorkUnitKind.TEST_EXECUTION
    haystack = " ".join(part for part in (prompt, target, evidence, command) if part).lower()
    if any(word in haystack for word in _PATCH_WORDS):
        return WorkUnitKind.PATCH_CANDIDATE
    if any(word in haystack for word in _REVIEW_WORDS):
        return WorkUnitKind.CODE_REVIEW
    return None


def normalize_topology(value: str) -> str:
    """Normalize routing topology aliases to current TaskHub topology names."""
    normalized = value.strip()
    return TOPOLOGY_ALIASES.get(normalized, normalized)


def default_topology_for_kind(kind: WorkUnitKind) -> str:
    """Return the current TaskHub-compatible default topology for a WorkUnit."""
    return DEFAULT_TOPOLOGY_BY_KIND[kind]
