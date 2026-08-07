"""Contract tests for the canonical Python task-lifecycle parity matrix."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from tests.golden.runners.task_lifecycle import REQUIRED_DOMAINS, generate_matrix

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/golden/fixtures/tasks/lifecycle.matrix.json"
SCHEMA = ROOT / "tests/golden/schema/task-lifecycle-matrix.schema.json"
ROLLBACK_GATE = ROOT / "tests/golden/fixtures/tasks/lifecycle.rollback-gate.json"
ROLLBACK_SCHEMA = ROOT / "tests/golden/schema/lifecycle-rollback-gate.schema.json"


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


def test_lifecycle_rollback_gate_is_schema_valid_and_retains_python_owner() -> None:
    schema = _load(ROLLBACK_SCHEMA)
    Draft202012Validator.check_schema(schema)
    gate = _load(ROLLBACK_GATE)
    Draft202012Validator(schema).validate(gate)
    assert gate["candidate_admitted"] is True
    assert gate["matched_case_count"] == gate["case_count"]
    assert gate["production_owner"] == gate["rollback_owner"] == "python"
    assert gate["public_mutation_api"] is False


def test_public_openapi_remains_read_only_after_candidate_admission() -> None:
    contract = yaml.safe_load(
        (ROOT / "schemas/controlmesh/openapi/controlmesh-admin.v1.yaml").read_text(encoding="utf-8")
    )
    methods = {
        method.lower()
        for path in contract["paths"].values()
        for method in path
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }
    assert methods == {"get"}
