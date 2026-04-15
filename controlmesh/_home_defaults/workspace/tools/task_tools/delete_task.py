#!/usr/bin/env python3
"""Permanently delete a finished background task (entry + folder).

Usage:
    python3 delete_task.py TASK_ID
"""

from __future__ import annotations

import os
import sys


def _load_shared() -> tuple[object, object, object]:
    tools_dir = os.path.dirname(__file__)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from _shared import detect_agent_name, get_api_url, post_json

    return get_api_url, post_json, detect_agent_name


def main() -> None:
    get_api_url, post_json, detect_agent_name = _load_shared()
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 delete_task.py TASK_ID", file=sys.stderr)
        sys.exit(1)

    task_id = args[0]
    sender = detect_agent_name()
    url = get_api_url("/tasks/delete")
    body: dict[str, object] = {"task_id": task_id}
    if sender:
        body["from"] = sender
    result = post_json(url, body, timeout=10)

    if result.get("success"):
        print(f"Task {task_id} deleted.")
    else:
        error = result.get("error", "Unknown error")
        print(f"Could not delete task {task_id}: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
