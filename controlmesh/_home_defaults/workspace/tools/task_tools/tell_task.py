#!/usr/bin/env python3
"""Queue a temporary parent update for a running background task.

Use this when a task is still running and you need to send a new requirement
or command without cancelling/restarting it.

Usage:
    python3 tell_task.py TASK_ID "your new requirement"
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
    if len(args) < 2:
        print('Usage: python3 tell_task.py TASK_ID "new requirement"', file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    message = args[1]
    sender = detect_agent_name()
    url = get_api_url("/tasks/tell")
    body: dict[str, object] = {"task_id": task_id, "message": message}
    if sender:
        body["from"] = sender
    result = post_json(url, body, timeout=10)

    if result.get("success"):
        sequence = result.get("sequence", "?")
        print(f"Queued parent update {sequence} for task {task_id}.")
    else:
        error = result.get("error", "Unknown error")
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
