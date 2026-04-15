#!/usr/bin/env python3
"""List received media files with optional filtering.

Reads the auto-maintained _index.yaml in the media files directory.
Searches both telegram_files/ and matrix_files/.

Usage:
    python tools/media_tools/list_files.py
    python tools/media_tools/list_files.py --type image
    python tools/media_tools/list_files.py --date 2025-01-15
    python tools/media_tools/list_files.py --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

_MEDIA_DIRS = ("telegram_files", "matrix_files")


def _get_base_dirs() -> list[Path]:
    """Resolve all media file directories relative to workspace/tools/media_tools/."""
    workspace = Path(__file__).resolve().parent.parent.parent
    return [workspace / d for d in _MEDIA_DIRS if (workspace / d).is_dir()]


def _scan_index(base_dir: Path, args: argparse.Namespace) -> list[dict]:
    """Read _index.yaml from a single media directory and return matching files."""
    index_path = base_dir / "_index.yaml"
    if not index_path.exists():
        return []
    try:
        data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return []
    tree = data.get("tree", {})
    results: list[dict] = []
    for date_str, files in sorted(tree.items(), reverse=True):
        if args.date and date_str != args.date:
            continue
        for f in files:
            if args.file_type and not f.get("type", "").startswith(args.file_type):
                continue
            results.append({
                "date": date_str,
                "name": f["name"],
                "type": f.get("type", "unknown"),
                "size": f.get("size", 0),
                "path": str(base_dir / date_str / f["name"]),
                "source": base_dir.name,
            })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="List received media files")
    parser.add_argument("--type", dest="file_type", help="Filter by MIME prefix (image, audio, video, application)")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    args = parser.parse_args()

    if yaml is None:
        print(json.dumps({"error": "pyyaml not installed (pip install pyyaml)"}))
        sys.exit(1)

    base_dirs = _get_base_dirs()
    if not base_dirs:
        print(json.dumps({"files": [], "total": 0, "note": "No media directories found. No files received yet."}))
        return

    all_results: list[dict] = []
    for base_dir in base_dirs:
        all_results.extend(_scan_index(base_dir, args))

    # Sort by date descending, limit
    all_results.sort(key=lambda r: r["date"], reverse=True)
    all_results = all_results[: args.limit]

    print(json.dumps({
        "files": all_results,
        "total": len(all_results),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
