"""Regression tests for task tool bootstrapping."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_TASK_TOOLS = (
    REPO_ROOT / "controlmesh" / "_home_defaults" / "workspace" / "tools" / "task_tools"
)


class _TaskAPIHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        self.server.requests.append((self.path, payload))  # type: ignore[attr-defined]
        response = json.dumps({"success": True, "task_id": "task-123"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, message_format: str, *args: object) -> None:
        return


def _start_task_api() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TaskAPIHandler)
    server.requests = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _install_deployed_task_tools(tmp_path: Path) -> Path:
    deployed_dir = tmp_path / "workspace" / "tools" / "task_tools"
    shutil.copytree(SOURCE_TASK_TOOLS, deployed_dir)
    return deployed_dir


def _run_tool(tool: Path, port: int, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    env.pop("PYTHONPATH", None)
    env.pop("CONTROLMESH_CHAT_ID", None)
    env.pop("CONTROLMESH_TOPIC_ID", None)
    env["CONTROLMESH_INTERAGENT_HOST"] = "127.0.0.1"
    env["CONTROLMESH_INTERAGENT_PORT"] = str(port)
    return subprocess.run(
        [sys.executable, "-S", str(tool), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_route_task_bootstraps_controlmesh_without_pythonpath(tmp_path: Path) -> None:
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "route_task.py",
            server.server_address[1],
            [
                "--provider",
                "claw-code",
                "--kind",
                "test_execution",
                "--command",
                "uv run pytest tests/test_x.py -q",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    assert "Routed background task" in result.stdout
    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert requests == [
        (
            "/tasks/create",
            {
                "from": "main",
                "prompt": "Run this command and summarize the result: "
                "uv run pytest tests/test_x.py -q",
                "route": "auto",
                "workunit_kind": "test_execution",
                "command": "uv run pytest tests/test_x.py -q",
                "provider": "claw",
            },
        )
    ]


def test_create_task_bootstraps_controlmesh_without_pythonpath(tmp_path: Path) -> None:
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "create_task.py",
            server.server_address[1],
            [
                "--provider",
                "claw-code",
                "--name",
                "Demo task",
                "Investigate the failing smoke test",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    assert "Background task 'Demo task' created" in result.stdout
    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert requests == [
        (
            "/tasks/create",
            {
                "from": "main",
                "prompt": "Investigate the failing smoke test",
                "name": "Demo task",
                "provider": "claw",
            },
        )
    ]


def test_route_task_normalizes_openai_provider_to_codex(tmp_path: Path) -> None:
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "route_task.py",
            server.server_address[1],
            [
                "--provider",
                "openai",
                "--kind",
                "test_execution",
                "--command",
                "uv run pytest tests/test_x.py -q",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert requests[0][1]["provider"] == "codex"


def test_create_task_supports_plan_phase_flags(tmp_path: Path) -> None:
    deployed_dir = _install_deployed_task_tools(tmp_path)
    plan_file = tmp_path / "PLAN.md"
    plan_file.write_text("# Demo Plan\n", encoding="utf-8")
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "create_task.py",
            server.server_address[1],
            [
                "--name",
                "Phase task",
                "--kind",
                "phase_execution",
                "--plan-id",
                "demo-plan",
                "--plan-file",
                str(plan_file),
                "--phase-id",
                "phase-002",
                "--phase-title",
                "Implement policy",
                "Execute the approved phase",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert requests == [
        (
            "/tasks/create",
            {
                "from": "main",
                "prompt": "Execute the approved phase",
                "name": "Phase task",
                "workunit_kind": "phase_execution",
                "plan_id": "demo-plan",
                "plan_markdown": "# Demo Plan\n",
                "phase_id": "phase-002",
                "phase_title": "Implement policy",
            },
        )
    ]


def test_release_task_submits_only_first_phase_with_full_manifest(tmp_path: Path) -> None:
    """release_task.py should submit only the first phase; later phases stay in the manifest."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--repo-url",
                "https://github.com/org/repo",
                "--version",
                "1.2.3",
                "Release version 1.2.3",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    assert "Release workflow" in result.stdout
    assert "repo_audit" in result.stdout
    assert "preflight_checks" in result.stdout
    assert "publish" in result.stdout
    assert "submitted" in result.stdout
    assert "Later phases will be started by the foreground-controlled review loop" in result.stdout

    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert len(requests) == 1

    first_request = requests[0]
    assert first_request[0] == "/tasks/create"
    first_body = first_request[1]
    assert first_body["from"] == "main"
    assert "plan_id" in first_body
    assert "plan_phases" in first_body
    assert len(first_body["plan_phases"]) == 5
    assert first_body["phase_id"] == "repo_audit"
    assert first_body["plan_markdown"]  # Has PLAN.md content
    publish_phase = next(
        phase for phase in first_body["plan_phases"] if phase["id"] == "publish"
    )
    assert publish_phase["evaluator"] == "foreground"
    assert publish_phase["workunit_kind"] == "github_release"
    assert publish_phase["metadata"]["gate_kind"] == "release_publish"
    assert publish_phase["metadata"]["side_effect_key"] == "release_publish:repo:1.2.3"
    assert publish_phase["metadata"]["version"] == "1.2.3"
    assert publish_phase["metadata"]["tag"] == "v1.2.3"
    assert publish_phase["metadata"]["commands"][0] == "git push origin main"
    verify_phase = next(
        phase for phase in first_body["plan_phases"] if phase["id"] == "verify"
    )
    assert verify_phase["metadata"]["wait_for_publish_execution"] is True


