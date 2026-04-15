"""Shared utilities for interactive selector widgets."""

from __future__ import annotations


def format_age(seconds: float) -> str:
    """Format elapsed seconds as compact human-readable string (45s / 2m / 3h / 1d)."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"
