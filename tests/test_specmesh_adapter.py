import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from controlmesh.cli_commands.specmesh import check_project


def request(tmp_path):
    return {
        "contract_version": "specmesh.port.v1-draft",
        "operation": "check",
        "repo_root": str(tmp_path),
        "expected_head": "a" * 40,
        "task_path": None,
        "mode": "read_only",
    }


def test_adapter_rejects_error_findings_even_with_pass_status(tmp_path):
    (tmp_path / "specmesh_port").mkdir()
    (tmp_path / "specmesh_port/__main__.py").write_text("")
    result = {
        "contract_version": "specmesh.port.v1-draft",
        "observed_head": "a" * 40,
        "status": "pass",
        "references": [],
        "findings": [{"code": "missing", "severity": "error", "path": None, "message": "missing"}],
    }
    with patch(
        "controlmesh.cli_commands.specmesh.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr=""),
    ):
        assert not check_project(request(tmp_path), specmesh_root=tmp_path)["ok"]


def test_adapter_rejects_changed_head_and_invalid_response(tmp_path):
    (tmp_path / "specmesh_port").mkdir()
    (tmp_path / "specmesh_port/__main__.py").write_text("")
    for out in [
        "{}",
        json.dumps(
            {
                "contract_version": "specmesh.port.v1-draft",
                "observed_head": "b" * 40,
                "status": "pass",
                "references": [],
                "findings": [],
            }
        ),
    ]:
        with patch(
            "controlmesh.cli_commands.specmesh.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=out, stderr=""),
        ):
            assert not check_project(request(tmp_path), specmesh_root=tmp_path)["ok"]


def test_specmesh_contract_bundle_matches_source():
    root = Path(__file__).resolve().parents[1]
    for source in (root / "schemas/controlmesh/specmesh").glob("*.json"):
        assert (
            source.read_bytes()
            == (root / "controlmesh/_specmesh_contracts" / source.name).read_bytes()
        )
