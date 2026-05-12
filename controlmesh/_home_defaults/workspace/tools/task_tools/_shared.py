"""Shared helpers for task tool scripts."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


_TASKHUB_SUPPORTED_PROVIDERS = frozenset({"claude", "codex", "gemini", "opencode"})
_TASKHUB_UNSUPPORTED_PROVIDERS = frozenset({"openai", "openai_agents", "claw", "claw-code"})


def detect_agent_name() -> str:
    """Detect the agent name from script path or env var.

    Sub-agent tools live at ``~/.controlmesh/agents/<name>/workspace/tools/task_tools/``.
    Main agent tools live at ``~/.controlmesh/workspace/tools/task_tools/``.
    The path is the most reliable source — env var is used as fallback.
    """
    # Derive from script path: .../agents/<name>/workspace/tools/task_tools/
    # Avoid .resolve() — it follows symlinks which could point to _home_defaults.
    script_dir = Path(os.path.abspath(__file__)).parent
    # Walk up: task_tools -> tools -> workspace -> <agent_home>
    workspace = script_dir.parent.parent
    if workspace.name == "workspace":
        agent_home = workspace.parent
        if agent_home.parent.name == "agents":
            return agent_home.name
    # Fallback to env var
    return os.environ.get("CONTROLMESH_AGENT_NAME", "main")


def normalize_provider_name(provider: str | None) -> str:
    """Normalize external provider aliases to internal provider IDs."""
    return (provider or "").strip().lower()


def validate_taskhub_provider_name(provider: str | None) -> str:
    """Validate one explicit TaskHub provider override."""
    normalized = normalize_provider_name(provider)
    if not normalized:
        return ""
    supported = ", ".join(sorted(_TASKHUB_SUPPORTED_PROVIDERS))
    if normalized in _TASKHUB_UNSUPPORTED_PROVIDERS:
        msg = (
            f"TaskHub background provider '{normalized}' is not supported. "
            f"Supported: {supported}."
        )
        raise ValueError(msg)
    if normalized not in _TASKHUB_SUPPORTED_PROVIDERS:
        msg = f"Unknown TaskHub provider '{normalized}'. Supported: {supported}."
        raise ValueError(msg)
    return normalized


def get_api_url(path: str) -> str:
    """Build internal API URL from environment."""
    port = os.environ.get("CONTROLMESH_INTERAGENT_PORT", "8799")
    host = os.environ.get("CONTROLMESH_INTERAGENT_HOST", "127.0.0.1")
    return f"http://{host}:{port}{path}"


def post_json(url: str, body: dict[str, object], *, timeout: int = 300) -> dict[str, object]:
    """POST JSON to internal API, return parsed response."""
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.URLError as e:
        print(f"Error: Cannot reach task API at {url}: {e}", file=sys.stderr)
        print("Make sure the ControlMesh bot is running with tasks enabled.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def get_json(url: str, *, timeout: int = 10) -> dict[str, object]:
    """GET JSON from internal API, return parsed response."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())  # type: ignore[no-any-return]
    except urllib.error.URLError as e:
        print(f"Error: Cannot reach task API at {url}: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
