"""Adapter for consuming the standalone feishu-auth-kit CLI."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sibling_repo_root() -> Path:
    return _workspace_root().parent / "feishu-auth-kit"


def resolve_feishu_auth_kit_command() -> tuple[list[str], Path | None]:
    """Resolve the command used to invoke the standalone feishu-auth-kit CLI."""
    configured = os.getenv("CONTROLMESH_FEISHU_AUTH_KIT_BIN", "").strip()
    if configured:
        return shlex.split(configured), None

    binary = shutil.which("feishu-auth-kit")
    if binary:
        return [binary], None

    sibling_repo = _sibling_repo_root()
    sibling_venv_bin = sibling_repo / ".venv" / "bin" / "feishu-auth-kit"
    if sibling_venv_bin.exists():
        return [str(sibling_venv_bin)], None

    uv_bin = shutil.which("uv")
    if uv_bin and (sibling_repo / "pyproject.toml").exists():
        return [uv_bin, "run", "feishu-auth-kit"], sibling_repo

    msg = (
        "feishu-auth-kit CLI not found. Install it in PATH, set "
        "CONTROLMESH_FEISHU_AUTH_KIT_BIN, or keep the sibling repo with uv available."
    )
    raise FileNotFoundError(msg)


def run_feishu_auth_kit(
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command, cwd = resolve_feishu_auth_kit_command()
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [*command, *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def run_feishu_auth_kit_json(
    args: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run feishu-auth-kit and parse a JSON stdout payload."""
    result = run_feishu_auth_kit(args, extra_env=extra_env)
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "feishu-auth-kit failed"
        raise RuntimeError(msg)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        msg = "feishu-auth-kit did not return valid JSON"
        raise RuntimeError(msg) from exc
    if not isinstance(payload, dict):
        msg = "feishu-auth-kit returned a non-object JSON payload"
        raise TypeError(msg)
    return payload


def run_feishu_auth_kit_json_with_payload_file(
    args: list[str],
    *,
    payload: dict[str, Any],
    payload_flag: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run feishu-auth-kit with a temporary JSON payload file argument."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        json.dump(payload, handle, ensure_ascii=False)
        handle.flush()
        return run_feishu_auth_kit_json(
            [*args, payload_flag, handle.name],
            extra_env=extra_env,
        )


def parse_feishu_auth_kit_message_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Feishu inbound event through feishu-auth-kit's context contract."""
    return run_feishu_auth_kit_json_with_payload_file(
        ["agent", "parse-inbound"],
        payload=payload,
        payload_flag="--event-file",
    )
