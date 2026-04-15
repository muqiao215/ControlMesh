"""Shared platform helpers."""

from __future__ import annotations

import os
import subprocess
import sys


def is_windows() -> bool:
    """Return True when running on Windows."""
    return os.name == "nt"


# 0x08000000 on Windows prevents a console window from appearing.
# On non-Windows, 0 is the default and has no effect.
CREATION_FLAGS: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
