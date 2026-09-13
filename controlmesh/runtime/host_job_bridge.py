"""External-controller bridge over the durable host-job substrate.

A non-model supervisor (for example an external coding CLI running outside the
ControlMesh process) needs three things for one delegated attempt:

1. submit one attempt and keep exactly one durable record of it, exactly once,
   even when two OS processes race on the same cold attempt id;
2. wait for that attempt to reach a terminal state without re-executing it;
3. retrieve one terminal event for that attempt at most once.

All three build on existing ControlMesh owners — :class:`HostJobRunner` owns durable
execution authority (sticky terminal states, per-step exit codes, restart reconciliation),
:class:`AgentInboxStore` owns once-only delivery to a named parent agent, and
``HostJobStore.lock`` owns durable per-job ownership (POSIX flock). This module adds
the missing pieces only: an explicit persisted parent/command/workspace binding, a
dispatch-intent record, a wait/long-poll, atomic consumption, and an explicit
"uncertain, needs review" outcome instead of inferred resource release.

Scope: this is a **local controller CLI bridge**. ``run`` always issues an explicit
``local_foreground``/terminal execution context; it is not authenticated remote task
ingress and not native session adoption.

Delivery semantics are **at-most-once**: consumption marks the single inbox item
consumed before returning, so a crash between the mark and the return loses the event
rather than duplicating it. Nothing here is guaranteed delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from controlmesh.bus.envelope import ExecutionContext, Origin, SourceScope
from controlmesh.execution_policy import enforce_execution_policy
from controlmesh.infra.json_store import atomic_json_save
from controlmesh.runtime.agent_inbox import AgentInboxStore
from controlmesh.runtime.host_jobs import (
    TERMINAL_HOST_JOB_STATES,
    HostJob,
    HostJobRunner,
    HostJobSpec,
    HostJobStep,
    default_single_step,
)
from controlmesh.runtime.models import AgentInboxItem
from controlmesh.workspace.paths import ControlMeshPaths

TERMINAL_EVENT_SCHEMA = "controlmesh.host_job.terminal_event.v1"
REVIEW_STATUS_SCHEMA = "controlmesh.host_job.review_status.v1"
DISPATCH_INTENT_SCHEMA = "controlmesh.host_job.dispatch.v1"
DEFAULT_JOB_KIND = "external_cli"
DEFAULT_STEP_ID = "external_cli"
DEFAULT_STEP_TITLE = "Run external CLI attempt"
DEFAULT_POLL_INTERVAL_SECONDS = 0.25

OUTCOME_TERMINAL = "terminal"
OUTCOME_NEEDS_REVIEW = "needs_review"

REVIEW_UNKNOWN_PROCESS = "worker_process_state_unknown"
REVIEW_WRAPPER_GONE = "worker_wrapper_gone_children_unknown"
REVIEW_DISPATCHER_LOST = "dispatcher_lost_before_worker_start"
REVIEW_UNCONFIRMED_TERMINAL = "terminal_without_confirmed_completion_evidence"

QUIESCENCE_UNKNOWN = "unknown"
QUIESCENCE_CONFIRMED = "confirmed"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_BINDING_FIELDS = (
    "parent_agent",
    "command_digest",
    "job_kind",
    "step_id",
    "step_title",
    "repo",
    "cwd",
    "plan_id",
    "source_task_id",
    "approval_required",
    "side_effect",
)
_INTENT_REQUIRED_STR = ("job_id", "parent_agent", "command_digest", "job_kind", "step_id", "step_title")
_INTENT_OPTIONAL_STR = ("repo", "cwd", "plan_id", "source_task_id")
_INTENT_BOOL_FIELDS = ("approval_required", "side_effect", "dispatched")

PROCESS_ALIVE = "alive"
PROCESS_DEAD = "dead"
PROCESS_UNKNOWN = "unknown"


class HostJobBridgeError(RuntimeError):
    """Base error for external-controller bridge rejections."""


class AttemptBindingError(HostJobBridgeError):
    """The attempt id is already bound to a different approved definition."""


class UncertainDispatchError(HostJobBridgeError):
    """A previous dispatch may have started the worker; re-execution is refused."""


class DispatchIntentError(HostJobBridgeError):
    """The persisted dispatch intent is missing, corrupt or invalid for existing evidence."""


def external_tool_use_id(job_id: str) -> str:
    """Stable once-only delivery key for one external attempt."""
    return f"toolu_{job_id}"


def external_tool_result_path(paths: ControlMeshPaths, job_id: str) -> Path:
    return paths.runtime_host_jobs_dir / job_id / "TOOL_RESULT.json"


def _intent_path(paths: ControlMeshPaths, job_id: str) -> Path:
    return paths.runtime_host_jobs_dir / job_id / "DISPATCH.json"


def _validate_identifier(value: str, field: str) -> str:
    """Reject anything that is not a flat, path-safe identifier."""
    text = str(value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(text):
        msg = f"invalid {field} {value!r}: expected [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}"
        raise ValueError(msg)
    return text


def _command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _current_step(job: HostJob) -> HostJobStep | None:
    for step in job.steps:
        if step.id == job.current_step_id:
            return step
    return job.steps[-1] if job.steps else None


def process_state(pid: int | None) -> str:
    """Return ``alive``, ``dead`` or ``unknown`` for one recorded worker pid.

    ``unknown`` is explicit and never treated as termination: a missing pid or an
    ``EPERM`` probe means the worker's fate cannot be confirmed, so no resource is
    released and the attempt is flagged for review instead.
    """
    if not isinstance(pid, int) or pid <= 0:
        return PROCESS_UNKNOWN
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return PROCESS_DEAD
    except PermissionError:
        return PROCESS_UNKNOWN
    except OSError:
        return PROCESS_UNKNOWN
    return PROCESS_ALIVE


def terminal_event_payload(paths: ControlMeshPaths, job: HostJob) -> dict[str, Any]:
    """Project one terminal host job into the parent-facing terminal event."""
    step = _current_step(job)
    return {
        "schema_version": TERMINAL_EVENT_SCHEMA,
        "job_id": job.job_id,
        "job_kind": job.job_kind,
        "source_task_id": job.source_task_id,
        "plan_id": job.plan_id,
        "state": job.state,
        "step_id": step.id if step is not None else "",
        "exit_code": step.exit_code if step is not None else None,
        "stdout_path": step.stdout_path if step is not None else "",
        "stderr_path": step.stderr_path if step is not None else "",
        "completed_at": job.completed_at,
        "last_error": job.last_error,
        "summary": job.summary,
        "tool_use_id": external_tool_use_id(job.job_id),
        "tool_result_path": str(external_tool_result_path(paths, job.job_id)),
        "requires_attention": job.state != "completed",
    }


# ---------------------------------------------------------------------------
# Dispatch intent: persisted binding + dispatch decision (lock-protected)
# ---------------------------------------------------------------------------


def _binding(
    *,
    job_id: str,
    parent_agent: str,
    command: str,
    job_kind: str,
    step_id: str,
    step_title: str,
    repo: str,
    cwd: str,
    plan_id: str,
    source_task_id: str,
    approval_required: bool,
    side_effect: bool,
) -> dict[str, Any]:
    """The approved attempt definition: parent, command, workspace and provenance."""
    return {
        "schema_version": DISPATCH_INTENT_SCHEMA,
        "job_id": job_id,
        "parent_agent": parent_agent,
        "command_digest": _command_digest(command),
        "job_kind": job_kind,
        "step_id": step_id,
        "step_title": step_title,
        "repo": repo,
        "cwd": cwd,
        "plan_id": plan_id,
        "source_task_id": source_task_id,
        "approval_required": bool(approval_required),
        "side_effect": bool(side_effect),
    }


def _intent_state(paths: ControlMeshPaths, job_id: str) -> tuple[str, dict[str, Any] | None]:
    """Load the dispatch intent as ``(state, intent)``.

    ``state`` is ``ok``, ``missing``, ``corrupt`` (unreadable or not JSON) or
    ``invalid`` (JSON present but schema, id or field types are wrong). Missing and
    corrupt are never the same thing: only a missing intent with no other evidence may
    be created, and corrupt evidence is never overwritten.
    """
    path = _intent_path(paths, job_id)
    if not path.is_file():
        return "missing", None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "corrupt", None
    if not isinstance(raw, dict):
        return "corrupt", None
    if str(raw.get("schema_version") or "") != DISPATCH_INTENT_SCHEMA:
        return "invalid", None
    if str(raw.get("job_id") or "") != job_id:
        return "invalid", None
    for field in _INTENT_REQUIRED_STR:
        if not isinstance(raw.get(field), str) or not str(raw.get(field) or "").strip():
            return "invalid", None
    for field in _INTENT_OPTIONAL_STR:
        if not isinstance(raw.get(field), str):
            return "invalid", None
    for field in _INTENT_BOOL_FIELDS:
        if not isinstance(raw.get(field), bool):
            return "invalid", None
    return "ok", raw


def _read_intent_locked(paths: ControlMeshPaths, job_id: str) -> dict[str, Any] | None:
    """Return the intent only when it is present and valid (else ``None``)."""
    state, intent = _intent_state(paths, job_id)
    return intent if state == "ok" else None


def _write_intent_locked(paths: ControlMeshPaths, intent: dict[str, Any]) -> None:
    path = _intent_path(paths, job_id_for_intent(intent))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_save(path, intent)


def job_id_for_intent(intent: dict[str, Any]) -> str:
    return str(intent.get("job_id") or "")


def _binding_mismatch(intent: dict[str, Any], binding: dict[str, Any]) -> str:
    for field in _BINDING_FIELDS:
        if intent.get(field) != binding.get(field):
            return field
    return ""


def read_dispatch_intent(paths: ControlMeshPaths, *, job_id: str) -> dict[str, Any] | None:
    """Return the persisted dispatch intent for one attempt (read-only)."""
    _validate_identifier(job_id, "job_id")
    runner = HostJobRunner(paths)
    with runner.store.lock(job_id):
        return _read_intent_locked(paths, job_id)


def _require_bound_parent_locked(
    paths: ControlMeshPaths,
    job_id: str,
    parent_agent: str,
) -> dict[str, Any]:
    state, intent = _intent_state(paths, job_id)
    if state != "ok" or intent is None:
        msg = f"attempt '{job_id}' has a {state} dispatch intent; refusing parent binding"
        raise DispatchIntentError(msg)
    bound = str(intent.get("parent_agent") or "")
    if bound != parent_agent:
        msg = (
            f"attempt '{job_id}' is bound to parent '{bound}', not '{parent_agent}'; "
            "a second delivery target is refused"
        )
        raise AttemptBindingError(msg)
    return intent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_attempt(
    paths: ControlMeshPaths,
    *,
    job_id: str,
    command: str,
    parent_agent: str,
    job_kind: str = DEFAULT_JOB_KIND,
    plan_id: str = "",
    source_task_id: str = "",
    repo: str = "",
    summary: str = "",
    step_id: str = DEFAULT_STEP_ID,
    step_title: str = DEFAULT_STEP_TITLE,
    approval_required: bool = False,
    side_effect: bool = False,
    cwd: str = "",
    timeout_seconds: float | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any] | None:
    """Ensure, start and wait for one external attempt.

    The first call with a given ``job_id`` persists the approved attempt definition
    (parent, command digest, workspace, kind, step, plan/source provenance,
    approval/side-effect flags) and dispatches the worker. Later calls with the same id
    never re-execute: they return the existing terminal event, and a changed definition
    is rejected instead of returning an unrelated receipt.

    Start is serialized by the durable per-job OS lock and the persisted dispatch intent
    records that a dispatch happened, so uncontended or cooperating concurrent callers
    produce one execution. This is **not** exactly-once under crashes: an intent that was
    written but never marked dispatched is *uncertain* and raises
    :class:`UncertainDispatchError`, because the previous process may have spawned the
    worker and no automatic replay is authorized.

    An existing job or artifact history without a valid binding is never implicitly
    claimed: missing/corrupt/invalid intents fail closed with
    :class:`DispatchIntentError` and leave the evidence untouched.

    When ``timeout_seconds`` elapses first the attempt is detached: the worker keeps
    running in its own session and the durable job record stays authoritative.
    """
    job_id = _validate_identifier(job_id, "job_id")
    parent_agent = _validate_identifier(parent_agent, "parent_agent")
    step_id = _validate_identifier(step_id, "step_id")
    enforce_execution_policy(
        ExecutionContext.issue(
            origin=Origin.USER,
            source_scope=SourceScope.LOCAL_FOREGROUND,
            transport="terminal",
            source_id=job_id,
        ),
        sandbox_available=False,
    )

    runner = HostJobRunner(paths)
    repo_root = repo or str(paths.framework_root)
    binding = _binding(
        job_id=job_id,
        parent_agent=parent_agent,
        command=command,
        job_kind=job_kind,
        step_id=step_id,
        step_title=step_title,
        repo=repo_root,
        cwd=cwd or repo_root,
        plan_id=plan_id,
        source_task_id=source_task_id,
        approval_required=approval_required,
        side_effect=side_effect,
    )

    with runner.store.lock(job_id):
        state, intent = _intent_state(paths, job_id)
        if state != "ok":
            if _has_attempt_evidence(paths, runner, job_id):
                raise DispatchIntentError(
                    f"attempt '{job_id}' has existing job evidence but a {state} dispatch "
                    "intent; refusing to rebind or adopt it without explicit review"
                )
            if state != "missing":
                raise DispatchIntentError(
                    f"attempt '{job_id}' has a {state} dispatch intent; refusing to "
                    "overwrite the evidence"
                )
        if intent is None:
            intent = {
                **binding,
                "summary": summary or command,
                "dispatched": False,
                "dispatch_outcome": "pending",
                "dispatch_pid": os.getpid(),
                "review_required": False,
                "review_reason": "",
                "execution_quiescence": "",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            _write_intent_locked(paths, intent)
            job = _ensure_job(
                runner,
                paths,
                job_id=job_id,
                command=command,
                job_kind=job_kind,
                plan_id=plan_id,
                source_task_id=source_task_id,
                repo=repo,
                summary=summary,
                step_id=step_id,
                step_title=step_title,
                approval_required=approval_required,
                side_effect=side_effect,
                cwd=cwd,
            )
            runner.start(job.job_id)
            intent["dispatched"] = True
            intent["dispatch_outcome"] = "dispatched"
            intent["updated_at"] = _now_iso()
            _write_intent_locked(paths, intent)
        else:
            mismatch = _binding_mismatch(intent, binding)
            if mismatch:
                msg = f"attempt '{job_id}' is already bound; '{mismatch}' differs from this request"
                raise AttemptBindingError(msg)
            if not intent.get("dispatched", False):
                raise UncertainDispatchError(
                    f"attempt '{job_id}' has an unconfirmed dispatch intent "
                    f"(pid={intent.get('dispatch_pid')}); refusing to re-execute"
                )

    event = await _wait_for_terminal(
        runner,
        paths,
        job_id=job_id,
        parent_agent=parent_agent,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    # A needs-review answer keeps the owner attached: no detach, no replay, no release.
    if event is None:
        await runner.detach(job_id)
    return event





def _ensure_job(
    runner: HostJobRunner,
    paths: ControlMeshPaths,
    *,
    job_id: str,
    command: str,
    job_kind: str,
    plan_id: str,
    source_task_id: str,
    repo: str,
    summary: str,
    step_id: str,
    step_title: str,
    approval_required: bool,
    side_effect: bool,
    cwd: str,
) -> HostJob:
    repo_root = repo or str(paths.framework_root)
    spec = HostJobSpec(
        job_id=job_id,
        job_kind=job_kind,
        source_task_id=source_task_id,
        plan_id=plan_id,
        repo=repo_root,
        summary=summary or command,
        steps=[
            default_single_step(
                step_id=step_id,
                title=step_title,
                command=command,
                approval_required=approval_required,
                side_effect=side_effect,
                cwd=cwd or repo_root,
            )
        ],
    )
    return runner.ensure_job(spec)


async def await_terminal_event(
    paths: ControlMeshPaths,
    *,
    job_id: str,
    parent_agent: str,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any] | None:
    """Wait for one terminal event, or return ``None`` while still running.

    The persisted parent binding is enforced: waiting under any other parent is
    rejected, so an arbitrary parent cannot create a second delivery target. This
    call never starts a job and never re-executes one.
    """
    job_id = _validate_identifier(job_id, "job_id")
    parent_agent = _validate_identifier(parent_agent, "parent_agent")
    runner = HostJobRunner(paths)
    with runner.store.lock(job_id):
        _require_bound_parent_locked(paths, job_id, parent_agent)
    return await _wait_for_terminal(
        runner,
        paths,
        job_id=job_id,
        parent_agent=parent_agent,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


async def _wait_for_terminal(
    runner: HostJobRunner,
    paths: ControlMeshPaths,
    *,
    job_id: str,
    parent_agent: str,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
) -> dict[str, Any] | None:
    inbox = AgentInboxStore(paths)
    interval = max(0.05, poll_interval_seconds)
    deadline = None if timeout_seconds is None else time.monotonic() + max(0.0, timeout_seconds)
    stall_grace = max(8 * interval, 2.0)
    pending_since: tuple[float, str] | None = None

    while True:
        with runner.store.lock(job_id):
            job = runner.get(job_id)
            if job is None:
                msg = f"Host job '{job_id}' not found"
                raise ValueError(msg)
            if job.state in {"running", "awaiting_approval"}:
                runner.reconcile_job(job_id)
                job = runner.get(job_id) or job

            # Terminal evidence always wins, so a later genuine completion is still
            # reconcilable after a needs-review answer.
            if job.state in TERMINAL_HOST_JOB_STATES:
                if _completion_confirmed(runner, job):
                    _clear_review_locked(paths, job_id)
                else:
                    _mark_review_locked(paths, job_id, REVIEW_UNCONFIRMED_TERMINAL)
                _enqueue_terminal_event(paths, inbox, job, parent_agent)
                return _terminal_result(paths, job_id, job)

            # A confirmed review state is answered immediately instead of blocking
            # forever; it never consumes a receipt and never launches again.
            intent = _read_intent_locked(paths, job_id)
            if intent is not None and intent.get("review_required", False):
                return _review_status(paths, job_id, job)

            outcome = "stalled" if job.state == "pending" and not _step_started(job) else _worker_outcome(runner, job)
            if outcome == "running":
                pending_since = None
            elif pending_since is None:
                # Require two observations: a running step briefly has no pid yet.
                pending_since = (time.monotonic(), outcome)
            else:
                elapsed = time.monotonic() - pending_since[0]
                grace = stall_grace if pending_since[1] == "stalled" else interval
                if elapsed >= grace:
                    if pending_since[1] == "vanished" and _finalize_vanished_worker(paths, runner, job):
                        continue
                    if pending_since[1] == "unknown":
                        _mark_review_locked(paths, job_id, REVIEW_UNKNOWN_PROCESS)
                    if pending_since[1] == "stalled":
                        _mark_review_locked(paths, job_id, REVIEW_DISPATCHER_LOST)
        if deadline is not None and time.monotonic() >= deadline:
            return None
        await asyncio.sleep(interval)


def consume_terminal_event(
    paths: ControlMeshPaths,
    *,
    job_id: str,
    parent_agent: str,
) -> dict[str, Any] | None:
    """Return the terminal event for one attempt at most once.

    Read, check and mark all happen inside the durable per-job OS lock, so two OS
    processes racing to consume produce exactly one winner. ``None`` means nothing
    is consumable: the attempt is not terminal yet, or its single event was already
    consumed by the bound parent. Delivery is at-most-once, not guaranteed: a crash
    between the mark and the return loses the event rather than duplicating it.
    """
    job_id = _validate_identifier(job_id, "job_id")
    parent_agent = _validate_identifier(parent_agent, "parent_agent")
    runner = HostJobRunner(paths)
    inbox = AgentInboxStore(paths)
    with runner.store.lock(job_id):
        _require_bound_parent_locked(paths, job_id, parent_agent)
        job = runner.get(job_id)
        if job is None or job.state not in TERMINAL_HOST_JOB_STATES:
            return None
        tool_use_id = external_tool_use_id(job_id)
        item = inbox.get(parent_agent, tool_use_id=tool_use_id)
        if item is None:
            item = _enqueue_terminal_event(paths, inbox, job, parent_agent)
        if item.status == "consumed":
            return None
        payload = _terminal_result(paths, job_id, job)
        inbox.mark_consumed(
            parent_agent,
            tool_use_id=tool_use_id,
            consumed_by=parent_agent,
            next_action="controller_review",
        )
        runner.store.append_event(
            job_id,
            "host_job.terminal_event.consumed_by_parent",
            {"parent_agent": parent_agent, "tool_use_id": tool_use_id, "state": job.state},
        )
        return payload


def read_attempt(paths: ControlMeshPaths, *, job_id: str) -> dict[str, Any] | None:
    """Return the current projection of one attempt plus dispatch/review metadata."""
    _validate_identifier(job_id, "job_id")
    runner = HostJobRunner(paths)
    with runner.store.lock(job_id):
        job = runner.get(job_id)
        if job is None:
            return None
        intent = _read_intent_locked(paths, job_id) or {}
        if job.state in TERMINAL_HOST_JOB_STATES:
            payload = _terminal_result(paths, job_id, job)
        elif intent.get("review_required", False):
            payload = _review_status(paths, job_id, job)
        else:
            payload = _with_intent_metadata(paths, job_id, terminal_event_payload(paths, job))
            payload["schema_version"] = "controlmesh.host_job.status.v1"
            payload["outcome"] = "status"
            payload["terminal"] = False
    payload["parent_agent"] = str(intent.get("parent_agent") or "")
    payload["dispatched"] = bool(intent.get("dispatched", False))
    payload["dispatch_outcome"] = str(intent.get("dispatch_outcome") or "")
    return payload


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _has_attempt_evidence(paths: ControlMeshPaths, runner: HostJobRunner, job_id: str) -> bool:
    """True when any durable job record or artifact directory already exists."""
    if runner.get(job_id) is not None:
        return True
    return any(
        (root / job_id).exists()
        for root in (paths.runtime_host_jobs_dir, paths.runtime_host_job_artifacts_dir)
    )


def _step_started(job: HostJob) -> bool:
    return any(
        step.state != "pending" or step.pid is not None or bool(step.started_at) for step in job.steps
    )


def _completion_confirmed(runner: HostJobRunner, job: HostJob) -> bool:
    """True only when the worker itself recorded completion evidence (an exit code)."""
    step = _current_step(job)
    if step is None:
        return False
    if step.exit_code is not None:
        return True
    return runner.store.exit_code_path(job.job_id, step.id).is_file()


def _terminal_result(paths: ControlMeshPaths, job_id: str, job: HostJob) -> dict[str, Any]:
    """Terminal event with retained review/quiescence metadata. Caller holds the lock."""
    payload = terminal_event_payload(paths, job)
    payload["outcome"] = OUTCOME_TERMINAL
    payload["terminal"] = True
    return _with_intent_metadata(paths, job_id, payload)


def _review_status(paths: ControlMeshPaths, job_id: str, job: HostJob) -> dict[str, Any]:
    """Structured needs-review answer: not a terminal event, not a receipt, no replay."""
    payload = terminal_event_payload(paths, job)
    payload["schema_version"] = REVIEW_STATUS_SCHEMA
    payload["outcome"] = OUTCOME_NEEDS_REVIEW
    payload["terminal"] = False
    payload["consumed"] = False
    payload["replay_authorized"] = False
    payload = _with_intent_metadata(paths, job_id, payload)
    payload["review_required"] = True
    return payload


def _with_intent_metadata(paths: ControlMeshPaths, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    intent = _read_intent_locked(paths, job_id) or {}
    payload["review_required"] = bool(intent.get("review_required", False))
    payload["review_reason"] = str(intent.get("review_reason") or "")
    payload["execution_quiescence"] = str(intent.get("execution_quiescence") or "")
    return payload


def _worker_outcome(runner: HostJobRunner, job: HostJob) -> str:
    """``running``, ``vanished`` (confirmed dead, no exit code) or ``unknown``."""
    step = _current_step(job)
    if job.state != "running" or step is None or step.state != "running":
        return "running"
    if runner.store.exit_code_path(job.job_id, step.id).is_file():
        return "running"
    pid_state = process_state(step.pid)
    if pid_state == PROCESS_DEAD:
        return "vanished"
    if pid_state == PROCESS_UNKNOWN:
        return "unknown"
    return "running"


def _finalize_vanished_worker(paths: ControlMeshPaths, runner: HostJobRunner, job: HostJob) -> bool:
    """Record a confirmed-dead worker wrapper as failed, with quiescence unknown.

    ``HostJobRunner.reconcile_job`` only recovers jobs that wrote an exit code, so a
    hard-killed worker would otherwise stay ``running`` forever. The wrapper being gone
    does **not** prove its spawned CLI and children stopped: the terminal state is
    recorded so the attempt stops waiting, while ``review_required`` and
    ``execution_quiescence=unknown`` are retained and no replay or resource release is
    authorized. Caller must hold the job lock.
    """
    step = _current_step(job)
    if job.state != "running" or step is None or step.state != "running":
        return False
    if runner.store.exit_code_path(job.job_id, step.id).is_file():
        return False
    if process_state(step.pid) != PROCESS_DEAD:
        return False
    step.state = "failed"
    step.detail = "worker wrapper disappeared without an exit code; children unverified"
    step.finished_at = _now_iso()
    step.completed_at = step.finished_at
    job.state = "failed"
    job.last_error = (
        f"step {step.id} worker wrapper disappeared (pid={step.pid}); "
        "execution quiescence unknown, review required"
    )
    job.completed_at = _now_iso()
    job.updated_at = job.completed_at
    runner.store.append_event(
        job.job_id,
        "host_job.step.vanished",
        {"step_id": step.id, "pid": step.pid, "quiescence": QUIESCENCE_UNKNOWN},
    )
    runner.store.put(job)
    _mark_quiescence_locked(paths, job.job_id, QUIESCENCE_UNKNOWN)
    _mark_review_locked(paths, job.job_id, REVIEW_WRAPPER_GONE)
    return True


def _mark_review_locked(paths: ControlMeshPaths, job_id: str, reason: str) -> None:
    """Persist an explicit uncertain outcome for human review. Caller holds the lock."""
    intent = _read_intent_locked(paths, job_id)
    if intent is None:
        return
    # Keep the first (most specific) reason: never downgrade an existing finding.
    if intent.get("review_required") and intent.get("review_reason"):
        return
    intent["review_required"] = True
    intent["review_reason"] = reason
    intent["updated_at"] = _now_iso()
    _write_intent_locked(paths, intent)


def _mark_quiescence_locked(paths: ControlMeshPaths, job_id: str, quiescence: str) -> None:
    intent = _read_intent_locked(paths, job_id)
    if intent is None or intent.get("execution_quiescence") == quiescence:
        return
    intent["execution_quiescence"] = quiescence
    intent["updated_at"] = _now_iso()
    _write_intent_locked(paths, intent)


def _clear_review_locked(paths: ControlMeshPaths, job_id: str) -> None:
    """Clear review once worker-written completion evidence exists (exit code)."""
    intent = _read_intent_locked(paths, job_id)
    if intent is None:
        return
    if not intent.get("review_required", False) and intent.get("execution_quiescence") == QUIESCENCE_CONFIRMED:
        return
    intent["review_required"] = False
    intent["review_reason"] = ""
    intent["execution_quiescence"] = QUIESCENCE_CONFIRMED
    intent["updated_at"] = _now_iso()
    _write_intent_locked(paths, intent)


def _enqueue_terminal_event(
    paths: ControlMeshPaths,
    inbox: AgentInboxStore,
    job: HostJob,
    parent_agent: str,
) -> AgentInboxItem:
    """Append the single terminal inbox item for one attempt (idempotent)."""
    tool_use_id = external_tool_use_id(job.job_id)
    existing = inbox.get(parent_agent, tool_use_id=tool_use_id)
    if existing is not None:
        return existing
    payload = terminal_event_payload(paths, job)
    summary = job.last_error or job.summary or f"{job.job_id} {job.state}"
    return inbox.append(
        AgentInboxItem(
            to_agent=parent_agent,
            kind=f"host_job.{job.state}",
            summary=summary[:1200],
            task_id=job.source_task_id,
            tool_use_id=tool_use_id,
            tool_result_ref=f"host_job://{job.job_id}/TOOL_RESULT.json",
            projection=summary[:1200],
            status="pending",
            from_task=job.source_task_id,
            source_agent="host_job_bridge",
            result_ref=f"host_job:{job.job_id}/result",
            requires_attention=job.state != "completed",
            payload=payload,
        )
    )
