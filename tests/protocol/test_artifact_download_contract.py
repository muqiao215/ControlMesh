"""Contract gates for the planned, unregistered MW-006 download operation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = REPO_ROOT / "schemas" / "controlmesh" / "openapi" / "controlmesh-admin.v1.yaml"
CONTRACT_PATH = REPO_ROOT / "docs" / "typescript-migration" / "ARTIFACT_DOWNLOAD_CONTRACT.md"
SERVER_PATH = REPO_ROOT / "controlmesh" / "api" / "server.py"
DOWNLOAD_PATH = "/api/v1/tasks/{task_id}/artifacts/content"

REQUIRED_SECURITY_CASES = {
    "AD-AUTH-001",
    "AD-AUTH-002",
    "AD-AUTH-003",
    "AD-AUTH-004",
    "AD-PATH-001",
    "AD-PATH-002",
    "AD-PATH-003",
    "AD-PATH-004",
    "AD-PATH-005",
    "AD-PATH-006",
    "AD-TASK-001",
    "AD-DIR-001",
    "AD-ALLOW-001",
    "AD-ALLOW-002",
    "AD-ALLOW-003",
    "AD-SYMLINK-001",
    "AD-SYMLINK-002",
    "AD-SYMLINK-003",
    "AD-FILE-001",
    "AD-FILE-002",
    "AD-MIME-001",
    "AD-MIME-002",
}


def _download_operation() -> dict[str, object]:
    document = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    return document["paths"][DOWNLOAD_PATH]["get"]


def test_download_openapi_uses_task_and_relative_metadata_path() -> None:
    operation = _download_operation()
    parameters = {
        (parameter["name"], parameter["in"]): parameter
        for parameter in operation["parameters"]
    }

    assert operation["operationId"] == "downloadTaskArtifact"
    assert operation["security"] == [{"bearerAuth": []}]
    assert parameters[("task_id", "path")]["required"] is True
    relative_path = parameters[("relative_path", "query")]
    assert relative_path["required"] is True
    assert relative_path["schema"]["minLength"] == 1
    assert set(operation["responses"]) == {"200", "400", "401", "404"}
    assert operation["responses"]["200"]["content"]["*/*"]["schema"] == {
        "type": "string",
        "format": "binary",
    }


def test_download_security_matrix_matches_openapi_gate() -> None:
    operation = _download_operation()
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| (AD-[A-Z]+-\d{3}) \|", contract, flags=re.MULTILINE))

    assert documented == REQUIRED_SECURITY_CASES
    assert set(operation["x-controlmesh-security-tests"]) == REQUIRED_SECURITY_CASES


def test_download_contract_is_active_and_route_registered() -> None:
    operation = _download_operation()
    server_source = SERVER_PATH.read_text(encoding="utf-8")

    assert operation["x-controlmesh-status"] == "active"
    assert DOWNLOAD_PATH in server_source