def test_release_task_dry_run_shows_plan_only(tmp_path: Path) -> None:
    """--dry-run prints plan without submitting tasks."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--dry-run",
                "--repo-url",
                "https://github.com/org/repo",
                "Test release",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr
    assert "Dry-run mode" in result.stdout
    assert "no tasks submitted" in result.stdout

    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert len(requests) == 0  # No tasks submitted


def test_release_task_claude_preference_sets_explicit_provider_in_manifest(tmp_path: Path) -> None:
    """--claude should bind phases to explicit Claude provider/model, not pseudo-route strings."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--claude",
                "Claude-only release",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr

    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert len(requests) == 1
    first_body = requests[0][1]
    assert first_body["route"] == "auto"
    for phase in first_body["plan_phases"]:
        assert phase["provider"] == "claude"
        assert phase["model"] == "sonnet"


def test_release_task_start_phase_skips_earlier(tmp_path: Path) -> None:
    """--phase starts from specified phase, skipping earlier ones."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--phase",
                "release_prep",
                "Resume from release prep",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr

    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert len(requests) == 1
    first_body = requests[0][1]
    assert first_body["phase_id"] == "release_prep"
    assert [phase["id"] for phase in first_body["plan_phases"]] == [
        "release_prep",
        "publish",
        "verify",
    ]


def test_release_task_no_foreground_eval_disables_approval(tmp_path: Path) -> None:
    """--no-foreground-eval removes foreground evaluator from publish."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--no-foreground-eval",
                "Auto-publish release",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 0, result.stderr

    requests: list[tuple[str, dict[str, Any]]] = server.requests  # type: ignore[attr-defined]
    assert len(requests) == 1
    publish_phase = next(
        phase for phase in requests[0][1]["plan_phases"] if phase["id"] == "publish"
    )
    evaluator_value = publish_phase.get("evaluator", "")
    assert evaluator_value == ""  # No foreground approval


def test_release_task_invalid_phase_shows_error(tmp_path: Path) -> None:
    """Invalid --phase shows available phases."""
    deployed_dir = _install_deployed_task_tools(tmp_path)
    server, thread = _start_task_api()
    try:
        result = _run_tool(
            deployed_dir / "release_task.py",
            server.server_address[1],
            [
                "--phase",
                "nonexistent",
                "Test",
            ],
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 1
    assert "Unknown phase" in result.stderr
    assert "repo_audit" in result.stderr
