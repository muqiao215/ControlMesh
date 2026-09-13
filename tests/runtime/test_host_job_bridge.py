"""Isolated integration proof for the external-controller host-job bridge.

The fake worker is a real subprocess, and the concurrency tests use real OS
processes, so single dispatch, binding enforcement, atomic consumption and
uncertain-process handling are exercised across process boundaries.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from controlmesh.runtime import AgentInboxStore, HostJobRunner
from controlmesh.runtime.host_job_bridge import (
    OUTCOME_NEEDS_REVIEW,
    OUTCOME_TERMINAL,
    REVIEW_DISPATCHER_LOST,
    REVIEW_UNKNOWN_PROCESS,
    REVIEW_WRAPPER_GONE,
    AttemptBindingError,
    DispatchIntentError,
    UncertainDispatchError,
    await_terminal_event,
    consume_terminal_event,
    external_tool_use_id,
    process_state,
    read_attempt,
    read_dispatch_intent,
    run_attempt,
)
from controlmesh.runtime.host_jobs import HostJob, HostJobStep
from controlmesh.workspace.paths import ControlMeshPaths

PARENT = "codex-external-controller"
REPO_ROOT = Path(__file__).resolve().parents[2]

_WORKER_SCRIPT = """
import asyncio, sys, time
from pathlib import Path
sys.path.insert(0, __REPO__)
from controlmesh.workspace.paths import ControlMeshPaths
from controlmesh.runtime.host_job_bridge import consume_terminal_event, run_attempt

mode, home, job_id, parent, command, start_at = sys.argv[1:7]
paths = ControlMeshPaths(
    controlmesh_home=Path(home),
    home_defaults=Path("/opt/controlmesh/workspace"),
    framework_root=Path(home).parent / "repo",
)
while time.time() < float(start_at):
    time.sleep(0.01)
# Record the real arrival time so the test can prove the processes really raced.
with open(str(Path(home).parent / "arrivals.log"), "a", encoding="utf-8") as handle:
    handle.write(f"{time.time():.3f}\\n")
if mode == "run":
    event = asyncio.run(
        run_attempt(paths, job_id=job_id, command=command, parent_agent=parent, timeout_seconds=60)
    )
else:
    event = consume_terminal_event(paths, job_id=job_id, parent_agent=parent)
