#!/usr/bin/env python3
"""List active and recent background tasks.

Usage:
    python3 list_tasks.py
"""

from __future__ import annotations

import os
import sys


def _load_shared() -> tuple[object, object, object]:
    tools_dir = os.path.dirname(__file__)
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from _shared import detect_agent_name, get_api_url, get_json

    return get_api_url, get_json, detect_agent_name


def main() -> None:
    get_api_url, get_json, detect_agent_name = _load_shared()
    sender = detect_agent_name()
    path = f"/tasks/list?from={sender}" if sender else "/tasks/list"
    url = get_api_url(path)
    result = get_json(url)

    tasks = result.get("tasks", [])
    if not tasks:
        print("No background tasks.")
        return

    for task in tasks:
        tid = task.get("task_id", "?")
        name = task.get("name", tid)
        status = task.get("status", "?")
        provider = task.get("provider", "?")
        model = task.get("model", "?")
        preview = task.get("prompt_preview", "")
        elapsed = task.get("elapsed_seconds", 0)

        status_icon = {"running": "⏳", "done": "✅", "failed": "❌", "cancelled": "🚫"}.get(
            status, "?"
        )
        elapsed_str = f"{elapsed:.0f}s" if elapsed else ""

        print(f"{status_icon} [{tid}] {name} | {provider}/{model} | {status} {elapsed_str}")
        if preview:
            print(f"   {preview}")


if __name__ == "__main__":
    main()
