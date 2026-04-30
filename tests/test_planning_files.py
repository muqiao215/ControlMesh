"""Tests for file-backed plan artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from controlmesh.planning_files import PlanPhase, create_plan_files


def test_create_plan_files_scaffolds_phase_artifacts(tmp_path: Path) -> None:
    plan_dir = create_plan_files(
        tmp_path,
        plan_id="demo-plan",
        plan_markdown="# Demo\n",
        phases=(
            PlanPhase(
                id="phase-001",
                title="Audit repository",
                workunit_kind="repo_audit",
            ),
            PlanPhase(
                id="phase-002",
                title="Prepare release",
                workunit_kind="github_release",
            ),
        ),
        status="executing",
    )

    assert plan_dir == tmp_path / ".controlmesh" / "plans" / "demo-plan"
    phases = json.loads((plan_dir / "PHASES.json").read_text(encoding="utf-8"))
    assert phases["workflow"] == "planning_with_files"
    assert phases["phases"][0]["workunit_kind"] == "repo_audit"
    assert (plan_dir / "phase-001" / "TASKMEMORY.md").exists()
    assert (plan_dir / "phase-001" / "EVIDENCE.json").exists()
    assert (plan_dir / "phase-001" / "RESULT.md").exists()
