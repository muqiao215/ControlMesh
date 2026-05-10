"""Plan-level release approval gate for publish side effects."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controlmesh.planning_files import plan_dir_for


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def approval_key(*, repo: str, version: str) -> str:
    repo_name = Path(repo.rstrip("/")).name or "repo"
    return f"release_publish:{repo_name}:{version}"


def side_effect_key(*, repo: str, version: str) -> str:
    """Stable idempotency key for one release publish side effect."""
    return approval_key(repo=repo, version=version)


def gate_state_path(root: str | Path, plan_id: str) -> Path:
    return plan_dir_for(root, plan_id) / "PUBLISH_GATE.json"


def executed_artifact_path(root: str | Path, plan_id: str) -> Path:
    return plan_dir_for(root, plan_id) / "publish" / "EXECUTED.json"


def load_gate_state(root: str | Path, plan_id: str) -> dict[str, Any]:
    path = gate_state_path(root, plan_id)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_gate_state(root: str | Path, plan_id: str, payload: dict[str, Any]) -> Path:
    path = gate_state_path(root, plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_publish_gate(
    root: str | Path,
    *,
    plan_id: str,
    repo: str,
    version: str,
    commit: str,
    tag: str,
    commands: list[str],
    requested_by_task: str,
) -> dict[str, Any]:
    state = load_gate_state(root, plan_id)
    if state:
        return state
    payload = {
        "approval_key": approval_key(repo=repo, version=version),
        "side_effect_key": side_effect_key(repo=repo, version=version),
        "plan_id": plan_id,
        "repo": repo,
        "version": version,
        "commit": commit,
        "tag": tag,
        "commands": commands,
        "status": "pending_approval",
        "requested_by_task": requested_by_task,
        "requested_at": utc_now_iso(),
        "approved_at": "",
        "approved_by": "",
        "approved_answer": "",
        "executor_task_id": "",
        "executed_at": "",
    }
    save_gate_state(root, plan_id, payload)
    return payload


def mark_gate_approved(
    root: str | Path,
    *,
    plan_id: str,
    approved_by: str,
    approved_answer: str,
) -> dict[str, Any]:
    state = load_gate_state(root, plan_id)
    if not state:
        return {}
    state["status"] = "approved_once"
    state["approved_by"] = approved_by
    state["approved_answer"] = approved_answer
    state["approved_at"] = utc_now_iso()
    save_gate_state(root, plan_id, state)
    return state


def claim_executor(root: str | Path, *, plan_id: str, task_id: str) -> tuple[bool, dict[str, Any]]:
    state = load_gate_state(root, plan_id)
    if not state:
        return False, {}
    existing = str(state.get("executor_task_id") or "")
    if existing and existing != task_id:
        return False, state
    state["executor_task_id"] = task_id
    if state.get("status") == "approved_once":
        state["status"] = "executing"
    save_gate_state(root, plan_id, state)
    return True, state


def mark_executed(
    root: str | Path,
    *,
    plan_id: str,
    payload: dict[str, Any],
) -> Path:
    path = executed_artifact_path(root, plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = load_gate_state(root, plan_id)
    if state:
        state["status"] = "executed"
        state["executed_at"] = utc_now_iso()
        save_gate_state(root, plan_id, state)
    return path
