"""Tests for task-local cron execution policy."""

from __future__ import annotations

import json
from pathlib import Path

from controlmesh.cron.execution import enrich_instruction
from controlmesh.cron.policy import CronTaskPolicy, load_task_policy


def test_missing_task_config_defaults_to_notify_only_publish_disabled(tmp_path: Path) -> None:
    """A task without sidecar config must default to local artifact + notify-only."""
    policy = load_task_policy(tmp_path)

    assert policy.delivery.primary == "feishu"
    assert policy.delivery.format == "markdown_text"
    assert policy.artifact.mode == "local"
    assert policy.artifact.path == "output"
    assert policy.publish.enabled is False
    assert policy.publish.target == "none"
    assert policy.publish.require_review is True


def test_task_config_can_explicitly_enable_external_update(tmp_path: Path) -> None:
    """External writes are represented explicitly in task-local policy."""
    (tmp_path / "task.config.json").write_text(
        json.dumps(
            {
                "delivery": {
                    "primary": "feishu",
                    "format": "markdown_text",
                },
                "artifact": {
                    "mode": "local",
                    "path": "artifacts",
                },
                "publish": {
                    "enabled": True,
                    "target": "feishu_bitable",
                    "mode": "upsert",
                    "require_review": False,
                },
            },
        ),
        encoding="utf-8",
    )

    policy = load_task_policy(tmp_path)

    assert policy.delivery.primary == "feishu"
    assert policy.delivery.format == "markdown_text"
    assert policy.artifact.mode == "local"
    assert policy.artifact.path == "artifacts"
    assert policy.publish.enabled is True
    assert policy.publish.target == "feishu_bitable"
    assert policy.publish.mode == "upsert"
    assert policy.publish.require_review is False


def test_enrich_instruction_injects_publish_disabled_guard() -> None:
    """Cron execution instructions should make notify-vs-publish explicit."""
    enriched = enrich_instruction("Run the task", "daily", policy=CronTaskPolicy())

    assert "Cron delivery policy" in enriched
    assert "publish.enabled=false" in enriched
    assert "Do not write to external publishing targets" in enriched
    assert "local artifact path: output" in enriched


def test_enrich_instruction_allows_explicit_publish_target(tmp_path: Path) -> None:
    """When a task opts in, the prompt should state the exact publish boundary."""
    (tmp_path / "task.config.json").write_text(
        json.dumps(
            {
                "publish": {
                    "enabled": True,
                    "target": "feishu_bitable",
                    "mode": "upsert",
                    "require_review": False,
                },
            },
        ),
        encoding="utf-8",
    )
    policy = load_task_policy(tmp_path)

    enriched = enrich_instruction("Run the task", "daily", policy=policy)

    assert "publish.enabled=true" in enriched
    assert "publish target: feishu_bitable" in enriched
    assert "publish mode: upsert" in enriched
