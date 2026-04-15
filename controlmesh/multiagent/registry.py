"""Agent registry: loads and manages agents.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from controlmesh.multiagent.models import SubAgentConfig

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Read/write access to the sub-agent registry file (agents.json)."""

    def __init__(self, agents_path: Path) -> None:
        self._path = agents_path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[SubAgentConfig]:
        """Load sub-agent definitions. Returns empty list if file is missing."""
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to read agents.json at %s", self._path)
            return []

        if not isinstance(raw, list):
            logger.warning("agents.json must be a JSON array, got %s", type(raw).__name__)
            return []

        agents: list[SubAgentConfig] = []
        for idx, entry in enumerate(raw):
            try:
                agents.append(SubAgentConfig(**entry))
            except Exception:
                logger.exception("Invalid sub-agent definition at index %d", idx)
        return agents

    def save(self, agents: list[SubAgentConfig]) -> None:
        """Write sub-agent definitions to agents.json."""
        from controlmesh.infra.json_store import atomic_json_save

        data = [a.model_dump(exclude_none=True) for a in agents]
        atomic_json_save(self._path, data)
        logger.info("Saved %d sub-agents to %s", len(agents), self._path)

    def add(self, agent: SubAgentConfig) -> None:
        """Add a sub-agent (name must be unique)."""
        agents = self.load()
        if any(a.name == agent.name for a in agents):
            msg = f"Sub-agent '{agent.name}' already exists"
            raise ValueError(msg)
        agents.append(agent)
        self.save(agents)

    def remove(self, name: str) -> SubAgentConfig | None:
        """Remove a sub-agent by name. Returns the removed config or None."""
        agents = self.load()
        removed = None
        remaining: list[SubAgentConfig] = []
        for a in agents:
            if a.name == name:
                removed = a
            else:
                remaining.append(a)
        if removed:
            self.save(remaining)
        return removed


def update_agent_fields(agents_path: Path, agent_name: str, **fields: object) -> None:
    """Update specific fields of an agent entry in agents.json.

    Reads the raw JSON, patches the matching entry, and writes back.
    A value of ``None`` removes the key from the entry.
    No-op if the file is missing or the agent is not found.
    """
    if not agents_path.is_file():
        return
    try:
        raw = json.loads(agents_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Cannot read agents.json for update: %s", agents_path)
        return
    if not isinstance(raw, list):
        return

    for entry in raw:
        if entry.get("name") == agent_name:
            for key, value in fields.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            break
    else:
        return

    from controlmesh.infra.json_store import atomic_json_save

    atomic_json_save(agents_path, raw)
    logger.info("Updated agent '%s' in agents.json: %s", agent_name, list(fields))
