#!/usr/bin/env python3
"""Read queued parent updates from inside a running background task.

Usage:
    python3 check_task_updates.py
    python3 check_task_updates.py --peek

Environment variable CONTROLMESH_TASK_ID is automatically set by the framework
when running inside a background task.
"""

from __future__ import annotations

import os
import sys


_HELP_FLAGS = {"--help", "-h"}


def _load_shared() -> tuple[object, object]:
    tools_dir = os.path.dirname(__file__)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from _shared import get_api_url, post_json

    return get_api_url, post_json


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _HELP_FLAGS:
        print((__doc__ or "").strip())
        return

    mark_read = True
    if args:
        if args[0] == "--peek":
            mark_read = False
        else:
            print("Usage: python3 check_task_updates.py [--peek]", file=sys.stderr)
            sys.exit(1)

    get_api_url, post_json = _load_shared()
    task_id = os.environ.get("CONTROLMESH_TASK_ID", "")
    if not task_id:
        print(
            "Error: CONTROLMESH_TASK_ID not set. This tool can only be used inside a background task.",
            file=sys.stderr,
        )
        sys.exit(1)

    url = get_api_url("/tasks/pull_updates")
    result = post_json(url, {"task_id": task_id, "mark_read": mark_read}, timeout=10)
    if not result.get("success"):
        error = result.get("error", "Unknown error")
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    updates = result.get("updates", [])
    if not updates:
        print("No new parent updates.")
        return

    for item in updates:
        sequence = item.get("sequence", "?")
        message = item.get("message", "")
        sender = item.get("from", "")
        sent_at = item.get("sent_at", "")
        header = f"[{sequence}]"
        if sender:
            header += f" from {sender}"
        if sent_at:
            header += f" at {sent_at}"
        print(header)
        print(message)


if __name__ == "__main__":
    main()