print("EVENT" if event else "NONE")
"""


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=tmp_path / "repo",
    )


def _write_worker(tmp_path: Path, body: str, *, name: str = "fake_worker.sh") -> str:
    script = tmp_path / name
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def _fake_worker(tmp_path: Path, *, exit_code: int = 0) -> str:
    """Fake worker that records each execution and exits with ``exit_code``."""
    runs = tmp_path / "runs.txt"
    return _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {runs}\n"
        "echo 'fake worker output'\n"
        f"exit {exit_code}\n",
    )


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _run_count(tmp_path: Path) -> int:
    path = tmp_path / "runs.txt"
    if not path.is_file():
        return 0
    return len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])


def _spawn_bridge(
    tmp_path: Path,
    *,
    mode: str,
    job_id: str,
    parent: str,
    command: str = "",
    count: int = 4,
) -> list[tuple[int, str]]:
    """Start `count` real OS processes that hit the bridge at the same instant."""
    script = tmp_path / "bridge_proc.py"
    script.write_text(_WORKER_SCRIPT.replace("__REPO__", repr(str(REPO_ROOT))), encoding="utf-8")
    home = str(tmp_path / ".controlmesh")
    start_at = str(time.time() + 1.5)
    procs = [
        subprocess.Popen(
            [sys.executable, str(script), mode, home, job_id, parent, command, start_at],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(count)
    ]
    results: list[tuple[int, str]] = []
    for proc in procs:
        out, err = proc.communicate(timeout=180)
        results.append((proc.returncode, out.strip() or err.strip()))
    return results


# ---------------------------------------------------------------------------
# Core contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_attempt_completes_once_and_parent_consumes_once(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)

    event = await run_attempt(
        paths, job_id="ext-attempt-1", command=command, parent_agent=PARENT, timeout_seconds=15.0
    )

    assert event is not None
    assert event["state"] == "completed"
    assert event["exit_code"] == 0
    assert event["job_id"] == "ext-attempt-1"
    assert event["tool_use_id"] == external_tool_use_id("ext-attempt-1")
    assert _run_count(tmp_path) == 1

    tool_result = json.loads(_read(event["tool_result_path"]))
    assert tool_result["status"] == "completed"
    assert tool_result["exit_code"] == 0

    # The binding is persisted with the attempt.
    intent = read_dispatch_intent(paths, job_id="ext-attempt-1")
    assert intent is not None
    assert intent["parent_agent"] == PARENT
    assert intent["dispatched"] is True
    assert intent["dispatch_outcome"] == "dispatched"

    # A healthy completion is not flagged for review (the pre-pid window is transient).
    status = read_attempt(paths, job_id="ext-attempt-1")
    assert status is not None
    assert status["review_required"] is False
    assert status["review_reason"] == ""

    # Exactly one inbox item exists for the bound parent.
    inbox = AgentInboxStore(paths)
    items = [item for item in inbox.read_recent(PARENT, limit=20) if item.tool_use_id == event["tool_use_id"]]
    assert len(items) == 1
    assert items[0].status == "pending"

    assert consume_terminal_event(paths, job_id="ext-attempt-1", parent_agent=PARENT) == event
    after = [item for item in inbox.read_recent(PARENT, limit=20) if item.tool_use_id == event["tool_use_id"]]
    assert after[0].status == "consumed"
    assert after[0].consumed_by == PARENT

    # A second consume returns nothing: one terminal event per attempt.
    assert consume_terminal_event(paths, job_id="ext-attempt-1", parent_agent=PARENT) is None

    # An unbound parent is refused and never becomes a second delivery target.
    with pytest.raises(AttemptBindingError, match="bound to parent"):
        consume_terminal_event(paths, job_id="ext-attempt-1", parent_agent="other-controller")
    assert AgentInboxStore(paths).read_recent("other-controller", limit=20) == []


@pytest.mark.asyncio
async def test_duplicate_wake_does_not_reexecute_completed_attempt(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)

    first = await run_attempt(
        paths, job_id="ext-attempt-2", command=command, parent_agent=PARENT, timeout_seconds=15.0
    )
    assert first is not None
    assert first["state"] == "completed"
    assert _run_count(tmp_path) == 1

    second = await run_attempt(
        paths, job_id="ext-attempt-2", command=command, parent_agent=PARENT, timeout_seconds=15.0
    )
    assert second == first
    assert _run_count(tmp_path) == 1

    polled = await await_terminal_event(paths, job_id="ext-attempt-2", parent_agent=PARENT, timeout_seconds=5.0)
    assert polled == first
    assert _run_count(tmp_path) == 1

    inbox = AgentInboxStore(paths)
    items = [item for item in inbox.read_recent(PARENT, limit=20) if item.tool_use_id == first["tool_use_id"]]
    assert len(items) == 1

    assert consume_terminal_event(paths, job_id="ext-attempt-2", parent_agent=PARENT) is not None
    assert consume_terminal_event(paths, job_id="ext-attempt-2", parent_agent=PARENT) is None


@pytest.mark.asyncio
async def test_failed_worker_exit_code_is_retained(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path, exit_code=3)

    event = await run_attempt(
        paths, job_id="ext-attempt-3", command=command, parent_agent=PARENT, timeout_seconds=15.0
    )

    assert event is not None
    assert event["state"] == "failed"
    assert event["exit_code"] == 3
    assert event["requires_attention"] is True
    assert "exit code 3" in event["last_error"]

    fresh = HostJobRunner(paths).get("ext-attempt-3")
    assert fresh is not None
    assert fresh.state == "failed"
    assert read_attempt(paths, job_id="ext-attempt-3") is not None
    assert consume_terminal_event(paths, job_id="ext-attempt-3", parent_agent=PARENT) is not None
    assert consume_terminal_event(paths, job_id="ext-attempt-3", parent_agent=PARENT) is None


# ---------------------------------------------------------------------------
# Fix 1: single dispatch under concurrent cold start / no re-execution
# ---------------------------------------------------------------------------


def test_concurrent_cold_start_executes_command_exactly_once(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)

    results = _spawn_bridge(tmp_path, mode="run", job_id="race-1", parent=PARENT, command=command, count=4)

    assert [code for code, _ in results] == [0, 0, 0, 0]
    assert [out for _, out in results] == ["EVENT"] * 4
    assert _run_count(tmp_path) == 1, f"cold start executed more than once: {results}"

    # Prove the processes actually overlapped instead of running one after another.
    arrivals = [float(line) for line in (tmp_path / "arrivals.log").read_text(encoding="utf-8").split()]
    assert len(arrivals) == 4
    assert max(arrivals) - min(arrivals) < 1.0, f"processes did not race: {arrivals}"

    event = read_attempt(paths, job_id="race-1")
    assert event is not None
    assert event["state"] == "completed"
    assert event["dispatch_outcome"] == "dispatched"
    assert event["review_required"] is False


@pytest.mark.asyncio
async def test_dispatch_crash_leaves_uncertain_intent_and_refuses_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    original = HostJobRunner.start
    calls = {"n": 0}

    def flaky_start(self: HostJobRunner, job_id: str) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            msg = "simulated crash during dispatch"
            raise RuntimeError(msg)
        return original(self, job_id)

    monkeypatch.setattr(HostJobRunner, "start", flaky_start)

    with pytest.raises(RuntimeError, match="simulated crash"):
        await run_attempt(paths, job_id="crash-1", command=command, parent_agent=PARENT, timeout_seconds=5.0)

    intent = read_dispatch_intent(paths, job_id="crash-1")
    assert intent is not None
    assert intent["dispatched"] is False

    # Reopening an uncertain attempt must never invoke runner.start again.
    with pytest.raises(UncertainDispatchError, match="unconfirmed dispatch intent"):
        await run_attempt(paths, job_id="crash-1", command=command, parent_agent=PARENT, timeout_seconds=5.0)
    assert calls["n"] == 1
    assert _run_count(tmp_path) == 0

    monkeypatch.undo()
    job = HostJobRunner(paths).get("crash-1")
    assert job is not None
    assert job.state == "pending"


# ---------------------------------------------------------------------------
# Fix 2: binding of job id to parent, command and workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_job_id_with_changed_command_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    first_command = _fake_worker(tmp_path)
    other = _write_worker(tmp_path, "#!/usr/bin/env bash\necho other\nexit 0\n", name="other.sh")

    await run_attempt(paths, job_id="bound-1", command=first_command, parent_agent=PARENT, timeout_seconds=15.0)
    assert _run_count(tmp_path) == 1

    with pytest.raises(AttemptBindingError, match="command_digest"):
        await run_attempt(paths, job_id="bound-1", command=other, parent_agent=PARENT, timeout_seconds=5.0)
    assert _run_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_same_job_id_with_changed_parent_or_workspace_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    (tmp_path / "other").mkdir(parents=True)
    command = _fake_worker(tmp_path)

    await run_attempt(paths, job_id="bound-2", command=command, parent_agent=PARENT, timeout_seconds=15.0)

    with pytest.raises(AttemptBindingError, match="parent_agent"):
        await run_attempt(
            paths, job_id="bound-2", command=command, parent_agent="other-controller", timeout_seconds=5.0
        )
    with pytest.raises(AttemptBindingError, match="cwd"):
        await run_attempt(
            paths,
            job_id="bound-2",
            command=command,
            parent_agent=PARENT,
            cwd=str(tmp_path / "other"),
            timeout_seconds=5.0,
        )
    with pytest.raises(AttemptBindingError, match="repo"):
        await run_attempt(
            paths,
            job_id="bound-2",
            command=command,
            parent_agent=PARENT,
            repo=str(tmp_path / "other"),
            timeout_seconds=5.0,
        )
    assert _run_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_unbound_parent_cannot_wait_or_consume(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    await run_attempt(paths, job_id="bound-3", command=command, parent_agent=PARENT, timeout_seconds=15.0)

    with pytest.raises(AttemptBindingError, match="bound to parent"):
        await await_terminal_event(paths, job_id="bound-3", parent_agent="other-controller", timeout_seconds=2.0)
    with pytest.raises(AttemptBindingError, match="bound to parent"):
        consume_terminal_event(paths, job_id="bound-3", parent_agent="other-controller")
    with pytest.raises(DispatchIntentError, match="missing dispatch intent"):
        consume_terminal_event(paths, job_id="never-dispatched", parent_agent=PARENT)

    assert AgentInboxStore(paths).read_recent("other-controller", limit=20) == []
    assert consume_terminal_event(paths, job_id="bound-3", parent_agent=PARENT) is not None


def test_identifiers_are_validated_before_path_use(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    for bad in ("../evil", "a/b", "", "with space", ".."):
        with pytest.raises(ValueError, match="invalid job_id"):
            read_attempt(paths, job_id=bad)
        with pytest.raises(ValueError, match="invalid parent_agent"):
            consume_terminal_event(paths, job_id="ok-id", parent_agent=bad)
    assert not (tmp_path / ".controlmesh" / "workspace" / "runtime" / "host-jobs" / "evil").exists()
    assert read_attempt(paths, job_id="ok-id") is None


# ---------------------------------------------------------------------------
# Fix 3: atomic consume across OS processes
# ---------------------------------------------------------------------------


def test_concurrent_consume_has_exactly_one_winner(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    event = asyncio.run(
        run_attempt(paths, job_id="consume-race", command=command, parent_agent=PARENT, timeout_seconds=15.0)
    )
    assert event is not None

    results = _spawn_bridge(tmp_path, mode="consume", job_id="consume-race", parent=PARENT, count=4)
    winners = [out for _, out in results if out == "EVENT"]

    assert [code for code, _ in results] == [0, 0, 0, 0]
    assert len(winners) == 1, f"expected one consume winner, got {results}"
    assert consume_terminal_event(paths, job_id="consume-race", parent_agent=PARENT) is None


# ---------------------------------------------------------------------------
# Fix 4: unknown worker process state requires review, never re-execution
# ---------------------------------------------------------------------------


def test_process_state_classifies_alive_dead_and_unknown() -> None:
    assert process_state(os.getpid()) == "alive"
    assert process_state(None) == "unknown"
    assert process_state(0) == "unknown"
    # pid 1 is not owned by this unprivileged user: EPERM means unknown, not dead.
    assert os.geteuid() != 0
    assert process_state(1) == "unknown"
    probe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    probe.wait()
    assert process_state(probe.pid) == "dead"


@pytest.mark.asyncio
async def test_unknown_worker_state_is_flagged_for_review_not_finalized(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    sleeper = _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {tmp_path / 'runs.txt'}\n"
        "sleep 30\n",
        name="sleeper.sh",
    )

    assert await run_attempt(paths, job_id="unknown-1", command=sleeper, parent_agent=PARENT, timeout_seconds=0.5) is None
    runner = HostJobRunner(paths)
    job = runner.get("unknown-1")
    assert job is not None
    real_pid = job.steps[0].pid

    # Replace the recorded pid with one this user cannot signal: fate unknown.
    job.steps[0].pid = 1
    job.steps[0].state = "running"
    job.state = "running"
    runner.store.put(job)

    answer = await await_terminal_event(paths, job_id="unknown-1", parent_agent=PARENT, timeout_seconds=1.5)
    assert answer is not None
    assert answer["outcome"] == OUTCOME_NEEDS_REVIEW
    assert answer["terminal"] is False
    assert answer["consumed"] is False
    assert answer["replay_authorized"] is False
    assert answer["review_required"] is True
    assert answer["review_reason"] == REVIEW_UNKNOWN_PROCESS

    status = read_attempt(paths, job_id="unknown-1")
    assert status is not None
    assert status["state"] == "running"
    assert status["review_required"] is True
    assert status["review_reason"] == REVIEW_UNKNOWN_PROCESS

    # No re-execution when reopening an attempt with an unknown worker.
    reopened = await run_attempt(paths, job_id="unknown-1", command=sleeper, parent_agent=PARENT, timeout_seconds=0.5)
    assert reopened is not None
    assert reopened["outcome"] == OUTCOME_NEEDS_REVIEW
    assert _run_count(tmp_path) == 1

    if real_pid:
        os.kill(int(real_pid), signal.SIGKILL)


@pytest.mark.asyncio
async def test_detached_worker_completion_is_reconciled_by_another_process(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    sleeper = _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {tmp_path / 'runs.txt'}\n"
        "sleep 1\n",
        name="short_sleeper.sh",
    )

    assert await run_attempt(paths, job_id="ext-attempt-5", command=sleeper, parent_agent=PARENT, timeout_seconds=0.2) is None
    snapshot = read_attempt(paths, job_id="ext-attempt-5")
    assert snapshot is not None
    assert snapshot["terminal"] is False
    assert snapshot["outcome"] == "status"

    event = await await_terminal_event(paths, job_id="ext-attempt-5", parent_agent=PARENT, timeout_seconds=15.0)
    assert event is not None
    assert event["state"] == "completed"
    assert event["exit_code"] == 0
    assert _run_count(tmp_path) == 1
    assert consume_terminal_event(paths, job_id="ext-attempt-5", parent_agent=PARENT) == event


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_artifact", [None, "", "  \n", "incomplete", "\udcff"])
async def test_confirmed_dead_worker_is_finalized_as_failed(tmp_path: Path, exit_artifact: str | None) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    sleeper = _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {tmp_path / 'runs.txt'}\n"
        "sleep 30\n",
        name="sleeper.sh",
    )

    assert await run_attempt(paths, job_id="dead-1", command=sleeper, parent_agent=PARENT, timeout_seconds=0.5) is None
    running = HostJobRunner(paths).get("dead-1")
    assert running is not None
    assert running.steps[0].pid is not None

    os.kill(int(running.steps[0].pid or 0), signal.SIGKILL)
    if exit_artifact is not None:
        HostJobRunner(paths).store.exit_code_path("dead-1", running.steps[0].id).write_bytes(
            exit_artifact.encode("utf-8", errors="surrogateescape")
        )
    event = await await_terminal_event(paths, job_id="dead-1", parent_agent=PARENT, timeout_seconds=15.0)

    assert event is not None
    assert event["outcome"] == OUTCOME_TERMINAL
    assert event["state"] == "failed"
    assert event["exit_code"] is None
    assert "disappeared" in event["last_error"]
    # Wrapper death is not confirmed execution quiescence: review is retained.
    assert event["review_required"] is True
    assert event["review_reason"] == REVIEW_WRAPPER_GONE
    assert event["execution_quiescence"] == "unknown"
    assert _run_count(tmp_path) == 1

    finalized = HostJobRunner(paths).get("dead-1")
    assert finalized is not None
    assert finalized.state == "failed"
    assert finalized.steps[0].state == "failed"
    assert consume_terminal_event(paths, job_id="dead-1", parent_agent=PARENT) is not None
    assert consume_terminal_event(paths, job_id="dead-1", parent_agent=PARENT) is None


# ---------------------------------------------------------------------------
# Review 3: intent integrity (no rebinding, no implicit adoption)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corrupt_dispatch_intent_refuses_rebinding(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    await run_attempt(paths, job_id="binding-check", command=command, parent_agent="owner", timeout_seconds=15.0)

    intent_path = paths.runtime_host_jobs_dir / "binding-check" / "DISPATCH.json"
    intent_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(DispatchIntentError, match="corrupt dispatch intent"):
        await run_attempt(paths, job_id="binding-check", command="false", parent_agent="other-owner", timeout_seconds=5.0)

    # Evidence untouched: same corrupt bytes, same completed job, no new delivery target.
    assert intent_path.read_text(encoding="utf-8") == "{broken"
    job = HostJobRunner(paths).get("binding-check")
    assert job is not None
    assert job.state == "completed"
    assert _run_count(tmp_path) == 1
    with pytest.raises(DispatchIntentError, match="corrupt dispatch intent"):
        consume_terminal_event(paths, job_id="binding-check", parent_agent="other-owner")
    with pytest.raises(DispatchIntentError, match="corrupt dispatch intent"):
        consume_terminal_event(paths, job_id="binding-check", parent_agent="owner")
    assert AgentInboxStore(paths).read_recent("other-owner", limit=20) == []


@pytest.mark.asyncio
async def test_deleted_dispatch_intent_refuses_rebinding(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    await run_attempt(paths, job_id="binding-del", command=command, parent_agent="owner", timeout_seconds=15.0)

    (paths.runtime_host_jobs_dir / "binding-del" / "DISPATCH.json").unlink()

    with pytest.raises(DispatchIntentError, match="missing dispatch intent"):
        await run_attempt(paths, job_id="binding-del", command="false", parent_agent="other-owner", timeout_seconds=5.0)
    assert _run_count(tmp_path) == 1
    assert (paths.runtime_host_jobs_dir / "binding-del" / "DISPATCH.json").exists() is False


def test_pre_existing_unbound_job_is_not_adopted(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    runner = HostJobRunner(paths)
    runner.store.put(
        HostJob(
            job_id="owned-elsewhere",
            job_kind="external_cli",
            repo=str(tmp_path / "repo"),
            steps=[HostJobStep(id="external_cli", title="pre-existing", command="true")],
        )
    )

    with pytest.raises(DispatchIntentError, match="refusing to rebind or adopt"):
        asyncio.run(
            run_attempt(
                paths, job_id="owned-elsewhere", command="false", parent_agent="owner", timeout_seconds=5.0
            )
        )

    job = runner.get("owned-elsewhere")
    assert job is not None
    assert job.state == "pending"
    assert (paths.runtime_host_jobs_dir / "owned-elsewhere" / "DISPATCH.json").exists() is False


@pytest.mark.asyncio
async def test_changed_provenance_is_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    await run_attempt(
        paths,
        job_id="prov-1",
        command=command,
        parent_agent=PARENT,
        plan_id="plan-a",
        source_task_id="task-a",
        step_title="Original title",
        timeout_seconds=15.0,
    )

    base: dict[str, object] = {"plan_id": "plan-a", "source_task_id": "task-a", "step_title": "Original title"}
    for overrides, field in (
        ({"plan_id": "plan-b"}, "plan_id"),
        ({"source_task_id": "task-b"}, "source_task_id"),
        ({"step_title": "Other title"}, "step_title"),
        ({"step_id": "other_step"}, "step_id"),
        ({"job_kind": "other_kind"}, "job_kind"),
        ({"side_effect": True}, "side_effect"),
        ({"approval_required": True}, "approval_required"),
    ):
        with pytest.raises(AttemptBindingError, match=field):
            await run_attempt(
                paths,
                job_id="prov-1",
                command=command,
                parent_agent=PARENT,
                timeout_seconds=5.0,
                **{**base, **overrides},
            )
    assert _run_count(tmp_path) == 1


def test_step_identifier_is_validated(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    with pytest.raises(ValueError, match="invalid step_id"):
        asyncio.run(
            run_attempt(paths, job_id="step-check", command="true", parent_agent=PARENT, step_id="../escape")
        )


# ---------------------------------------------------------------------------
# Review 3: wrapper/child separation and needs-review surfacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vanished_wrapper_retains_review_while_child_survives(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    wrapper = _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {tmp_path / 'runs.txt'}\n"
        f"sleep 30 &\necho $! > {tmp_path / 'child.pid'}\n"
        "sleep 30\n",
        name="wrapper.sh",
    )

    assert await run_attempt(paths, job_id="split-1", command=wrapper, parent_agent=PARENT, timeout_seconds=0.5) is None
    running = HostJobRunner(paths).get("split-1")
    assert running is not None
    wrapper_pid = int(running.steps[0].pid or 0)
    assert wrapper_pid > 0
    for _ in range(100):
        if (tmp_path / "child.pid").is_file():
            break
        await asyncio.sleep(0.05)
    child_pid = int((tmp_path / "child.pid").read_text(encoding="utf-8").strip())

    os.kill(wrapper_pid, signal.SIGKILL)
    event = await await_terminal_event(paths, job_id="split-1", parent_agent=PARENT, timeout_seconds=15.0)

    assert event is not None
    assert event["state"] == "failed"
    assert event["review_required"] is True
    assert event["review_reason"] == REVIEW_WRAPPER_GONE
    assert event["execution_quiescence"] == "unknown"

    # The wrapper is gone but its child is still running: quiescence is genuinely unknown.
    assert process_state(child_pid) == "alive"
    os.kill(child_pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_wait_returns_needs_review_and_later_reconciles_completion(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    sleeper = _write_worker(
        tmp_path,
        "#!/usr/bin/env bash\n"
        f"echo run >> {tmp_path / 'runs.txt'}\n"
        "sleep 3\n",
        name="sleeper3.sh",
    )

    assert await run_attempt(paths, job_id="review-1", command=sleeper, parent_agent=PARENT, timeout_seconds=0.2) is None
    runner = HostJobRunner(paths)
    job = runner.get("review-1")
    assert job is not None
    real_pid = job.steps[0].pid

    job.steps[0].pid = 1
    runner.store.put(job)

    started = time.monotonic()
    answer = await await_terminal_event(paths, job_id="review-1", parent_agent=PARENT, timeout_seconds=None)
    elapsed = time.monotonic() - started

    # Surfaces instead of blocking forever on a review-required state.
    assert elapsed < 10.0
    assert answer is not None
    assert answer["outcome"] == OUTCOME_NEEDS_REVIEW
    assert answer["review_reason"] == REVIEW_UNKNOWN_PROCESS

    # Genuine completion evidence stays reconcilable: restore the real pid, let the
    # worker finish, and a later wait still returns the terminal event (terminal
    # evidence is always evaluated before the review answer).
    restored = runner.get("review-1")
    assert restored is not None
    restored.steps[0].pid = real_pid
    runner.store.put(restored)
    await asyncio.sleep(3.5)

    event = await await_terminal_event(paths, job_id="review-1", parent_agent=PARENT, timeout_seconds=20.0)
    assert event is not None
    assert event["outcome"] == OUTCOME_TERMINAL
    assert event["state"] == "completed"
    assert event["exit_code"] == 0
    assert event["review_required"] is False
    assert _run_count(tmp_path) == 1


@pytest.mark.asyncio
async def test_dispatcher_lost_before_worker_start_is_reviewable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir(parents=True)
    command = _fake_worker(tmp_path)
    original = HostJobRunner.start

    def never_start(self: HostJobRunner, job_id: str) -> object:
        return self.get(job_id)

    monkeypatch.setattr(HostJobRunner, "start", never_start)
    answer = await run_attempt(paths, job_id="stall-1", command=command, parent_agent=PARENT, timeout_seconds=None)
    monkeypatch.setattr(HostJobRunner, "start", original)

    assert answer is not None
    assert answer["outcome"] == OUTCOME_NEEDS_REVIEW
    assert answer["review_reason"] == REVIEW_DISPATCHER_LOST
    assert answer["state"] == "pending"
    assert _run_count(tmp_path) == 0

    intent = read_dispatch_intent(paths, job_id="stall-1")
    assert intent is not None
    assert intent["dispatched"] is True
    assert intent["review_required"] is True


@pytest.mark.asyncio
async def test_orphan_execution_artifacts_prevent_implicit_recreation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    (tmp_path / "repo").mkdir()
    artifact = paths.runtime_host_job_artifacts_dir / "orphan-1" / "external_cli" / "stdout.log"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("previous execution evidence", encoding="utf-8")
    with pytest.raises(DispatchIntentError, match="existing job evidence"):
        await run_attempt(paths, job_id="orphan-1", command="true", parent_agent=PARENT)
    assert artifact.read_text(encoding="utf-8") == "previous execution evidence"
    assert not (paths.runtime_host_jobs_dir / "orphan-1" / "DISPATCH.json").exists()
