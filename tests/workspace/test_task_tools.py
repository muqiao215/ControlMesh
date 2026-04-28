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
    def do_POST(self) -> None:  # noqa: N802
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

    def log_message(self, format: str, *args: object) -> None:
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
