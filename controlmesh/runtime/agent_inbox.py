"""Runtime-owned inbox for agent-visible backstage events."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from controlmesh.runtime.models import AgentInboxItem
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)


class AgentInboxStore:
    """Append-only JSONL inbox per agent under the runtime-owned substrate."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def path_for(self, agent_name: str) -> Path:
        """Return the inbox path for one agent."""
        return self._paths.agent_inbox_dir / f"{agent_name}.jsonl"

    def append(self, item: AgentInboxItem) -> AgentInboxItem:
        """Append one inbox item."""
        path = self.path_for(item.to_agent)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(item.model_dump_json())
            fh.write("\n")
        return item

    def read_recent(self, agent_name: str, *, limit: int = 20) -> list[AgentInboxItem]:
        """Read recent inbox items for one agent."""
        path = self.path_for(agent_name)
        if not path.exists():
            return []
        items: list[AgentInboxItem] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                items.append(AgentInboxItem.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("AgentInboxStore: skipping unreadable line in %s", path)
        if limit <= 0:
            return items
        return items[-limit:]

    def read_recent_filtered(
        self,
        agent_name: str,
        *,
        limit: int = 20,
        plan_id: str = "",
        chat_id: object | None = None,
        topic_id: object | None = None,
    ) -> list[AgentInboxItem]:
        """Read recent inbox items narrowed to one workflow/session context."""
        items = self.read_recent(agent_name, limit=0)
        if plan_id:
            items = [item for item in items if str(item.payload.get("plan_id") or "") == plan_id]
        if chat_id not in (None, ""):
            items = [item for item in items if item.payload.get("chat_id") == chat_id]
        if topic_id is None and (plan_id or chat_id not in (None, "")):
            items = [item for item in items if item.payload.get("topic_id") in (None, "")]
        elif topic_id is not None:
            items = [item for item in items if item.payload.get("topic_id") == topic_id]
        if limit <= 0:
            return items
        return items[-limit:]
