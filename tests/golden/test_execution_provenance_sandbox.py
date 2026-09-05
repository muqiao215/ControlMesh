from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.golden.runners.execution_provenance_sandbox import REQUIRED_CASES, generate_matrix

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/golden/fixtures/runtime/execution-provenance-sandbox.matrix.json"
SCHEMA = ROOT / "tests/golden/schema/execution-provenance-sandbox-matrix.schema.json"


def test_execution_provenance_sandbox_matrix_matches_python_oracle() -> None:
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == generate_matrix()


def test_execution_provenance_sandbox_matrix_has_exact_inventory() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    matrix = json.loads(FIXTURE.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(matrix)
    assert tuple(case["id"] for case in matrix["cases"]) == REQUIRED_CASES
    assert matrix["production_owner"] == "python"
