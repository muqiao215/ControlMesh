#!/usr/bin/env python3
"""Resume a completed background task with a follow-up prompt.

The follow-up runs in the SAME CLI session as the original task, so the
task agent already has full context from its previous work.  The task
resumes on the original provider/model regardless of the current chat
provider.

Usage:
    python3 resume_task.py TASK_ID "your follow-up prompt"
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
    if len(args) < 2:
        print(
            'Usage: python3 resume_task.py TASK_ID "follow-up prompt"',
            file=sys.stderr,
        )
        sys.exit(1)

    task_id = args[0]
    prompt = args[1]
    sender = detect_agent_name()

    url = get_api_url("/tasks/resume")
    result = post_json(
        url,
        {"task_id": task_id, "prompt": prompt, "from": sender},
        timeout=10,
    )

    if result.get("success"):
        print(
            f"Task '{task_id}' resumed. The result will be delivered back to your chat when ready."
        )
    else:
        error = result.get("error", "Unknown error")
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
