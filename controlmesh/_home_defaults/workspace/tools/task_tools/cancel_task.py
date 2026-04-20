#!/usr/bin/env python3
"""Cancel a running background task.

Usage:
    python3 cancel_task.py TASK_ID
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
    if not args:
        print("Usage: python3 cancel_task.py TASK_ID", file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    sender = detect_agent_name()
    url = get_api_url("/tasks/cancel")
    body: dict[str, object] = {"task_id": task_id}
    if sender:
        body["from"] = sender
    result = post_json(url, body, timeout=10)

    if result.get("success"):
        print(f"Task {task_id} cancelled.")
    else:
        print(f"Could not cancel task {task_id}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
