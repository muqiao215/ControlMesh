"""File artifacts for foreground-controlled phased plans."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanPhase:
    """One controller-approved unit in a file-backed plan."""

    id: str
    title: str
    workunit_kind: str
    route: str = "auto"
    allowed_edit: bool = False
    status: str = "pending"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "workunit_kind": self.workunit_kind,
            "route": self.route,
            "allowed_edit": self.allowed_edit,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class PlanFilesManifest:
    """PHASES.json-compatible manifest for phased TaskHub execution."""

    workflow: str = "planning_with_files"
    status: str = "planning"
    current_phase: int = 0
    phases: tuple[PlanPhase, ...] = field(default_factory=tuple)
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow": self.workflow,
            "status": self.status,
            "current_phase": self.current_phase,
            "phases": [phase.to_dict() for phase in self.phases],
        }


def create_plan_files(
    root: str | Path,
    *,
    plan_id: str,
    plan_markdown: str,
    phases: tuple[PlanPhase, ...],
    status: str = "planning",
    current_phase: int = 0,
) -> Path:
    """Create `.controlmesh/plans/<plan_id>` artifacts for a phased workflow."""
    plan_dir = plan_dir_for(root, plan_id)
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "PLAN.md").write_text(plan_markdown.rstrip() + "\n", encoding="utf-8")
    manifest = PlanFilesManifest(status=status, phases=phases, current_phase=current_phase)
    _write_json(plan_dir / "PHASES.json", manifest.to_dict())
    _write_json(
        plan_dir / "STATE.json",
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": status,
            "current_phase": current_phase,
        },
    )
    for phase in phases:
        phase_dir = plan_dir / phase.id
        phase_dir.mkdir(exist_ok=True)
        _write_phase_placeholders(phase_dir)
    return plan_dir


def plans_root(root: str | Path) -> Path:
    """Resolve the canonical plans root from either home or a generic root."""
    base = Path(root).expanduser()
    if base.name == "plans":
        return base
    if base.name == ".controlmesh":
        return base / "plans"
    return base / ".controlmesh" / "plans"


def plan_dir_for(root: str | Path, plan_id: str) -> Path:
    """Return the plan directory for one plan id."""
    return plans_root(root) / plan_id


def phase_dir_for(root: str | Path, plan_id: str, phase_id: str) -> Path:
    """Return the artifact directory for one phase."""
    return plan_dir_for(root, plan_id) / phase_id


def ensure_phase_artifacts(
    root: str | Path,
    *,
    plan_id: str,
    phase_id: str,
) -> Path:
    """Ensure the phase artifact directory and placeholder files exist."""
    phase_dir = phase_dir_for(root, plan_id, phase_id)
    phase_dir.mkdir(parents=True, exist_ok=True)
    _write_phase_placeholders(phase_dir)
    return phase_dir


def update_phase_state(
    root: str | Path,
    *,
    plan_id: str,
    phase_id: str,
    phase_title: str,
    workunit_kind: str,
    route: str = "auto",
    allowed_edit: bool = False,
    phase_status: str | None = None,
    plan_status: str | None = None,
) -> Path:
    """Upsert one phase in PHASES.json and update STATE.json status."""
    plan_dir = plan_dir_for(root, plan_id)
    plan_dir.mkdir(parents=True, exist_ok=True)
    phases_path = plan_dir / "PHASES.json"
    state_path = plan_dir / "STATE.json"

    manifest = _read_json(phases_path) or {
        "schema_version": 1,
        "workflow": "planning_with_files",
        "status": "planning",
        "current_phase": 0,
        "phases": [],
    }
    phases = manifest.get("phases")
    if not isinstance(phases, list):
        phases = []
        manifest["phases"] = phases

    phase_index = None
    for index, raw in enumerate(phases):
        if isinstance(raw, dict) and raw.get("id") == phase_id:
            phase_index = index
            break

    payload = {
        "id": phase_id,
        "title": phase_title,
        "workunit_kind": workunit_kind,
        "route": route,
        "allowed_edit": allowed_edit,
        "status": phase_status or "pending",
    }
    if phase_index is None:
        phases.append(payload)
        phase_index = len(phases) - 1
    else:
        merged = dict(phases[phase_index])
        merged.update(payload)
        phases[phase_index] = merged

    if plan_status is not None:
        manifest["status"] = plan_status
    manifest["current_phase"] = phase_index + 1
    _write_json(phases_path, manifest)

    state = _read_json(state_path) or {"schema_version": 1, "plan_id": plan_id}
    state["status"] = plan_status or manifest.get("status", "planning")
    state["current_phase"] = phase_index + 1
    _write_json(state_path, state)

    return ensure_phase_artifacts(root, plan_id=plan_id, phase_id=phase_id)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_phase_placeholders(phase_dir: Path) -> None:
    (phase_dir / "TASKMEMORY.md").touch(exist_ok=True)
    if not (phase_dir / "EVIDENCE.json").exists():
        _write_json(phase_dir / "EVIDENCE.json", {"schema_version": 1, "evidence": []})
    (phase_dir / "RESULT.md").touch(exist_ok=True)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None
