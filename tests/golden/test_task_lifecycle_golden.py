"""Contract tests for the canonical Python task-lifecycle parity matrix."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.golden.runners.task_lifecycle import REQUIRED_DOMAINS, generate_matrix

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/golden/fixtures/tasks/lifecycle.matrix.json"
SCHEMA = ROOT / "tests/golden/schema/task-lifecycle-matrix.schema.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_lifecycle_matrix_matches_python_oracle() -> None:
    assert _load(FIXTURE) == generate_matrix()


def test_lifecycle_matrix_validates_and_has_unique_complete_inventory() -> None:
    schema = _load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    matrix = _load(FIXTURE)
    Draft202012Validator(schema).validate(matrix)
    cases = matrix["cases"]
    assert isinstance(cases, list)
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert {case["domain"] for case in cases} == set(REQUIRED_DOMAINS)
    assert {"tell.not_running", "resume.no_session", "cancel.missing", "artifact.traversal"} <= set(
        ids
    )
