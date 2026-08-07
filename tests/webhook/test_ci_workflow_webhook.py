from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_sends_telegram_notification_on_failure() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    notify_job = data["jobs"]["notify-failure"]
    steps = notify_job["steps"]
    step_names = [step["name"] for step in steps]

    assert "Send Telegram notification" in step_names
    assert "Send ControlMesh webhook" not in step_names

    telegram_step = next(step for step in steps if step["name"] == "Send Telegram notification")
    env = telegram_step["env"]
    run_script = telegram_step["run"]

    assert env["TELEGRAM_BOT_TOKEN"] == "${{ secrets.TELEGRAM_BOT_TOKEN }}"
    assert env["TELEGRAM_CHAT_ID"] == "${{ secrets.TELEGRAM_CHAT_ID }}"
    assert env["TELEGRAM_MESSAGE_THREAD_ID"] == "${{ secrets.TELEGRAM_MESSAGE_THREAD_ID }}"
    assert 'echo "Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not configured."' in run_script
    assert '"https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"' in run_script
    assert '--data-urlencode "chat_id=${TELEGRAM_CHAT_ID}"' in run_script
    assert '--data-urlencode "message_thread_id=${TELEGRAM_MESSAGE_THREAD_ID}"' in run_script
    assert 'f"ruff: {os.environ[\'RUFF_RESULT\']}"' in run_script
    assert 'f"mypy: {os.environ[\'MYPY_RESULT\']}"' in run_script
    assert 'f"product_layer: {os.environ[\'PRODUCT_LAYER_RESULT\']}"' in run_script
    assert 'f"synthetic_failure: {os.environ[\'SMOKE_RESULT\']}"' in run_script


def test_ci_workflow_requires_protocol_sdk_and_web_gates() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    product_job = data["jobs"]["product-layer"]
    run_commands = [step["run"] for step in product_job["steps"] if "run" in step]

    assert data["env"]["NODE_VERSION"] == "22"
    assert data["env"]["PNPM_VERSION"] == "10.33.4"
    assert "pnpm install --frozen-lockfile" in run_commands
    assert "pnpm check:protocol" in run_commands
    assert "pnpm test:golden" in run_commands
    assert "pnpm test:sdk" in run_commands
    assert "pnpm --filter @controlmesh/web build" in run_commands

    required_jobs = set(data["jobs"]["ci-success"]["needs"])
    assert required_jobs == {"ruff", "mypy", "test", "build", "product-layer"}
