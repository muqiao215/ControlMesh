"""File storage helpers: sanitization, destination preparation, and indexing."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_UNSAFE_CHARS_RE = re.compile(r'[/\\<>:"|?*\x00]')
_INDEX_SKIP = frozenset({"_index.yaml", "CLAUDE.md", "AGENTS.md"})


def sanitize_filename(name: str) -> str:
    r"""Remove path separators, null bytes, and OS-illegal characters.

    Strips characters forbidden on Windows (``< > : " | ? *``),
    path separators (``/`` ``\\``), and null bytes on all platforms.
    """
    name = _UNSAFE_CHARS_RE.sub("_", name)
    while "__" in name:
        name = name.replace("__", "_")
    return name.strip("_. ")[:120] or "file"


def prepare_destination(base_dir: Path, file_name: str) -> Path:
    """Create date directory and return a non-colliding destination path."""
    day_dir = base_dir / datetime.now(tz=UTC).strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    dest = day_dir / file_name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 1
        while dest.exists():
            dest = day_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    return dest


def update_index(base_dir: Path) -> None:
    """Rebuild ``_index.yaml`` by scanning all date subdirectories.

    Works for any transport's file directory (Telegram, Matrix, API).
    """
    import yaml

    from controlmesh.files.tags import guess_mime

    tree: dict[str, list[dict[str, object]]] = {}
    total = 0

    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir() or len(entry.name) != 10 or entry.name[4] != "-":
            continue
        files: list[dict[str, object]] = []
        for f in sorted(entry.iterdir()):
            if not f.is_file() or f.name in _INDEX_SKIP:
                continue
            stat = f.stat()
            mime = guess_mime(f)
            files.append(
                {
                    "name": f.name,
                    "type": mime,
                    "size": stat.st_size,
                    "received": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                }
            )
            total += 1
        if files:
            tree[entry.name] = files

    index = {
        "last_updated": datetime.now(tz=UTC).isoformat(),
        "total_files": total,
        "tree": tree,
    }
    index_path = base_dir / "_index.yaml"
    index_path.write_text(
        yaml.safe_dump(index, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.debug("Index updated: %d files across %d days", total, len(tree))
