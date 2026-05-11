"""Runtime-owned inbox for agent-visible backstage events."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from controlmesh.runtime.models import AgentInboxItem, utc_now_iso
from controlmesh.workspace.paths import ControlMeshPaths

logger = logging.getLogger(__name__)

_STATUSES = ("pending", "delivered_to_parent", "consumed", "failed")


class AgentInboxStore:
    """Directory-backed inbox per agent under the runtime-owned substrate."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def agent_dir(self, agent_name: str) -> Path:
        return self._paths.agent_inbox_dir / agent_name

    def status_dir(self, agent_name: str, status: str) -> Path:
        return self.agent_dir(agent_name) / status

    def path_for(self, agent_name: str) -> Path:
        """Compatibility path for legacy append-only jsonl readers."""
        return self._paths.agent_inbox_dir / f"{agent_name}.jsonl"

    def item_path(self, item: AgentInboxItem) -> Path:
        safe_tool_use = item.tool_use_id or item.inbox_id
        return self.status_dir(item.to_agent, item.status) / f"{safe_tool_use}.json"

    def append(self, item: AgentInboxItem) -> AgentInboxItem:
        """Append one inbox item into its state bucket."""
        item = self._normalize_item(item)
        path = self.item_path(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.model_dump_json(), encoding="utf-8")
        return item

    def read_recent(self, agent_name: str, *, limit: int = 20) -> list[AgentInboxItem]:
        """Read recent inbox items for one agent across all buckets."""
        items: list[AgentInboxItem] = []
        for status in _STATUSES:
            status_dir = self.status_dir(agent_name, status)
            if status_dir.is_dir():
                for path in sorted(status_dir.glob("*.json")):
                    item = self._read_item(path)
                    if item is not None:
                        items.append(item)
        items.extend(self._read_legacy_jsonl(agent_name))
        items.sort(key=lambda item: item.created_at)
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
        statuses: tuple[str, ...] = ("pending", "delivered_to_parent"),
    ) -> list[AgentInboxItem]:
        """Read recent inbox items narrowed to one workflow/session context."""
        items = self.read_recent(agent_name, limit=0)
        if statuses:
            items = [item for item in items if item.status in statuses]
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

    def mark_delivered(
        self,
        agent_name: str,
        *,
        tool_use_id: str,
    ) -> AgentInboxItem | None:
        item = self._find(agent_name, tool_use_id)
        if item is None:
            return None
        if item.status == "consumed":
            return item
        item.status = "delivered_to_parent"
        if not item.delivered_at:
            item.delivered_at = utc_now_iso()
        return self._rewrite(item)

    def mark_consumed(
        self,
        agent_name: str,
        *,
        tool_use_id: str,
        consumed_by: str,
        next_action: str = "",
    ) -> AgentInboxItem | None:
        item = self._find(agent_name, tool_use_id)
        if item is None:
            return None
        if item.status == "consumed":
            return item
        item.status = "consumed"
        item.consumed_at = utc_now_iso()
        item.consumed_by = consumed_by
        item.next_action = next_action
        if not item.delivered_at:
            item.delivered_at = item.consumed_at
        return self._rewrite(item)

    def mark_failed(
        self,
        agent_name: str,
        *,
        tool_use_id: str,
        reason: str,
    ) -> AgentInboxItem | None:
        item = self._find(agent_name, tool_use_id)
        if item is None:
            return None
        item.status = "failed"
        item.payload["failure_reason"] = reason
        return self._rewrite(item)

    def pending_exists(self, agent_name: str, *, tool_use_id: str) -> bool:
        item = self._find(agent_name, tool_use_id)
        return item is not None and item.status in {"pending", "delivered_to_parent"}

    def get(self, agent_name: str, *, tool_use_id: str) -> AgentInboxItem | None:
        return self._find(agent_name, tool_use_id)

    def _rewrite(self, item: AgentInboxItem) -> AgentInboxItem:
        for status in (*_STATUSES, "delivered_to_parent"):
            candidate = self.agent_dir(item.to_agent) / status / f"{item.tool_use_id or item.inbox_id}.json"
            if candidate.exists():
                candidate.unlink()
        path = self.item_path(item)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.model_dump_json(), encoding="utf-8")
        return item

    def _find(self, agent_name: str, tool_use_id: str) -> AgentInboxItem | None:
        for item in self.read_recent(agent_name, limit=0):
            if item.tool_use_id == tool_use_id:
                return item
        return None

    def _read_item(self, path: Path) -> AgentInboxItem | None:
        try:
            return AgentInboxItem.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            logger.warning("AgentInboxStore: skipping unreadable item %s", path)
            return None

    def _read_legacy_jsonl(self, agent_name: str) -> list[AgentInboxItem]:
        path = self.path_for(agent_name)
        if not path.exists():
            return []
        items: list[AgentInboxItem] = []
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = AgentInboxItem.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValueError, TypeError):
                logger.warning("AgentInboxStore: skipping unreadable legacy line in %s", path)
                continue
            items.append(self._normalize_item(item))
        return items

    def _normalize_item(self, item: AgentInboxItem) -> AgentInboxItem:
        if not item.task_id and item.from_task:
            item.task_id = item.from_task
        if not item.tool_result_ref and item.payload.get("tool_result_path"):
            item.tool_result_ref = f"task://{item.task_id or item.from_task}/TOOL_RESULT.json"
        if not item.projection:
            item.projection = item.summary
        if item.status not in {"pending", "delivered_to_parent", "consumed", "failed"}:
            item.status = "pending"
        return item
