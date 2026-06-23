#!/usr/bin/env python3
"""Resume a completed background task with a follow-up prompt.

The follow-up runs in the SAME CLI session as the original task, so the
task agent already has full context from its previous work.  The task
resumes on the original provider/model regardless of the current chat
provider.

Usage:
    python3 resume_task.py [options] TASK_ID "your follow-up prompt"

Options:
    --auto-micro-commit
                      Enable intent-complete micro-commit for this resumed task
    --no-auto-micro-commit
                      Disable inherited auto micro-commit policy for this resumed task
    --auto-micro-commit-push
                      Enable micro-commit and git push for this resumed task
    --no-auto-micro-commit-push
                      Disable inherited push policy for this resumed task
    --micro-commit-message MSG
                      Commit message for the automatic micro-commit
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
    auto_micro_commit: bool | None = None
    auto_micro_commit_push: bool | None = None
    micro_commit_message = ""
    while args:
        if args[0] == "--auto-micro-commit":
            auto_micro_commit = True
            args = args[1:]
        elif args[0] == "--no-auto-micro-commit":
            auto_micro_commit = False
            args = args[1:]
        elif args[0] == "--auto-micro-commit-push":
            auto_micro_commit = True
            auto_micro_commit_push = True
            args = args[1:]
        elif args[0] == "--no-auto-micro-commit-push":
            auto_micro_commit_push = False
            args = args[1:]
        elif args[0] == "--micro-commit-message" and len(args) >= 2:
            micro_commit_message = args[1]
            args = args[2:]
        else:
            break

    if len(args) < 2:
        print(
            'Usage: python3 resume_task.py [options] TASK_ID "follow-up prompt"',
            file=sys.stderr,
        )
        sys.exit(1)

    task_id = args[0]
    prompt = args[1]
    sender = detect_agent_name()

    url = get_api_url("/tasks/resume")
    body: dict[str, object] = {"task_id": task_id, "prompt": prompt, "from": sender}
    if auto_micro_commit is not None:
        body["auto_micro_commit"] = auto_micro_commit
    if auto_micro_commit_push is not None:
        body["auto_micro_commit_push"] = auto_micro_commit_push
    if micro_commit_message:
        body["micro_commit_message"] = micro_commit_message
    result = post_json(
        url,
        body,
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
