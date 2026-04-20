"""Task-local cron execution policy.

Keeps publish/update decisions in the cron task folder instead of the
global cron registry so scheduling metadata stays stable and narrow.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class DeliveryPolicy:
    """How a cron task should notify the user."""

    primary: str = "feishu"
    format: str = "markdown_text"


@dataclass(slots=True)
class ArtifactPolicy:
    """Where task artifacts should be written."""

    mode: str = "local"
    path: str = "output"


@dataclass(slots=True)
class PublishPolicy:
    """Whether the task may write to external systems."""

    enabled: bool = False
    target: str = "none"
    mode: str = "none"
    require_review: bool = True


@dataclass(slots=True)
class CronTaskPolicy:
    """Combined task-local policy sidecar."""

    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)
    artifact: ArtifactPolicy = field(default_factory=ArtifactPolicy)
    publish: PublishPolicy = field(default_factory=PublishPolicy)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_task_policy() -> CronTaskPolicy:
    """Return the default notify-only cron task policy."""
    return CronTaskPolicy()


def task_policy_path(task_dir: Path) -> Path:
    """Return the sidecar policy file path for a cron task folder."""
    return task_dir / "task.config.json"


def write_default_task_policy(task_dir: Path) -> Path:
    """Create the default task policy sidecar for a new cron task."""
    path = task_policy_path(task_dir)
    path.write_text(
        json.dumps(default_task_policy().to_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_task_policy(task_dir: Path) -> CronTaskPolicy:
    """Load a task-local policy sidecar, falling back to safe defaults."""
    path = task_policy_path(task_dir)
    if not path.is_file():
        return default_task_policy()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_task_policy()

    if not isinstance(raw, dict):
        return default_task_policy()

    delivery = _load_dataclass(DeliveryPolicy, raw.get("delivery"))
    artifact = _load_dataclass(ArtifactPolicy, raw.get("artifact"))
    publish = _load_dataclass(PublishPolicy, raw.get("publish"))
    return CronTaskPolicy(delivery=delivery, artifact=artifact, publish=publish)


def _load_dataclass(cls: type[T], raw: Any) -> T:
    """Best-effort dataclass construction from a JSON object."""
    base = cls()
    if not isinstance(raw, dict):
        return base

    allowed = set(base.__dataclass_fields__)  # type: ignore[attr-defined]
    values = {key: value for key, value in raw.items() if key in allowed}
    return cls(**values)
