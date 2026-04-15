"""Shared test helpers for infra tests."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock


def make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Create a mock subprocess.CompletedProcess."""
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r
