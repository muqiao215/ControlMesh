#!/usr/bin/env python3
"""Remove a sub-agent from agents.json.

The agent is stopped automatically (FileWatcher detects the removal).
The agent's workspace is preserved and can be reused.

Usage:
    python3 remove_agent.py NAME
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _agents_path() -> Path:
    """Resolve agents.json path (always in main agent home).

    Sub-agents have CONTROLMESH_HOME = ~/.controlmesh/agents/<name>/, so we navigate
    up to the main home.
    """
    import os

    home = Path(os.environ.get("CONTROLMESH_HOME", str(Path.home() / ".controlmesh")))
    direct = home / "agents.json"
    if direct.is_file():
        return direct
    main_home = home.parent.parent
    main_path = main_home / "agents.json"
    if main_path.is_file() or (main_home / "config").is_dir():
        return main_path
    return direct


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 remove_agent.py NAME", file=sys.stderr)
        sys.exit(1)

    name = sys.argv[1].strip().lower()
    if name == "main":
        print("Error: Cannot remove the main agent.", file=sys.stderr)
        sys.exit(1)

    path = _agents_path()
    if not path.is_file():
        print(f"Error: No agents.json found at {path}", file=sys.stderr)
        sys.exit(1)

    try:
        agents = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("Error: Failed to read agents.json", file=sys.stderr)
        sys.exit(1)

    remaining = [a for a in agents if a.get("name") != name]
    if len(remaining) == len(agents):
        print(f"Error: Agent '{name}' not found.", file=sys.stderr)
        sys.exit(1)

    path.write_text(json.dumps(remaining, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Agent '{name}' removed from registry.")
    print("The agent will stop automatically within a few seconds.")
    print(f"Note: The workspace at agents/{name}/ is preserved.")


if __name__ == "__main__":
    main()
