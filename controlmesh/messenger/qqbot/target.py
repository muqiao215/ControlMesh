"""Pure QQ Bot target parsing helpers."""

from __future__ import annotations

import re

from controlmesh.messenger.qqbot.types import ParsedQQTarget

_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_target(target: str) -> ParsedQQTarget:
    """Parse a QQ Bot target string into its canonical shape."""
    normalized = target.replace("qqbot:", "", 1) if target.lower().startswith("qqbot:") else target

    if normalized.startswith("c2c:"):
        value = normalized[4:]
        if not value:
            msg = f"Invalid c2c target format: {target} - missing user ID"
            raise ValueError(msg)
        return ParsedQQTarget(type="c2c", id=value)

    if normalized.startswith("group:"):
        value = normalized[6:]
        if not value:
            msg = f"Invalid group target format: {target} - missing group ID"
            raise ValueError(msg)
        return ParsedQQTarget(type="group", id=value)

    if normalized.startswith("channel:"):
        value = normalized[8:]
        if not value:
            msg = f"Invalid channel target format: {target} - missing channel ID"
            raise ValueError(msg)
        return ParsedQQTarget(type="channel", id=value)

    if normalized.startswith("dm:"):
        value = normalized[3:]
        if not value:
            msg = f"Invalid dm target format: {target} - missing guild ID"
            raise ValueError(msg)
        return ParsedQQTarget(type="dm", id=value)

    if not normalized:
        msg = f"Invalid target format: {target} - empty ID after removing qqbot: prefix"
        raise ValueError(msg)

    return ParsedQQTarget(type="c2c", id=normalized)


def normalize_target(target: str) -> str | None:
    """Return canonical `qqbot:...` form when the input looks like a QQ target."""
    normalized = target.replace("qqbot:", "", 1) if target.lower().startswith("qqbot:") else target
    if normalized.startswith(("c2c:", "group:", "channel:", "dm:")):
        return f"qqbot:{normalized}"
    if _HEX32_RE.match(normalized) or _UUID_RE.match(normalized):
        return f"qqbot:c2c:{normalized}"
    return None


def looks_like_qqbot_target(value: str) -> bool:
    """Return True when a string looks like a QQ Bot target."""
    if re.match(r"^qqbot:(c2c|group|channel|dm):", value, flags=re.IGNORECASE):
        return True
    if re.match(r"^(c2c|group|channel|dm):", value, flags=re.IGNORECASE):
        return True
    return bool(_HEX32_RE.match(value) or _UUID_RE.match(value))
