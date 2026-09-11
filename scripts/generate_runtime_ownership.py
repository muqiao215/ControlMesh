#!/usr/bin/env python3
"""Capture actual Python ownership and serializers without opening operator state."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "plans/runtime-convergence/python-ownership.json"
FIXTURE = ROOT / "tests/golden/fixtures/tasks/legacy-registry.json"
AREAS = {
    "tasks": ["controlmesh/tasks"],
    "execution_and_providers": ["controlmesh/cli", "controlmesh/execution_grants.py"],
    "events_inbox_and_host_jobs": ["controlmesh/runtime"],
    "orchestration": ["controlmesh/multiagent", "controlmesh/team", "controlmesh/orchestrator"],
    "review_recovery_promotion": ["controlmesh_runtime"],
    "transport_and_ingress": ["controlmesh/messenger", "controlmesh/bus"],
    "workspace_and_memory": ["controlmesh/workspace", "controlmesh/memory"],
    "schedules": ["controlmesh/cron"],
    "session_identity": ["controlmesh/session"],
}
MODELS = [
    "controlmesh/tasks/models.py", "controlmesh/tasks/native_sessions.py",
    "controlmesh/bus/envelope.py", "controlmesh/execution_grants.py",
    "controlmesh/runtime/models.py", "controlmesh_runtime/task_packet.py",
    "controlmesh_runtime/worker_state.py", "controlmesh_runtime/records.py",
    "controlmesh_runtime/events.py", "controlmesh_runtime/contracts.py",
    "controlmesh_runtime/execution_payloads.py", "controlmesh_runtime/promotion_receipt.py",
    "controlmesh_runtime/summary/contracts.py", "controlmesh_runtime/recovery/contracts.py",
]


def render(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def generate() -> tuple[dict, dict]:
    # Importing a data model is safe; TaskRegistry construction is deliberately absent.
    from controlmesh.tasks.models import TaskEntry

    areas = {}
    for area, roots in AREAS.items():
        files = set()
        for relative in roots:
            path = ROOT / relative
            if not path.exists():
                raise ValueError(f"missing ownership root: {relative}")
            files.update([path] if path.is_file() else path.rglob("*.py"))
        areas[area] = {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files) if "__pycache__" not in path.parts
        }
    assigned = {path for files in areas.values() for path in files}
    areas["other_python_owners"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((ROOT / "controlmesh").rglob("*.py"))
        if str(path.relative_to(ROOT)) not in assigned and "__pycache__" not in path.parts
    }
    models = {}
    for relative in MODELS:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        models[relative] = {
            item.name: [node.target.id for node in item.body
                        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)]
            for item in tree.body if isinstance(item, ast.ClassDef)
        }
    row = TaskEntry(
        task_id="fixture-task", chat_id="synthetic-chat", parent_agent="main", name="fixture",
        prompt_preview="synthetic context", status="cancelled", created_at=1.0, thread_id="topic",
    ).to_dict()
    task_fields = models["controlmesh/tasks/models.py"]["TaskEntry"]
    fixture = {"tasks": [row], "future_metadata": {"preserve": True}}
    return {
        "schema_version": 1,
        "meaning": "source inventory, not proof that listed owners are ported or retired",
        "areas": areas,
        "model_fields": models,
        "task_entry_serialized_fields": sorted(row),
        "task_entry_nonserialized_fields": sorted(set(task_fields) - set(row)),
        "task_entry_conditional_fields": ["thread_id"],
    }, fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    ownership, fixture = generate()
    for path, content in [(OUTPUT, render(ownership)), (FIXTURE, render(fixture))]:
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                print(f"runtime ownership drift: {path.relative_to(ROOT)}")
                return 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print(f"runtime ownership current: {sum(len(x) for x in ownership['areas'].values())} modules; "
          f"{len(ownership['task_entry_serialized_fields'])} persisted TaskEntry fields")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
