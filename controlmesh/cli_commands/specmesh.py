"""Explicit read-only adapter for a trusted independent SpecMesh checkout.

This is an opt-in local command, not an untrusted plugin sandbox or dispatch hook.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from typing import Any
from pathlib import Path
from collections.abc import Sequence

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]


def check_project(
    request: dict[str, Any], *, specmesh_root: Path, timeout: float = 5.0
) -> dict[str, Any]:
    """Call the separately owned tool without reading/writing TaskHub state."""
    schemas = Path(__file__).resolve().parents[1] / "_specmesh_contracts"
    # Bundled schemas keep installed wheel behavior independent of checkout layout.
    for name in ("specmesh-request", "specmesh-result"):
        if not (schemas / f"{name}.schema.json").is_file():
            raise RuntimeError("bundled_specmesh_contract_missing")
    request_schema = json.loads((schemas / "specmesh-request.schema.json").read_text())
    result_schema = json.loads((schemas / "specmesh-result.schema.json").read_text())
    Draft202012Validator(request_schema).validate(request)
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 60:
        raise ValueError("timeout_must_be_between_zero_and_60")
    root = Path(specmesh_root).resolve(strict=True)
    if not (root / "specmesh_port/__main__.py").is_file():
        raise ValueError("independent_specmesh_port_missing")
    allowed = Path(request["repo_root"]).resolve(strict=True)
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "specmesh_port", "--allowed-root", str(allowed)],
            cwd=root,
            env=env,
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reasons": ["specmesh_timeout"]}
    if len(proc.stdout) > 1024 * 1024 or len(proc.stderr) > 65536:
        return {"ok": False, "reasons": ["specmesh_output_limit"]}
    try:
        result = json.loads(proc.stdout)
        Draft202012Validator(result_schema).validate(result)
    except (ValueError, ValidationError):
        return {"ok": False, "reasons": ["invalid_specmesh_response"]}
    reasons = []
    if proc.returncode != 0:
        reasons.append("specmesh_nonzero_exit")
    if result["observed_head"] != request["expected_head"]:
        reasons.append("head_changed")
    if result["status"] != "pass":
        reasons.append("specmesh_" + result["status"])
    if any(item["severity"] == "error" for item in result["findings"]):
        reasons.append("specmesh_error")
    return {"ok": not reasons, "reasons": reasons, "result": result}


def cmd_specmesh(args: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="controlmesh specmesh", description=__doc__)
    parser.add_argument(
        "operation", choices=("inspect", "check", "prepare_handoff", "verify_closeout")
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--specmesh-root",
        type=Path,
        required=True,
        help="Trusted SpecMesh code checkout, not the inspected repository",
    )
    parser.add_argument("--task", default=None)
    parser.add_argument("--timeout", type=float, default=5)
    values = list(args)
    if values and values[0] == "specmesh":
        values = values[1:]
    options = parser.parse_args(values)
    request = {
        "contract_version": "specmesh.port.v1-draft",
        "operation": options.operation,
        "repo_root": str(options.repo.resolve()),
        "expected_head": options.expected_head,
        "task_path": options.task,
        "mode": "read_only",
    }
    try:
        result = check_project(
            request, specmesh_root=options.specmesh_root, timeout=options.timeout
        )
    except (OSError, ValueError, ValidationError, RuntimeError) as exc:
        result = {"ok": False, "reasons": [type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False))
    if not result["ok"]:
        raise SystemExit(3)
