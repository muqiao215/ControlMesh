"""Adapters from existing Python read models to protocol boundary models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import json
from typing import Any

from controlmesh.history.index import IndexedRuntimeEvent, IndexedTaskCatalogRow, IndexedTeamEntity
from controlmesh.files.tags import guess_mime
from controlmesh.protocol.generated import Artifact, ProviderCapability, Task, TaskEvent, Topology

_TASK_STATES = frozenset(
    {
        "running",
        "done",
        "failed",
        "cancelled",
        "waiting",
        "detached",
        "recovering",
        "stale",
        "timeout",
    }
)


def task_catalog_row_to_protocol(row: IndexedTaskCatalogRow) -> Task:
    """Convert a derived task catalog row into the public task protocol shape."""
    return Task(
        schema_version="controlmesh.task.v1",
        task_id=row.task_id,
        source_kind=row.source_kind,
        chat_id=row.chat_id,
        thread_id=row.thread_id,
        parent_agent=row.parent_agent,
        name=row.name,
        prompt_preview=row.prompt_preview,
        provider=row.provider,
        model=row.model,
        status=row.status,
        session_id=row.session_id,
        created_at=row.created_at,
        completed_at=row.completed_at,
        elapsed_seconds=row.elapsed_seconds,
        result_preview=row.result_preview,
        last_question=row.last_question,
    )


def provider_info_to_protocol(raw: Mapping[str, Any]) -> ProviderCapability:
    """Convert provider status/info dictionaries into protocol capability objects."""
    name = str(raw.get("name") or raw.get("provider") or "")
    available = bool(raw.get("available", True))
    health = str(raw.get("health") or ("ok" if available else "unavailable"))
    if health not in {"ok", "degraded", "unavailable"}:
        health = "degraded" if available else "unavailable"
    return ProviderCapability(
        schema_version="controlmesh.provider_capability.v1",
        name=name,
        available=available,
        version=_optional_str(raw.get("version")),
        last_checked_at=raw.get("last_checked_at"),
        health=health,
        detail=_optional_str(raw.get("detail") or raw.get("status")),
        capabilities=dict(raw.get("capabilities") or {}),
    )


def runtime_event_to_task_event(row: IndexedRuntimeEvent) -> TaskEvent | None:
    """Convert an indexed runtime event with a task payload into a task event."""
    payload = _decode_payload(row.payload_json)
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return None

    status = payload.get("status")
    return TaskEvent(
        schema_version="controlmesh.task_event.v1",
        event_id=row.event_id,
        task_id=task_id,
        event_type=row.event_type,
        status=status if isinstance(status, str) and status in _TASK_STATES else None,
        created_at=row.created_at,
        transport=row.transport,
        chat_id=row.chat_id,
        topic_id=row.topic_id,
        payload=payload,
    )


def task_artifact_to_protocol(task_id: str, task_folder: Path, path: Path) -> Artifact | None:
    """Convert one Python-resolved task artifact path into public metadata."""
    try:
        resolved_folder = task_folder.resolve()
        resolved_path = path.resolve()
        if not resolved_path.is_file() or not resolved_path.is_relative_to(resolved_folder):
            return None
        relative_path = resolved_path.relative_to(resolved_folder).as_posix()
        stat = resolved_path.stat()
        mime = guess_mime(resolved_path)
    except OSError:
        return None
    return Artifact(
        schema_version="controlmesh.artifact.v1",
        task_id=task_id,
        relative_path=relative_path,
        name=resolved_path.name,
        mime=mime,
        size=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
    )


def team_entities_to_topology(team_name: str, rows: list[IndexedTeamEntity]) -> Topology:
    """Project authoritative indexed team entities into a read-only graph."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, str]] = {}
    leader_id = ""
    for row in rows:
        payload = _decode_payload(row.payload_json)
        if row.entity_kind == "manifest":
            leader = payload.get("leader")
            if isinstance(leader, dict) and isinstance(leader.get("agent_name"), str):
                leader_id = f"agent:{leader['agent_name']}"
                nodes[leader_id] = {
                    "id": leader_id,
                    "kind": "agent",
                    "label": leader["agent_name"],
                    "role": "leader",
                }
            workers = payload.get("workers")
            if isinstance(workers, list):
                for worker in workers:
                    if not isinstance(worker, dict) or not isinstance(worker.get("name"), str):
                        continue
                    node_id = f"agent:{worker['name']}"
                    nodes[node_id] = {
                        "id": node_id,
                        "kind": "agent",
                        "label": worker["name"],
                        "role": worker.get("role"),
                        "provider": worker.get("provider"),
                    }
                    if leader_id:
                        edges[(leader_id, node_id, "supervises")] = {
                            "source": leader_id,
                            "target": node_id,
                            "kind": "supervises",
                        }
        elif row.entity_kind == "worker_runtime" and row.worker:
            node_id = f"agent:{row.worker}"
            nodes.setdefault(node_id, {"id": node_id, "kind": "agent", "label": row.worker})
            nodes[node_id]["status"] = row.status
        elif row.entity_kind == "task":
            node_id = f"task:{row.entity_id}"
            nodes[node_id] = {
                "id": node_id,
                "kind": "task",
                "label": payload.get("subject") or row.entity_id,
                "status": row.status,
                "owner": row.owner,
            }
            if row.owner:
                owner_id = f"agent:{row.owner}"
                nodes.setdefault(owner_id, {"id": owner_id, "kind": "agent", "label": row.owner})
                edges[(owner_id, node_id, "owns")] = {
                    "source": owner_id,
                    "target": node_id,
                    "kind": "owns",
                }
            blocked_by = payload.get("blocked_by")
            if isinstance(blocked_by, list):
                for blocker in blocked_by:
                    if isinstance(blocker, str):
                        source = f"task:{blocker}"
                        edges[(source, node_id, "blocks")] = {
                            "source": source,
                            "target": node_id,
                            "kind": "blocks",
                        }
    return Topology(
        schema_version="controlmesh.topology.v1",
        topology_id=team_name,
        name=team_name,
        nodes=sorted(nodes.values(), key=lambda node: str(node["id"])),
        edges=sorted(edges.values(), key=lambda edge: (edge["source"], edge["target"], edge["kind"])),
    )


def _decode_payload(raw_payload: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
