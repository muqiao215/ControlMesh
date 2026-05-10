from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_BIND_ALL = ".".join(["0"] * 4)

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
    assert payload["listener"] == f"http://{_BIND_ALL}:8742"

    config = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert config["webhooks"]["enabled"] is True
    assert config["webhooks"]["host"] == _BIND_ALL
    assert config["webhooks"]["token"] != "disabled"

    hooks = json.loads((tmp_path / "webhooks.json").read_text(encoding="utf-8"))["hooks"]
    hook = next(h for h in hooks if h["id"] == "github-ci-failed")
    assert hook["mode"] == "task"
    assert hook["task_name"] == "CI failure triage"
    assert hook["workunit_kind"] == "test_triage"
    assert hook["provider"] is None
    assert hook["model"] is None
    assert hook["reasoning_effort"] is None


def test_setup_ci_failure_webhook_preserves_existing_hook_routing_overrides(tmp_path: Path) -> None:
    env = {**os.environ, "CONTROLMESH_HOME": str(tmp_path)}
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(json.dumps({"webhooks": {}}), encoding="utf-8")
    (tmp_path / "webhooks.json").write_text(
        json.dumps(
            {
                "hooks": [
                    {
                        "id": "github-ci-failed",
                        "title": "Old title",
                        "description": "Old description",
                        "mode": "task",
                        "prompt_template": "old",
                        "enabled": True,
                        "task_folder": None,
                        "auth_mode": "bearer",
                        "token": "keep-me",
                        "hmac_secret": "",
                        "hmac_header": "",
                        "hmac_algorithm": "sha256",
                        "hmac_encoding": "hex",
                        "hmac_sig_prefix": "sha256=",
                        "hmac_sig_regex": "",
                        "hmac_payload_prefix_regex": "",
                        "created_at": "2026-05-10T00:00:00+00:00",
                        "trigger_count": 7,
                        "last_triggered_at": "2026-05-10T01:00:00+00:00",
                        "last_error": "error:test",
                        "provider": "claude",
                        "model": "sonnet",
                        "reasoning_effort": "medium",
                        "cli_parameters": ["--foo"],
                        "quiet_start": 22,
                        "quiet_end": 7,
                        "dependency": "chrome_browser",
                        "task_name": "Custom triage",
                        "parent_agent": "ops",
                        "task_transport": "qqbot",
                        "workunit_kind": "code_review",
                        "topology": "fanout_merge",
                        "route": "manual",
                    }
                ]
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
    hooks = json.loads((tmp_path / "webhooks.json").read_text(encoding="utf-8"))["hooks"]
    hook = next(h for h in hooks if h["id"] == "github-ci-failed")
    assert hook["title"] == "GitHub CI Failed"
    assert hook["description"] == "Create a background triage task for failed CI runs"
    assert hook["prompt_template"].startswith("Repository: {{repo}}")
    assert hook["token"] == "keep-me"
    assert hook["provider"] == "claude"
    assert hook["model"] == "sonnet"
    assert hook["reasoning_effort"] == "medium"
    assert hook["cli_parameters"] == ["--foo"]
    assert hook["quiet_start"] == 22
    assert hook["quiet_end"] == 7
    assert hook["dependency"] == "chrome_browser"
    assert hook["task_name"] == "Custom triage"
    assert hook["parent_agent"] == "ops"
    assert hook["task_transport"] == "qqbot"
    assert hook["workunit_kind"] == "code_review"
    assert hook["topology"] == "fanout_merge"
    assert hook["route"] == "manual"
