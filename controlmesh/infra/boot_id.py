"""Cross-platform boot ID detection.

Returns a unique identifier for the current system boot session.
Used by startup state tracking to distinguish restarts from reboots.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_LINUX_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def get_boot_id() -> str:
    """Return a unique identifier for the current system boot.

    - Linux/Docker: ``/proc/sys/kernel/random/boot_id``
    - macOS: ``sysctl -n kern.bootsessionuuid``
    - Windows: boot time derived from uptime counter

    Returns empty string on failure or unsupported platform.
    """
    platform = sys.platform
    if platform == "linux":
        return _linux_boot_id()
    if platform == "darwin":
        return _darwin_boot_id()
    if platform == "win32":
        return _windows_boot_id()
    return ""


def _linux_boot_id() -> str:
    """Read boot ID from /proc on Linux and Docker."""
    try:
        return _LINUX_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        logger.debug("Cannot read %s", _LINUX_BOOT_ID_PATH)
        return ""


def _darwin_boot_id() -> str:
    """Read boot session UUID via sysctl on macOS."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "kern.bootsessionuuid"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except OSError:
        logger.debug("sysctl command failed")
    return ""


def _windows_boot_id() -> str:
    """Derive boot identifier from system uptime on Windows.

    Uses ``GetTickCount64`` to get milliseconds since boot, then computes
    an approximate boot timestamp.  The resolution is coarse (minutes) but
    sufficient to distinguish reboots from service restarts.
    """
    try:
        import ctypes
        import time

        uptime_ms = ctypes.windll.kernel32.GetTickCount64()  # type: ignore[attr-defined]
        # Round to nearest minute to avoid jitter
        uptime_minutes = int(uptime_ms / 60_000)
        boot_epoch_min = int(time.time() / 60) - uptime_minutes
    except Exception:
        logger.debug("Windows boot ID detection failed")
        return ""
    else:
        return f"win-{boot_epoch_min}"
