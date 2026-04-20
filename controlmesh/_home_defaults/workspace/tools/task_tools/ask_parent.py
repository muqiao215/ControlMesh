#!/usr/bin/env python3
"""Forward a question to the parent agent from within a running task.

The question is delivered to the parent agent's Telegram chat. The parent
will answer by resuming your task with the response. This call returns
immediately — finish your current work and the parent will resume you.

Usage:
    python3 ask_parent.py "Your question here"

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

    get_api_url, post_json = _load_shared()
    if not args:
        print('Usage: python3 ask_parent.py "your question"', file=sys.stderr)
        sys.exit(1)

    question = args[0]
    task_id = os.environ.get("CONTROLMESH_TASK_ID", "")

    if not task_id:
        print(
            "Error: CONTROLMESH_TASK_ID not set. This tool can only be used inside a background task.",
            file=sys.stderr,
        )
        sys.exit(1)

    url = get_api_url("/tasks/ask_parent")
    result = post_json(url, {"task_id": task_id, "question": question}, timeout=10)

    if result.get("success"):
        print(result.get("answer", "Question forwarded."))
    else:
        error = result.get("error", "Unknown error")
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
