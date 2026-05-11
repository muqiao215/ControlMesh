#!/usr/bin/env python3
"""Attach to an existing background task without re-running it.

Usage:
    python3 attach_task.py TASK_ID
"""

from __future__ import annotations

import os
import sys


_HELP_FLAGS = {"--help", "-h"}


def _load_shared() -> tuple[object, object, object]:
    tools_dir = os.path.dirname(__file__)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from _shared import detect_agent_name, get_api_url, post_json

    return get_api_url, post_json, detect_agent_name


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in _HELP_FLAGS:
        print((__doc__ or "").strip())
        return

    get_api_url, post_json, detect_agent_name = _load_shared()
    if len(args) != 1:
        print("Usage: python3 attach_task.py TASK_ID", file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    result = post_json(
        get_api_url("/tasks/attach"),
        {"task_id": task_id, "from": detect_agent_name()},
        timeout=10,
    )

    if result.get("success"):
        status = result.get("status", "unknown")
        print(f"Task '{task_id}' attached (status: {status}).")
        return

    error = result.get("error", "Unknown error")
    print(f"Error: {error}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
