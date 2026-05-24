"""File-backed inbox for terminal-visible background updates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TerminalInboxItem(BaseModel):
    """One background update visible through ``/inbox``."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: Literal["task_update", "agent_message", "cron_result", "memory_notice"]
    title: str
    body: str
    task_id: str | None = None
    agent: str | None = None
    read: bool = False


class TerminalInbox:
    """Small JSONL inbox used by the enhanced terminal prompt and ``/inbox``."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, item: TerminalInboxItem) -> None:
        """Append an inbox item."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(item.model_dump_json() + "\n")

    def list_unread(self) -> list[TerminalInboxItem]:
        """Return unread items."""
        return [item for item in self.list_all(limit=1000) if not item.read]

    def list_all(self, limit: int = 20) -> list[TerminalInboxItem]:
        """Return recent inbox items."""
        items = self._read_all()
        return list(reversed(items[-limit:]))

    def mark_read(self, item_id: str) -> None:
        """Mark one item read."""
        items = self._read_all()
        changed = False
        for item in items:
            if item.id == item_id:
                item.read = True
                changed = True
        if changed:
            self._write_all(items)

    def mark_all_read(self) -> int:
        """Mark every item read and return the number changed."""
        items = self._read_all()
        changed = 0
        for item in items:
            if not item.read:
                item.read = True
                changed += 1
        if changed:
            self._write_all(items)
        return changed

    def _read_all(self) -> list[TerminalInboxItem]:
        if not self.path.exists():
            return []
        items: list[TerminalInboxItem] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                items.append(TerminalInboxItem.model_validate_json(line))
            except (ValueError, json.JSONDecodeError):
                continue
        return items

    def _write_all(self, items: list[TerminalInboxItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(item.model_dump_json() + "\n" for item in items)
        self.path.write_text(payload, encoding="utf-8")
