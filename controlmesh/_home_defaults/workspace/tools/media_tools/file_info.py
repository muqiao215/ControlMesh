#!/usr/bin/env python3
"""Get metadata about a specific received media file.

Usage:
    python tools/media_tools/file_info.py --file /path/to/media_files/2025-01-15/photo_abc.jpg
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_CONTROLMESH_HOME = Path(
    os.environ.get("CONTROLMESH_HOME", str(Path.home() / ".controlmesh"))
).expanduser()

_MEDIA_DIRS = (
    _CONTROLMESH_HOME / "workspace" / "telegram_files",
    _CONTROLMESH_HOME / "workspace" / "matrix_files",
    _CONTROLMESH_HOME / "workspace" / "feishu_files",
    _CONTROLMESH_HOME / "workspace" / "api_files",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Get file metadata")
    parser.add_argument("--file", required=True, help="Path to file")
    args = parser.parse_args()

    path = Path(args.file).resolve()
    if not any(path.is_relative_to(d.resolve()) for d in _MEDIA_DIRS if d.exists()):
        print(json.dumps({"error": f"Path outside media directories: {path}"}))
        sys.exit(1)
    if not path.exists():
        print(json.dumps({"error": f"File not found: {path}"}))
        sys.exit(1)

    stat = path.stat()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    result: dict[str, object] = {
        "name": path.name,
        "path": str(path),
        "type": mime,
        "size": stat.st_size,
        "size_human": _human_size(stat.st_size),
        "modified": mtime,
    }

    caption = _find_caption(path)
    if caption is not None:
        result["caption"] = caption

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _find_caption(path: Path) -> str | None:
    """Look up caption for a file in the nearest _index.yaml."""
    try:
        import yaml
    except ImportError:
        return None

    candidate = path.parent.parent / "_index.yaml"
    if not candidate.exists():
        candidate = path.parent / "_index.yaml"
    if not candidate.exists():
        return None

    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except Exception:
        return None

    tree = data.get("tree", {})
    date_dir = path.parent.name
    files = tree.get(date_dir, [])
    for f in files:
        if f.get("name") == path.name:
            return f.get("caption")
    return None


def _human_size(size: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size //= 1024
    return f"{size:.1f} TB"


if __name__ == "__main__":
    main()
