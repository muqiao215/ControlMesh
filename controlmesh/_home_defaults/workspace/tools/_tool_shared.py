"""Shared helpers for cron and webhook tool scripts.

Consolidates the identical load/save/sanitize patterns that were
duplicated in ``cron_tools/_shared.py`` and ``webhook_tools/_shared.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def sanitize_name(raw: str) -> str:
    """Lowercase and normalize a name to ``[a-z0-9-]``."""
    slug = raw.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


def load_collection_or_default(path: Path, key: str) -> dict[str, Any]:
    """Load a JSON file or return ``{key: []}`` if missing/corrupt.

    *key* is the top-level list field (e.g. ``"jobs"`` or ``"hooks"``).
    """
    if not path.exists():
        return {key: []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {key: []}
    if not isinstance(data, dict):
        return {key: []}
    if not isinstance(data.get(key), list):
        return {key: []}
    return data


def load_collection_strict(path: Path, key: str) -> dict[str, Any]:
    """Load a JSON file and raise on malformed structure.

    *key* is the top-level list field (e.g. ``"jobs"`` or ``"hooks"``).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        msg = f"Corrupt {path.name} -- cannot parse"
        raise TypeError(msg)
    return data


def save_collection(path: Path, data: dict[str, Any]) -> None:
    """Persist a JSON collection with stable formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def available_ids(items: list[dict[str, Any]], id_field: str = "id") -> list[str]:
    """Return all IDs from a list of dicts for diagnostics."""
    return [str(item.get(id_field, "???")) for item in items]


def find_by_id(
    items: list[dict[str, Any]], item_id: str, id_field: str = "id"
) -> dict[str, Any] | None:
    """Find an item dict by its ID field."""
    return next((item for item in items if item.get(id_field) == item_id), None)
