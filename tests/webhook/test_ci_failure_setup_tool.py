from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "controlmesh"
    / "_home_defaults"
    / "workspace"
    / "tools"
    / "webhook_tools"
    / "setup_ci_failure_webhook.py"
)


def test_setup_ci_failure_webhook_enables_listener_and_registers_hook(tmp_path: Path) -> None:
    env = {**os.environ, "CONTROLMESH_HOME": str(tmp_path)}
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "webhooks": {
                    "enabled": False,
                    "host": "127.0.0.1",
                    "port": 8742,
                    "token": "disabled",
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(TOOL_PATH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hook_id"] == "github-ci-failed"
    assert payload["listener"] == "http://0.0.0.0:8742"

    config = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert config["webhooks"]["enabled"] is True
    assert config["webhooks"]["host"] == "0.0.0.0"
    assert config["webhooks"]["token"] != "disabled"

    hooks = json.loads((tmp_path / "webhooks.json").read_text(encoding="utf-8"))["hooks"]
    hook = next(h for h in hooks if h["id"] == "github-ci-failed")
    assert hook["mode"] == "task"
    assert hook["task_name"] == "CI failure triage"
    assert hook["workunit_kind"] == "test_execution"
