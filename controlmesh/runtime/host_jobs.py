"""Durable host-side job execution for generic host-side step graphs."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.infra.platform import CREATION_FLAGS as _CREATION_FLAGS
from controlmesh.infra.process_tree import force_kill_process_tree
from controlmesh.runtime.registry import append_task_event
from controlmesh.workspace.paths import ControlMeshPaths

HostJobStepKind = Literal["host_job", "short_shell"]
HostJobStepState = Literal[
    "pending",
    "awaiting_approval",
    "running",
    "completed",
    "failed",
    "cancelled",
    "skipped",
]
HostJobState = Literal["pending", "running", "awaiting_approval", "completed", "failed", "cancelled"]
TERMINAL_HOST_JOB_STATES = frozenset({"completed", "failed", "cancelled"})


def _now() -> float:
    return time.time()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_now()))


def _command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _pid_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _job_state_rank(state: str) -> int:
    order = {
        "pending": 0,
        "running": 1,
        "awaiting_approval": 2,
        "completed": 3,
        "failed": 3,
        "cancelled": 3,
    }
    return order.get(state, -1)


def _sticky_transition(current: str, target: str) -> str:
    if current in TERMINAL_HOST_JOB_STATES:
        return current
    if _job_state_rank(target) < _job_state_rank(current):
        return current
    return target


def _merge_step_state(existing: HostJobStep, incoming: HostJobStep) -> HostJobStep:
    if existing.state in {"completed", "failed", "cancelled", "skipped"}:
        return existing
    return incoming


def _merge_job(existing: HostJob, incoming: HostJob) -> HostJob:
    merged_steps: list[HostJobStep] = []
    existing_by_id = {step.id: step for step in existing.steps}
    for step in incoming.steps:
        current = existing_by_id.get(step.id)
        merged_steps.append(_merge_step_state(current, step) if current is not None else step)

    return HostJob(
        job_id=existing.job_id,
        job_kind=incoming.job_kind or existing.job_kind,
        source_task_id=incoming.source_task_id or existing.source_task_id,
        plan_id=incoming.plan_id or existing.plan_id,
        repo=incoming.repo or existing.repo,
        version=incoming.version or existing.version,
        tag=incoming.tag or existing.tag,
        summary=incoming.summary or existing.summary,
        state=_sticky_transition(existing.state, incoming.state),
        current_step_id=incoming.current_step_id or existing.current_step_id,
        steps=merged_steps,
        created_at=existing.created_at,
        updated_at=incoming.updated_at or existing.updated_at,
        completed_at=existing.completed_at or incoming.completed_at,
        last_error=existing.last_error or incoming.last_error,
    )


@dataclass(slots=True)
class HostJobStep:
    id: str
    title: str
    command: str
    kind: HostJobStepKind = "host_job"
    approval_required: bool = False
    side_effect: bool = False
    cwd: str = ""
    state: HostJobStepState = "pending"
    exit_code: int | None = None
    stdout_path: str = ""
    stderr_path: str = ""
    started_at: str = ""
    finished_at: str = ""
    completed_at: str = ""
    approved_at: str = ""
    approved_by: str = ""
    pid: int | None = None
    pgid: int | None = None
    command_digest: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "command": self.command,
            "kind": self.kind,
            "approval_required": self.approval_required,
            "side_effect": self.side_effect,
            "cwd": self.cwd,
            "state": self.state,
            "exit_code": self.exit_code,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "completed_at": self.completed_at,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
            "pid": self.pid,
            "pgid": self.pgid,
            "command_digest": self.command_digest or _command_digest(self.command),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HostJobStep:
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            command=str(data.get("command") or ""),
            kind=str(data.get("kind") or "host_job"),
            approval_required=bool(data.get("approval_required", False)),
            side_effect=bool(data.get("side_effect", False)),
            cwd=str(data.get("cwd") or ""),
            state=str(data.get("state") or "pending"),
            exit_code=data.get("exit_code"),
            stdout_path=str(data.get("stdout_path") or ""),
            stderr_path=str(data.get("stderr_path") or ""),
            started_at=str(data.get("started_at") or ""),
            finished_at=str(data.get("finished_at") or data.get("completed_at") or ""),
            completed_at=str(data.get("completed_at") or ""),
            approved_at=str(data.get("approved_at") or ""),
            approved_by=str(data.get("approved_by") or ""),
            pid=data.get("pid"),
            pgid=data.get("pgid"),
            command_digest=str(data.get("command_digest") or ""),
            detail=str(data.get("detail") or ""),
        )


@dataclass(slots=True)
class HostJob:
    job_id: str
    job_kind: str = "generic"
    source_task_id: str = ""
    plan_id: str = ""
    repo: str = ""
    version: str = ""
    tag: str = ""
    summary: str = ""
    state: HostJobState = "pending"
    current_step_id: str = ""
    steps: list[HostJobStep] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    completed_at: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_kind": self.job_kind,
            "source_task_id": self.source_task_id,
            "plan_id": self.plan_id,
            "repo": self.repo,
            "version": self.version,
            "tag": self.tag,
            "summary": self.summary,
            "state": self.state,
            "current_step_id": self.current_step_id,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HostJob:
        raw_steps = data.get("steps") or []
        steps = [HostJobStep.from_dict(item) for item in raw_steps if isinstance(item, dict)]
        return cls(
            job_id=str(data.get("job_id") or ""),
            job_kind=str(data.get("job_kind") or "generic"),
            source_task_id=str(data.get("source_task_id") or ""),
            plan_id=str(data.get("plan_id") or ""),
            repo=str(data.get("repo") or ""),
            version=str(data.get("version") or ""),
            tag=str(data.get("tag") or ""),
            summary=str(data.get("summary") or ""),
            state=str(data.get("state") or "pending"),
            current_step_id=str(data.get("current_step_id") or ""),
            steps=steps,
            created_at=str(data.get("created_at") or _now_iso()),
            updated_at=str(data.get("updated_at") or _now_iso()),
            completed_at=str(data.get("completed_at") or ""),
            last_error=str(data.get("last_error") or ""),
        )


@dataclass(slots=True)
class HostJobSpec:
    job_id: str
    job_kind: str = "generic"
    source_task_id: str = ""
    plan_id: str = ""
    repo: str = ""
    version: str = ""
    tag: str = ""
    summary: str = ""
    steps: list[HostJobStep] = field(default_factory=list)

    def to_job(self) -> HostJob:
        return HostJob(
            job_id=self.job_id,
            job_kind=self.job_kind,
            source_task_id=self.source_task_id,
            plan_id=self.plan_id,
            repo=self.repo,
            version=self.version,
            tag=self.tag,
            summary=self.summary,
            steps=[
                HostJobStep.from_dict(step.to_dict()) if isinstance(step, HostJobStep) else step
                for step in self.steps
            ],
        )


def task_host_job_id(task_id: str) -> str:
    normalized = task_id.strip() or "task"
    return f"task-{normalized}"


def default_single_step(
    *,
    step_id: str,
    title: str,
    command: str,
    kind: HostJobStepKind = "host_job",
    approval_required: bool = False,
    side_effect: bool = False,
    cwd: str = "",
) -> HostJobStep:
    return HostJobStep(
        id=step_id,
        title=title,
        command=command,
        kind=kind,
        approval_required=approval_required,
        side_effect=side_effect,
        cwd=cwd,
        command_digest=_command_digest(command),
    )


def default_test_execution_steps(command: str, *, step_id: str = "test_execution") -> list[HostJobStep]:
    return [
        default_single_step(step_id=step_id, title="Run test execution", command=command, kind="host_job")
    ]


def single_step_host_job_spec(
    *,
    job_id: str,
    job_kind: str,
    source_task_id: str = "",
    plan_id: str = "",
    repo: str = "",
    version: str = "",
    tag: str = "",
    summary: str = "",
    step_id: str,
    step_title: str,
    command: str,
    kind: HostJobStepKind = "host_job",
    approval_required: bool = False,
    side_effect: bool = False,
    cwd: str = "",
) -> HostJobSpec:
    return HostJobSpec(
        job_id=job_id,
        job_kind=job_kind,
        source_task_id=source_task_id,
        plan_id=plan_id,
        repo=repo,
        version=version,
        tag=tag,
        summary=summary or command,
        steps=[
            default_single_step(
                step_id=step_id,
                title=step_title,
                command=command,
                kind=kind,
                approval_required=approval_required,
                side_effect=side_effect,
                cwd=cwd or repo,
            )
        ],
    )


class HostJobStore:
    """Persistent JSON store for host jobs."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._path = paths.runtime_host_jobs_path
        self._jobs_dir = paths.runtime_host_jobs_dir
        self._artifacts_root = paths.runtime_host_job_artifacts_dir

    def job_dir(self, job_id: str) -> Path:
        return self._jobs_dir / job_id

    def _job_authority_paths(self, job_id: str) -> tuple[Path, Path, Path]:
        job_dir = self.job_dir(job_id)
        return job_dir / "HOST_JOB.json", job_dir / "STEPS.json", job_dir / "TOOL_RESULT.json"

    def exit_code_path(self, job_id: str, step_id: str) -> Path:
        return self._artifacts_dir(job_id, step_id) / "exit_code.txt"

    def stdout_path(self, job_id: str, step_id: str) -> Path:
        return self._artifacts_dir(job_id, step_id) / "stdout.log"

    def stderr_path(self, job_id: str, step_id: str) -> Path:
        return self._artifacts_dir(job_id, step_id) / "stderr.log"

    def _artifacts_dir(self, job_id: str, step_id: str) -> Path:
        return self._artifacts_root / job_id / step_id

    def list_jobs(self) -> list[HostJob]:
        jobs_from_dirs = self._list_jobs_from_dirs()
        if jobs_from_dirs:
            return jobs_from_dirs
        raw = load_json(self._path)
        if not isinstance(raw, dict):
            return []
        jobs = raw.get("jobs")
        if not isinstance(jobs, list):
            return []
        return [HostJob.from_dict(item) for item in jobs if isinstance(item, dict)]

    def get(self, job_id: str) -> HostJob | None:
        for job in self.list_jobs():
            if job.job_id == job_id:
                return job
        return None

    def put(self, job: HostJob) -> HostJob:
        jobs = self.list_jobs()
        updated = False
        for index, existing in enumerate(jobs):
            if existing.job_id == job.job_id:
                job = _merge_job(existing, job)
                jobs[index] = job
                updated = True
                break
        if not updated:
            jobs.append(job)
        payload = {
            "schema_version": 1,
            "jobs": [item.to_dict() for item in jobs],
            "updated_at": _now_iso(),
        }
        atomic_json_save(self._path, payload)
        self._save_job_authority(job)
        return job

    def append_event(self, job_id: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        append_task_event(self.job_dir(job_id), event_type, payload)

    def _list_jobs_from_dirs(self) -> list[HostJob]:
        if not self._jobs_dir.exists():
            return []
        jobs: list[HostJob] = []
        for item in sorted(self._jobs_dir.iterdir()):
            if not item.is_dir():
                continue
            host_job_path, steps_path, _tool_result_path = self._job_authority_paths(item.name)
            host_job_raw = load_json(host_job_path)
            steps_raw = load_json(steps_path)
            if not isinstance(host_job_raw, dict):
                continue
            job = HostJob.from_dict(host_job_raw)
            if isinstance(steps_raw, dict):
                raw_steps = steps_raw.get("steps")
                if isinstance(raw_steps, list):
                    job.steps = [HostJobStep.from_dict(step) for step in raw_steps if isinstance(step, dict)]
            jobs.append(job)
        return jobs

    def _save_job_authority(self, job: HostJob) -> None:
        host_job_path, steps_path, tool_result_path = self._job_authority_paths(job.job_id)
        host_job_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_save(
            host_job_path,
            {
                "job_id": job.job_id,
                "job_kind": job.job_kind,
                "source_task_id": job.source_task_id,
                "plan_id": job.plan_id,
                "repo": job.repo,
                "version": job.version,
                "tag": job.tag,
                "summary": job.summary,
                "state": job.state,
                "current_step_id": job.current_step_id,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
                "completed_at": job.completed_at,
                "last_error": job.last_error,
            },
        )
        atomic_json_save(
            steps_path,
            {
                "job_id": job.job_id,
                "steps": [step.to_dict() for step in job.steps],
                "updated_at": job.updated_at,
            },
        )
        current_step = next((step for step in job.steps if step.id == job.current_step_id), None)
        tool_result = {
            "job_id": job.job_id,
            "job_kind": job.job_kind,
            "source_task_id": job.source_task_id,
            "status": job.state,
            "current_step_id": job.current_step_id,
            "completed_at": job.completed_at,
            "last_error": job.last_error,
            "summary": job.summary,
            "exit_code": current_step.exit_code if current_step is not None else None,
            "stdout_path": current_step.stdout_path if current_step is not None else "",
            "stderr_path": current_step.stderr_path if current_step is not None else "",
        }
        atomic_json_save(tool_result_path, tool_result)


class HostJobRunner:
    """Durable bounded host-side job runner with append-only step authority."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths
        self._store = HostJobStore(paths)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._explicit_cancel: set[str] = set()

    @property
    def store(self) -> HostJobStore:
        return self._store

    def ensure_job(self, spec: HostJobSpec | HostJob) -> HostJob:
        job = spec.to_job() if isinstance(spec, HostJobSpec) else spec
        existing = self._store.get(job.job_id)
        if existing is not None:
            return existing
        return self._store.put(job)

    def get(self, job_id: str) -> HostJob | None:
        return self._store.get(job_id)

    def approve_step(self, job_id: str, step_id: str, *, approved_by: str) -> HostJob:
        job = self._require_job(job_id)
        if job.state in TERMINAL_HOST_JOB_STATES:
            return job
        step = self._require_step(job, step_id)
        if step.approval_required and step.state == "awaiting_approval":
            step.state = "pending"
            step.approved_at = _now_iso()
            step.approved_by = approved_by
            job.state = _sticky_transition(job.state, "running")
            self._store.append_event(
                job.job_id,
                "host_job.step.approved",
                {"step_id": step_id, "approved_by": approved_by},
            )
        job.updated_at = _now_iso()
        self._store.put(job)
        return job

    def start(self, job_id: str) -> HostJob:
        job = self._require_job(job_id)
        if job.state in TERMINAL_HOST_JOB_STATES:
            return job
        if job_id not in self._tasks or self._tasks[job_id].done():
            self._tasks[job_id] = asyncio.create_task(self._advance_job(job_id), name=f"host-job:{job_id}")
        return job

    async def cancel(self, job_id: str) -> HostJob:
        job = self._require_job(job_id)
        if job.state in TERMINAL_HOST_JOB_STATES:
            return job
        self._explicit_cancel.add(job_id)
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._explicit_cancel.discard(job_id)
        step = next((item for item in job.steps if item.id == job.current_step_id), None)
        if step is not None and step.state == "running":
            step.state = "cancelled"
            step.finished_at = _now_iso()
            step.completed_at = _now_iso()
            step.detail = "cancelled"
        job.state = _sticky_transition(job.state, "cancelled")
        job.completed_at = _now_iso()
        job.updated_at = _now_iso()
        self._store.append_event(job.job_id, "host_job.cancelled", {"current_step_id": job.current_step_id})
        return self._store.put(job)

    async def shutdown(self, *, cancel_running: bool = False) -> None:
        tasks = list(self._tasks.items())
        if cancel_running:
            for job_id, task in tasks:
                self._explicit_cancel.add(job_id)
                task.cancel()
            if tasks:
                await asyncio.gather(*(task for _job_id, task in tasks), return_exceptions=True)
            self._explicit_cancel.clear()
        self._tasks.clear()

    def reconcile_all(self) -> int:
        changed = 0
        for job in self._store.list_jobs():
            if self.reconcile_job(job.job_id):
                changed += 1
        return changed

    def reconcile_job(self, job_id: str) -> bool:
        job = self._store.get(job_id)
        if job is None or job.state in TERMINAL_HOST_JOB_STATES:
            return False
        if job.state == "pending" and (job_id not in self._tasks or self._tasks[job_id].done()):
            self.start(job_id)
            return True
        step = next((item for item in job.steps if item.id == job.current_step_id), None)
        if job.state != "running" or step is None:
            return False
        if _pid_alive(step.pid):
            return False
        exit_code_path = self._store.exit_code_path(job.job_id, step.id)
        if not exit_code_path.is_file():
            return False
        try:
            exit_code = int(exit_code_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        step.exit_code = exit_code
        step.finished_at = _now_iso()
        step.completed_at = step.finished_at
        if exit_code == 0:
            step.state = "completed"
            step.detail = "completed"
            job.last_error = ""
        else:
            step.state = "failed"
            step.detail = f"exit={exit_code}"
            job.last_error = f"step {step.id} failed with exit code {exit_code}"
        job.updated_at = _now_iso()
        self._store.append_event(
            job.job_id,
            "host_job.step.reconciled",
            {"step_id": step.id, "exit_code": exit_code},
        )
        self._store.put(job)
        self._finalize_job(job)
        return True

    async def _advance_job(self, job_id: str) -> None:
        while True:
            job = self._require_job(job_id)
            if job.state in TERMINAL_HOST_JOB_STATES:
                return
            next_step = self._next_runnable_step(job)
            if next_step is None:
                self._finalize_job(job)
                return
            if next_step.approval_required and next_step.approved_at == "":
                next_step.state = "awaiting_approval"
                job.state = _sticky_transition(job.state, "awaiting_approval")
                job.current_step_id = next_step.id
                job.updated_at = _now_iso()
                self._store.append_event(
                    job.job_id,
                    "host_job.step.awaiting_approval",
                    {"step_id": next_step.id},
                )
                self._store.put(job)
                return
            await self._execute_step(job, next_step)
            if next_step.state == "failed":
                return

    async def _execute_step(self, job: HostJob, step: HostJobStep) -> None:
        artifacts_dir = self._store._artifacts_dir(job.job_id, step.id)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = self._store.stdout_path(job.job_id, step.id)
        stderr_path = self._store.stderr_path(job.job_id, step.id)
        exit_code_path = self._store.exit_code_path(job.job_id, step.id)
        step.stdout_path = str(stdout_path)
        step.stderr_path = str(stderr_path)
        step.cwd = step.cwd or job.repo
        step.command_digest = step.command_digest or _command_digest(step.command)
        step.state = "running"
        step.started_at = _now_iso()
        job.state = _sticky_transition(job.state, "running")
        job.current_step_id = step.id
        job.updated_at = _now_iso()
        self._store.append_event(
            job.job_id,
            "host_job.step.started",
            {"step_id": step.id, "command": step.command},
        )
        self._store.put(job)

        stdout_handle = stdout_path.open("wb")
        stderr_handle = stderr_path.open("wb")
        proc: asyncio.subprocess.Process | None = None
        wrapped_command = (
            "{ "
            + step.command
            + "; }; rc=$?; printf '%s\\n' \"$rc\" > "
            + shlex.quote(str(exit_code_path))
            + '; exit "$rc"'
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-lc",
                wrapped_command,
                cwd=step.cwd or job.repo or None,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
                creationflags=_CREATION_FLAGS,
            )
            step.pid = proc.pid
            try:
                step.pgid = os.getpgid(proc.pid)
            except OSError:
                step.pgid = None
            job.updated_at = _now_iso()
            self._store.put(job)
            rc = await proc.wait()
        except asyncio.CancelledError:
            if job.job_id in self._explicit_cancel and proc is not None and proc.pid:
                force_kill_process_tree(proc.pid)
                with contextlib.suppress(Exception):
                    await proc.wait()
            raise
        finally:
            stdout_handle.close()
            stderr_handle.close()

        step.exit_code = rc
        step.finished_at = _now_iso()
        step.completed_at = _now_iso()
        with contextlib.suppress(OSError):
            exit_code_path.write_text(f"{rc}\n", encoding="utf-8")
        if rc == 0:
            step.state = "completed"
            step.detail = "completed"
            job.last_error = ""
            self._store.append_event(
                job.job_id,
                "host_job.step.completed",
                {"step_id": step.id, "exit_code": rc},
            )
        else:
            step.state = "failed"
            step.detail = f"exit={rc}"
            job.state = _sticky_transition(job.state, "failed")
            job.last_error = f"step {step.id} failed with exit code {rc}"
            job.completed_at = _now_iso()
            self._store.append_event(
                job.job_id,
                "host_job.step.failed",
                {"step_id": step.id, "exit_code": rc},
            )
        job.updated_at = _now_iso()
        self._store.put(job)
        self._finalize_job(job)

    def _finalize_job(self, job: HostJob) -> None:
        if job.state in TERMINAL_HOST_JOB_STATES:
            job.updated_at = _now_iso()
            self._store.put(job)
            return
        if any(step.state == "failed" for step in job.steps):
            job.state = _sticky_transition(job.state, "failed")
        elif any(step.state == "cancelled" for step in job.steps):
            job.state = _sticky_transition(job.state, "cancelled")
        elif any(step.state in {"pending", "awaiting_approval", "running"} for step in job.steps):
            return
        else:
            job.state = _sticky_transition(job.state, "completed")
        if not job.completed_at and job.state in {"completed", "failed", "cancelled"}:
            job.completed_at = _now_iso()
            self._store.append_event(
                job.job_id,
                "host_job.completed"
                if job.state == "completed"
                else "host_job.failed"
                if job.state == "failed"
                else "host_job.cancelled",
                {"current_step_id": job.current_step_id},
            )
        job.updated_at = _now_iso()
        self._store.put(job)

    @staticmethod
    def _next_runnable_step(job: HostJob) -> HostJobStep | None:
        for step in job.steps:
            if step.state in {"failed", "cancelled", "completed", "skipped"}:
                continue
            return step
        return None

    def _require_job(self, job_id: str) -> HostJob:
        job = self._store.get(job_id)
        if job is None:
            msg = f"Host job '{job_id}' not found"
            raise ValueError(msg)
        return job

    @staticmethod
    def _require_step(job: HostJob, step_id: str) -> HostJobStep:
        for step in job.steps:
            if step.id == step_id:
                return step
        msg = f"Host job '{job.job_id}' step '{step_id}' not found"
        raise ValueError(msg)
