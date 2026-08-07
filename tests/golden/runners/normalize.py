"""Golden fixture normalization helpers."""

from __future__ import annotations

from typing import Any


def normalize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(value)
    for key in ("created_at", "completed_at", "timestamp"):
        if key in normalized:
            normalized[key] = "<timestamp>"
    if "task_id" in normalized:
        normalized["task_id"] = "<task_id>"
    return normalized
