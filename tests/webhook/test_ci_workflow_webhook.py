from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_sends_controlmesh_webhook_before_telegram() -> None:
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    notify_job = data["jobs"]["notify-failure"]
    steps = notify_job["steps"]
    step_names = [step["name"] for step in steps]

    assert "Send ControlMesh webhook" in step_names
    assert "Send Telegram notification" in step_names
    assert step_names.index("Send ControlMesh webhook") < step_names.index(
        "Send Telegram notification"
    )

    webhook_step = next(step for step in steps if step["name"] == "Send ControlMesh webhook")
    env = webhook_step["env"]
    run_script = webhook_step["run"]

    assert env["CONTROLMESH_WEBHOOK_URL"] == "${{ secrets.CONTROLMESH_WEBHOOK_URL }}"
    assert env["CONTROLMESH_WEBHOOK_BEARER_TOKEN"] == (
        "${{ secrets.CONTROLMESH_WEBHOOK_BEARER_TOKEN }}"
    )
    assert "webhook-payload.json" in run_script
    assert '"repo": os.environ["REPOSITORY"]' in run_script
    assert '"synthetic_failure_result": os.environ["SMOKE_RESULT"]' in run_script
    assert "Authorization: Bearer ${CONTROLMESH_WEBHOOK_BEARER_TOKEN}" in run_script
