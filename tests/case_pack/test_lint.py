from __future__ import annotations

import json
from pathlib import Path

import pytest

from controlmesh.case_pack.lint import CasePackLintError, lint_case_pack_path

EXAMPLES_ROOT = Path(__file__).resolve().parents[2] / "examples" / "case-pack"


def test_minimal_case_passes_semantic_lint() -> None:
    errors = lint_case_pack_path(EXAMPLES_ROOT / "minimal" / "case.json")

    assert errors == []


def test_real_case_passes_semantic_lint() -> None:
    errors = lint_case_pack_path(EXAMPLES_ROOT / "public-repo-release-gate" / "case.json")

    assert errors == []


def test_lint_reports_missing_refs_and_semantic_breaks(tmp_path: Path) -> None:
    source_path = EXAMPLES_ROOT / "minimal" / "case.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload["events"][0]["evidence_refs"] = ["msg:missing"]
    payload["tool_events"][0]["linked_event_ids"] = ["event-missing"]
    payload["timeline"][1]["order"] = 3
    payload["turning_points"][0]["event_ids"] = []
    payload["turning_points"][0]["tool_event_ids"] = []
    payload["tool_events"][0]["why_it_matters"] = ""
    payload["lifted_view"]["questions"][0]["timeline_refs"] = ["timeline-missing"]
    broken_path = tmp_path / "broken-case.json"
    broken_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(CasePackLintError) as exc_info:
        lint_case_pack_path(broken_path, raise_on_error=True)

    message = str(exc_info.value)
    assert "unknown evidence ref" in message
    assert "linked_event_ids" in message
    assert "continuous" in message
    assert "turning point" in message
    assert "why_it_matters" in message
    assert "lifted_view" in message
