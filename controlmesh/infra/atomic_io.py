"""Atomic file write primitives.

All persistent writes in the codebase should funnel through these helpers.
They use ``tempfile.mkstemp`` + ``os.replace`` for POSIX-atomic semantics:
a partial write can never leave a corrupt target file.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_text_save(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically via temp file + rename.

    Creates parent directories if they don't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        tmp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise


def atomic_bytes_save(path: Path, data: bytes) -> None:
    """Write *data* to *path* atomically via temp file + rename.

    Creates parent directories if they don't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    tmp = Path(tmp_str)
    try:
        os.write(fd, data)
        os.close(fd)
        tmp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
