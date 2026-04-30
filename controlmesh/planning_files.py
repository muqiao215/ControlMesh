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
) -> Path:
    """Create `.controlmesh/plans/<plan_id>` artifacts for a phased workflow."""
    plan_dir = Path(root).expanduser() / ".controlmesh" / "plans" / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "PLAN.md").write_text(plan_markdown.rstrip() + "\n", encoding="utf-8")
    manifest = PlanFilesManifest(status=status, phases=phases)
    _write_json(plan_dir / "PHASES.json", manifest.to_dict())
    _write_json(
        plan_dir / "STATE.json",
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": status,
            "current_phase": manifest.current_phase,
        },
    )
    for phase in phases:
        phase_dir = plan_dir / phase.id
        phase_dir.mkdir(exist_ok=True)
        _write_phase_placeholders(phase_dir)
    return plan_dir


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_phase_placeholders(phase_dir: Path) -> None:
    (phase_dir / "TASKMEMORY.md").touch(exist_ok=True)
    if not (phase_dir / "EVIDENCE.json").exists():
        _write_json(phase_dir / "EVIDENCE.json", {"schema_version": 1, "evidence": []})
    (phase_dir / "RESULT.md").touch(exist_ok=True)
