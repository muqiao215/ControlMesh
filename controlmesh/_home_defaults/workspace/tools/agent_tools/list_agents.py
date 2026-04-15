#!/usr/bin/env python3
"""List all registered sub-agents and their configuration.

Usage:
    python3 list_agents.py
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
    path = _agents_path()
    if not path.is_file():
        print("No agents.json found. No sub-agents configured.")
        return

    try:
        agents = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        print("Error: Failed to read agents.json", file=sys.stderr)
        sys.exit(1)

    if not agents:
        print("No sub-agents configured.")
        return

    print(f"Registered sub-agents ({len(agents)}):\n")
    for agent in agents:
        name = agent.get("name", "?")
        token = agent.get("telegram_token", "?")
        users = agent.get("allowed_user_ids", [])
        provider = agent.get("provider", "(inherited)")
        model = agent.get("model", "(inherited)")

        # Check if workspace exists
        home = Path(_agents_path().parent / "agents" / name)
        workspace_status = "exists" if home.is_dir() else "not created"

        print(f"  {name}")
        print(f"    Token:     {token[:8]}...")
        print(f"    Users:     {users}")
        print(f"    Provider:  {provider}")
        print(f"    Model:     {model}")
        print(f"    Workspace: {workspace_status}")
        print()


if __name__ == "__main__":
    main()
