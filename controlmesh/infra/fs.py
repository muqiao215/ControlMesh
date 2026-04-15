"""Filesystem utilities."""

from __future__ import annotations

import logging
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_RMTREE_RETRIES = 3
_RMTREE_RETRY_DELAY = 1.0


def robust_rmtree(path: Path) -> None:
    """Remove a directory tree, handling locked files on Windows.

    On Windows, processes can hold file locks (e.g. log files). This helper:
    1. Clears read-only flags on permission errors
    2. Retries the full rmtree up to ``_RMTREE_RETRIES`` times with a delay
    """

    def _on_error(
        func: Callable[..., object],
        fpath: str,
        _exc_info: object,
    ) -> None:
        """Handle permission errors by clearing read-only and retrying."""
        try:
            Path(fpath).chmod(stat.S_IWRITE | stat.S_IREAD)
            func(fpath)
        except OSError:
            pass

    last_exc: Exception | None = None
    for attempt in range(_RMTREE_RETRIES):
        try:
            shutil.rmtree(path, onerror=_on_error)
        except OSError as exc:
            last_exc = exc
        else:
            return

        if attempt < _RMTREE_RETRIES - 1:
            logger.debug(
                "rmtree attempt %d failed for %s, retrying in %.0fs",
                attempt + 1,
                path,
                _RMTREE_RETRY_DELAY,
            )
            time.sleep(_RMTREE_RETRY_DELAY)

    if last_exc:
        logger.warning("Could not fully remove %s: %s", path, last_exc)
