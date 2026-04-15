"""Startup state tracking: classify startup as first start, restart, or reboot.

Compares the current boot ID (from ``boot_id.get_boot_id()``) with a
persisted state file to determine what kind of startup this is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from controlmesh.infra.boot_id import get_boot_id
from controlmesh.infra.json_store import atomic_json_save, load_json

logger = logging.getLogger(__name__)


class StartupKind(Enum):
    """Classification of the current startup."""

    FIRST_START = "first_start"
    SERVICE_RESTART = "service_restart"
    SYSTEM_REBOOT = "system_reboot"


@dataclass(slots=True)
class StartupInfo:
    """Result of startup classification."""

    kind: StartupKind
    boot_id: str
    started_at: str


def detect_startup_kind(state_path: Path) -> StartupInfo:
    """Compare current boot ID with stored state to classify startup.

    - No file or corrupt file → FIRST_START
    - Same boot ID → SERVICE_RESTART
    - Different boot ID → SYSTEM_REBOOT
    - Empty stored boot ID → FIRST_START (never compared before)
    - Empty current boot ID → SERVICE_RESTART (detection failed, safe default)
    """
    current_boot_id = get_boot_id()
    now_iso = datetime.now(UTC).isoformat()

    stored = load_json(state_path)
    if stored is None:
        return StartupInfo(
            kind=StartupKind.FIRST_START, boot_id=current_boot_id, started_at=now_iso
        )

    stored_boot_id = str(stored.get("boot_id", "")).strip()
    if not stored_boot_id:
        return StartupInfo(
            kind=StartupKind.FIRST_START, boot_id=current_boot_id, started_at=now_iso
        )

    if not current_boot_id:
        # Boot ID detection failed — can't distinguish restart from reboot.
        # Default to restart (less alarming, more common).
        return StartupInfo(
            kind=StartupKind.SERVICE_RESTART,
            boot_id=current_boot_id,
            started_at=now_iso,
        )

    if current_boot_id == stored_boot_id:
        return StartupInfo(
            kind=StartupKind.SERVICE_RESTART,
            boot_id=current_boot_id,
            started_at=now_iso,
        )

    return StartupInfo(kind=StartupKind.SYSTEM_REBOOT, boot_id=current_boot_id, started_at=now_iso)


def save_startup_state(state_path: Path, info: StartupInfo) -> None:
    """Persist startup state using atomic JSON save."""
    atomic_json_save(
        state_path,
        {
            "boot_id": info.boot_id,
            "started_at": info.started_at,
        },
    )
