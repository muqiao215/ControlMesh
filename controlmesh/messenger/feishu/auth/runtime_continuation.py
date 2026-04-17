"""File-backed Feishu auth continuation metadata."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FeishuAuthContinuationEntry:
    operation_id: str
    chat_id: str
    sender_open_id: str
    retry_text: str
    thread_id: str | None = None
    trigger_message_id: str | None = None


class FeishuAuthRuntimeStore:
    """File-backed ControlMesh runtime metadata for auth continuation callbacks."""

    def __init__(self, controlmesh_home: str | Path) -> None:
        self.path = (
            Path(controlmesh_home).expanduser()
            / "feishu_store"
            / "auth"
            / "orchestration_runtime.json"
        )

    def load(self, operation_id: str) -> FeishuAuthContinuationEntry | None:
        item = self._read_all().get(operation_id)
        if not item:
            return None
        return FeishuAuthContinuationEntry(
            operation_id=str(item["operation_id"]),
            chat_id=str(item["chat_id"]),
            sender_open_id=str(item["sender_open_id"]),
            retry_text=str(item["retry_text"]),
            thread_id=item.get("thread_id"),
            trigger_message_id=item.get("trigger_message_id"),
        )

    def save(self, entry: FeishuAuthContinuationEntry) -> None:
        items = self._read_all()
        items[entry.operation_id] = asdict(entry)
        self._write_all(items)

    def remove(self, operation_id: str) -> bool:
        items = self._read_all()
        removed = items.pop(operation_id, None)
        if removed is None:
            return False
        self._write_all(items)
        return True

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(payload, dict):
            return {}
        items = payload.get("continuations", payload)
        if not isinstance(items, dict):
            return {}
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}

    def _write_all(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps({"continuations": items}, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)
