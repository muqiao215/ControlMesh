"""Cron job management: JSON-based persistence.

Jobs are stored in a JSON file. The CronObserver watches the file
for changes and schedules jobs in-process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from threading import RLock

from controlmesh.infra.json_store import load_json
from controlmesh.cron.guarded_store import LockedJsonJobs

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    """A scheduled job definition."""

    id: str
    title: str
    description: str
    schedule: str
    task_folder: str
    agent_instruction: str
    enabled: bool = True
    timezone: str = ""
    created_at: str = ""
    last_run_at: str | None = None
    last_run_status: str | None = None
    manual_run_at: str | None = None
    manual_run_status: str | None = None

    # Per-task execution overrides
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    cli_parameters: list[str] = field(default_factory=list)

    # Quiet hours (None = use global config defaults)
    quiet_start: int | None = None
    quiet_end: int | None = None

    # Optional dependency for sequential execution
    dependency: str | None = None

    # Job profile: stable recurring automation vs bounded monitor-style scheduler
    job_kind: str = "recurring"

    # Execution split: legacy one-shot vs TaskHub-backed background task
    execution_mode: str = "oneshot"
    workunit_kind: str | None = None
    risk: str | None = None
    output_policy: str | None = None

    # Routing: deliver results to the chat/topic where the job was created
    chat_id: int = 0
    topic_id: int | None = None
    transport: str = "tg"

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "schedule": self.schedule,
            "task_folder": self.task_folder,
            "agent_instruction": self.agent_instruction,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "last_run_status": self.last_run_status,
            "manual_run_at": self.manual_run_at,
            "manual_run_status": self.manual_run_status,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "cli_parameters": self.cli_parameters,
            "quiet_start": self.quiet_start,
            "quiet_end": self.quiet_end,
            "dependency": self.dependency,
            "job_kind": self.job_kind,
            "execution_mode": self.execution_mode,
            "workunit_kind": self.workunit_kind,
            "risk": self.risk,
            "output_policy": self.output_policy,
            "chat_id": self.chat_id,
            "topic_id": self.topic_id,
            "transport": self.transport,
        }
        if self.timezone:
            result["timezone"] = self.timezone
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CronJob:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description", ""),
            schedule=data["schedule"],
            task_folder=data["task_folder"],
            agent_instruction=data["agent_instruction"],
            enabled=data.get("enabled", True),
            timezone=data.get("timezone", ""),
            created_at=data.get("created_at", ""),
            last_run_at=data.get("last_run_at"),
            last_run_status=data.get("last_run_status"),
            manual_run_at=data.get("manual_run_at"),
            manual_run_status=data.get("manual_run_status"),
            provider=data.get("provider"),
            model=data.get("model"),
            reasoning_effort=data.get("reasoning_effort"),
            cli_parameters=data.get("cli_parameters", []),
            quiet_start=data.get("quiet_start"),
            quiet_end=data.get("quiet_end"),
            dependency=data.get("dependency"),
            job_kind=data.get("job_kind", "recurring"),
            execution_mode=data.get("execution_mode", "oneshot"),
            workunit_kind=data.get("workunit_kind"),
            risk=data.get("risk"),
            output_policy=data.get("output_policy"),
            chat_id=data.get("chat_id", 0),
            topic_id=data.get("topic_id"),
            transport=data.get("transport", "tg"),
        )


class CronManager:
    """Manages cron jobs: JSON persistence.

    The CronObserver watches the JSON file for changes and handles
    scheduling. This class is responsible for data only.
    """

    def __init__(self, *, jobs_path: Path) -> None:
        self._jobs_path = jobs_path
        self._cache_lock = RLock()
        self._jobs: list[CronJob] = self._load()

    # -- CRUD --

    def add_job(self, job: CronJob) -> None:
        def mutate(data):
            if any(row["id"] == job.id for row in data["jobs"]):
                raise ValueError(f"Job '{job.id}' already exists")
            data["jobs"].append(job.to_dict())

        self._mutate_jobs(mutate)

    def remove_job(self, job_id: str) -> bool:
        def mutate(data):
            previous = len(data["jobs"])
            data["jobs"] = [row for row in data["jobs"] if row["id"] != job_id]
            return len(data["jobs"]) != previous

        return self._mutate_jobs(mutate)

    def list_jobs(self) -> list[CronJob]:
        """Return all jobs."""
        return list(self._jobs)

    def get_job(self, job_id: str) -> CronJob | None:
        """Return a job by ID, or None."""
        return next((j for j in self._jobs if j.id == job_id), None)

    def set_enabled(self, job_id: str, *, enabled: bool) -> bool:
        def mutate(data):
            for row in data["jobs"]:
                if row["id"] == job_id:
                    if row.get("enabled", True) == enabled:
                        return False
                    row["enabled"] = enabled
                    return True
            return False

        return self._mutate_jobs(mutate)

    def set_all_enabled(self, *, enabled: bool) -> int:
        def mutate(data):
            changed = 0
            for row in data["jobs"]:
                if row.get("enabled", True) != enabled:
                    row["enabled"] = enabled
                    changed += 1
            return changed

        return self._mutate_jobs(mutate)

    def update_run_status(self, job_id: str, *, status: str) -> None:
        def mutate(data):
            for row in data["jobs"]:
                if row["id"] == job_id:
                    row["last_run_at"] = datetime.now(UTC).isoformat()
                    row["last_run_status"] = status
                    return

        self._mutate_jobs(mutate)

    def update_manual_run_status(self, job_id: str, *, status: str) -> None:
        """Record manual execution without overwriting concurrent configuration edits."""

        def mutate(data):
            for row in data["jobs"]:
                if row["id"] == job_id:
                    row["manual_run_at"] = datetime.now(UTC).isoformat()
                    row["manual_run_status"] = status
                    return

        self._mutate_jobs(mutate)

    def reload(self) -> None:
        """Re-read jobs from disk (called by CronObserver on file change)."""
        with self._cache_lock:
            self._jobs = self._load()

    # -- Persistence --

    def _load(self) -> list[CronJob]:
        """Load jobs from JSON file."""
        data = load_json(self._jobs_path)
        if data is None:
            return []
        try:
            jobs = [CronJob.from_dict(j) for j in data.get("jobs", [])]
        except (KeyError, TypeError):
            logger.warning("Corrupt cron jobs file: %s", self._jobs_path)
            return []
        for j in jobs:
            logger.debug("Job loaded id=%s title=%s enabled=%s", j.id, j.title, j.enabled)
        return jobs

    def _save(self) -> None:
        raise RuntimeError(
            "Unsafe cached whole-registry save disabled; use transactional field mutations"
        )

    def _mutate_jobs(self, mutation):
        """Serialize cooperating writers and refresh this manager's cache atomically."""

        def checked_mutation(data):
            # Reject an invalid existing registry before committing any change.
            for row in data["jobs"]:
                CronJob.from_dict(row)
            result = mutation(data)
            for row in data["jobs"]:
                CronJob.from_dict(row)
            return result

        with self._cache_lock:
            result, data = LockedJsonJobs(self._jobs_path).mutate(checked_mutation)
            self._jobs = [CronJob.from_dict(row) for row in data["jobs"]]
            return result
