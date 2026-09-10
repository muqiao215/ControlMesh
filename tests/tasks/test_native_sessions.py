"""Native adoption verifies identity and lifecycle, not just command construction."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from controlmesh.bus.envelope import ExecutionContext, Origin, SourceScope, bind_execution_context, reset_execution_context
from controlmesh.cli.base import CLIConfig
from controlmesh.cli.executor import _build_subprocess_env
from controlmesh.cli.opencode_provider import OpenCodeCLI
from controlmesh.cli.types import AgentResponse
from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskEntry, TaskSubmit
from controlmesh.tasks.native_commands import native_task_command
from controlmesh.tasks.native_sessions import NativeSessionLease, read_native_session, validate_native_session
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.session import SessionKey
from controlmesh.workspace.paths import ControlMeshPaths

SID = "ses_TestHistory123"


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = tmp_path / "data/opencode/opencode.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE session(id TEXT, directory TEXT, project_id TEXT, title TEXT, time_updated INT, time_archived INT);
        CREATE TABLE message(id TEXT, session_id TEXT, time_created INT, time_updated INT, data TEXT);
        CREATE TABLE part(session_id TEXT, time_updated INT);
        """)
        db.execute("INSERT INTO session VALUES(?,?,?,?,?,NULL)", (SID, str(tmp_path), "project1", "history", 1))
        db.execute("INSERT INTO message VALUES(?,?,?,?,?)", ("msg1", SID, 1, 1, json.dumps({
            "role": "assistant", "providerID": "vendor", "modelID": "model", "time": {"completed": 1},
        })))
    return read_native_session(SID), path


def context(scope=SourceScope.LOCAL_FOREGROUND):
    return ExecutionContext.issue(origin=Origin.USER, source_scope=scope, transport="terminal")


def submission(ref):
    return TaskSubmit(chat_id=1, prompt="continue historical work", message_id=0, thread_id=None,
                      parent_agent="main", transport="terminal", provider_override="opencode",
                      model_override="vendor/model", repo_root=ref.directory, native_session=ref,
                      execution_context=context())


def make_hub(tmp_path, response=None):
    paths = ControlMeshPaths(controlmesh_home=tmp_path / "cm")
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    cli = MagicMock()
    cli.execute = AsyncMock(side_effect=[AgentResponse(result="PONG", session_id="ses_Probe"),
                                        response or AgentResponse(result="historical answer", session_id=SID)])
    config = MagicMock(enabled=True, max_parallel=5, timeout_seconds=30)
    return TaskHub(registry, paths, cli_service=cli, config=config), cli


async def drain(hub, task_id):
    await hub._in_flight[task_id].asyncio_task
    await asyncio.sleep(0)


def test_identity_revision_and_read_only(native):
    ref, path = native
    assert validate_native_session(ref) == ref
    before = path.read_bytes()
    assert read_native_session(SID).model == "vendor/model"
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        db.execute("UPDATE message SET time_updated=2")
    with pytest.raises(ValueError, match="changed"):
        validate_native_session(ref)


@pytest.mark.parametrize("statement", ["UPDATE session SET directory='/missing-native-cwd'",
                                         "UPDATE session SET project_id='another'",
                                         "UPDATE session SET time_archived=1", "DELETE FROM session"])
def test_changed_native_identity_rejected(native, statement):
    ref, path = native
    with sqlite3.connect(path) as db:
        db.execute(statement)
    with pytest.raises(ValueError, match="Native session"):
        validate_native_session(ref)


def test_lease_excludes_other_cm_runs_and_releases(native):
    ref, _ = native
    lease = NativeSessionLease(ref)
    with pytest.raises(ValueError, match="leased"):
        NativeSessionLease(ref)
    lease.close()
    NativeSessionLease(ref).close()


async def test_adoption_runs_exact_session_model_cwd_and_persists(native, tmp_path):
    ref, _ = native
    hub, cli = make_hub(tmp_path)
    task_id = hub.submit(submission(ref))
    with pytest.raises(ValueError, match="owned"):
        hub.submit(submission(ref))
    await drain(hub, task_id)
    calls = [call.args[0] for call in cli.execute.await_args_list]
    assert calls[0].resume_session is None
    assert calls[1].resume_session == SID
    assert calls[1].model_override == "vendor/model"
    assert calls[1].working_dir == ref.directory
    entry = hub.registry.get(task_id)
    assert entry.status == "done"
    restored = TaskEntry.from_dict(entry.to_dict())
    assert restored.native_session == ref
    assert restored.session_id == SID
    cli.execute.side_effect = [AgentResponse(result="PONG"), AgentResponse(result="again", session_id=SID)]
    hub.resume(task_id, "next")
    await drain(hub, task_id)
    assert cli.execute.await_args.args[0].resume_session == SID
    await hub.shutdown()


async def test_wrong_provider_session_fails_without_rebinding(native, tmp_path):
    ref, _ = native
    hub, _ = make_hub(tmp_path, AgentResponse(result="wrong", session_id="ses_Other"))
    task_id = hub.submit(submission(ref))
    await drain(hub, task_id)
    assert hub.registry.get(task_id).status == "failed"
    assert hub.registry.get(task_id).session_id == SID
    await hub.shutdown()


async def test_quota_preflight_does_not_touch_source(native, tmp_path):
    ref, _ = native
    hub, cli = make_hub(tmp_path)
    cli.execute.side_effect = [AgentResponse(result="quota", is_error=True, error_code="quota_exhausted")]
    task_id = hub.submit(submission(ref))
    await drain(hub, task_id)
    assert cli.execute.await_count == 1
    entry = hub.registry.get(task_id)
    assert entry.status == "failed"
    assert "quota_exhausted" in entry.error
    assert entry.session_id == SID
    assert entry.native_session == ref
    await hub.shutdown()


@pytest.mark.parametrize("scope", [SourceScope.LEGACY_COMPAT, SourceScope.API, SourceScope.LOCAL_FOREGROUND])
async def test_ingress_and_grants_are_not_widened(native, tmp_path, scope):
    ref, _ = native
    hub, cli = make_hub(tmp_path)
    submit = submission(ref)
    submit.execution_context = context(scope)
    if scope is SourceScope.LOCAL_FOREGROUND:
        submit.requested_no_network = True
        task_id = hub.submit(submit)
        await drain(hub, task_id)
        assert hub.registry.get(task_id).tool_grant is not None
        assert hub.registry.get(task_id).status == "failed"
        cli.execute.assert_not_awaited()
    else:
        with pytest.raises(ValueError, match="local CM terminal"):
            hub.submit(submit)
    await hub.shutdown()


async def test_cancel_checkpoints_native_turn_and_recovery_reuses_session(native, tmp_path):
    ref, path = native
    hub, cli = make_hub(tmp_path)
    started = asyncio.Event()

    async def execute(request):
        if request.resume_session is None:
            return AgentResponse(result="PONG")
        with sqlite3.connect(path) as db:
            db.execute("UPDATE message SET time_updated=2")
        started.set()
        await asyncio.Event().wait()
        return AgentResponse(result="unreachable")

    cli.execute.side_effect = execute
    task_id = hub.submit(submission(ref))
    await started.wait()
    await hub.cancel(task_id)
    await asyncio.sleep(0)
    entry = hub.registry.get(task_id)
    assert entry.session_id == SID
    assert entry.native_session.revision != ref.revision
    # Restart the registry and hub, then use the persisted task's normal resume path.
    await hub.shutdown()
    recovered, recovered_cli = make_hub(tmp_path)
    recovered_cli.execute.side_effect = [AgentResponse(result="PONG"), AgentResponse(result="recovered", session_id=SID)]
    recovered.resume(task_id, "continue after interruption")
    await drain(recovered, task_id)
    assert recovered.registry.get(task_id).status == "done"
    assert recovered_cli.execute.await_args.args[0].resume_session == SID
    await recovered.shutdown()


def test_native_cwd_does_not_change_runtime_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTROLMESH_HOME", raising=False)
    config = CLIConfig(working_dir=tmp_path / "native", runtime_home=str(tmp_path / "cm"))
    env = _build_subprocess_env(config)
    assert env["CONTROLMESH_HOME"] == str(tmp_path / "cm")
    monkeypatch.setattr(OpenCodeCLI, "_find_cli", staticmethod(lambda: "opencode"))
    cmd = OpenCodeCLI(config)._build_command("next", resume_session=SID)
    assert cmd[cmd.index("--dir") + 1] == str(tmp_path / "native")
    assert cmd[cmd.index("--session") + 1] == SID


async def test_command_requires_trusted_context_and_checks_explicit_directory(native, tmp_path):
    ref, _ = native
    hub, cli = make_hub(tmp_path)
    key = SessionKey(chat_id=1, transport="terminal")
    text = await native_task_command(hub, key, f"/tasks inspect {SID}")
    assert "requires the local" in text
    token = bind_execution_context(context())
    try:
        text = await native_task_command(hub, key, f"/tasks inspect {SID}")
        assert json.loads(text)["revision"] == ref.revision
        text = await native_task_command(hub, key,
            f"/tasks adopt --session {SID} --revision {ref.revision} --directory /wrong "
            f"--repo {tmp_path} --model vendor/model -- continue")
        assert "mismatch" in text
        cli.execute.assert_not_awaited()
    finally:
        reset_execution_context(token)
        await hub.shutdown()


async def test_external_write_blocks_resume_before_reactivation(native, tmp_path):
    ref, path = native
    hub, cli = make_hub(tmp_path)
    task_id = hub.submit(submission(ref))
    await drain(hub, task_id)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE message SET time_updated=99")
    with pytest.raises(ValueError, match="changed"):
        hub.resume(task_id, "next")
    assert hub.registry.get(task_id).status == "done"
    assert cli.execute.await_count == 2
    await hub.shutdown()


async def test_cancel_during_preflight_releases_lease_without_native_dispatch(native, tmp_path):
    ref, _ = native
    hub, cli = make_hub(tmp_path)
    started = asyncio.Event()

    async def preflight(request):
        assert request.resume_session is None
        started.set()
        await asyncio.Event().wait()

    cli.execute.side_effect = preflight
    task_id = hub.submit(submission(ref))
    await started.wait()
    await hub.cancel(task_id)
    entry = hub.registry.get(task_id)
    assert entry.status == "cancelled"
    assert entry.native_session == ref
    assert cli.execute.await_count == 1
    NativeSessionLease(ref).close()
    await hub.shutdown()


def test_viewer_candidates_crosscheck_native_store_and_reject_redirects(native):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from controlmesh.tasks.native_sessions import viewer_candidates

    ref, _ = native

    class Handler(BaseHTTPRequestHandler):
        redirect = False

        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.redirect:
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/private")
                self.end_headers()
                return
            data = json.dumps({"sessions": [
                {"id": SID, "cwd": ref.directory, "title": "untrusted override"},
                {"id": SID, "cwd": "/wrong"}, {"id": "ses_Missing"},
            ]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        refs = viewer_candidates("history", port=server.server_port)
        assert len(refs) == 1
        assert refs[0].title == "history"
        assert refs[0].source == "history-viewer"
        Handler.redirect = True
        with pytest.raises(ValueError, match="Cannot read History Viewer"):
            viewer_candidates("history", port=server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_part_only_update_invalidates_checkpoint(native):
    ref, path = native
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO part VALUES(?,?)", (SID, 9))
    with pytest.raises(ValueError, match="changed"):
        validate_native_session(ref)


async def test_success_without_native_session_id_is_not_accepted(native, tmp_path):
    ref, _ = native
    hub, _ = make_hub(tmp_path, AgentResponse(result="unbound text"))
    task_id = hub.submit(submission(ref))
    await drain(hub, task_id)
    assert hub.registry.get(task_id).status == "failed"
    assert hub.registry.get(task_id).session_id == SID
    await hub.shutdown()


async def test_crash_recovery_rechecks_revision_and_live_process(native, tmp_path):
    import os

    ref, path = native
    hub, _ = make_hub(tmp_path)
    # Persist an admitted task as if its owning process died before completion.
    entry = hub.registry.create(submission(ref), "opencode", "vendor/model")
    from controlmesh.tasks.models import TaskBindingSnapshot
    entry.binding = TaskBindingSnapshot(slot="opencode_default", assistant="opencode", command="opencode")
    hub.registry.update_status(entry.task_id, "running", binding=entry.binding)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE message SET time_updated=88")
    recovered, cli = make_hub(tmp_path)
    assert recovered.registry.get(entry.task_id).status == "stale"
    current = read_native_session(SID)
    token = bind_execution_context(context())
    try:
        with pytest.raises(ValueError, match="changed"):
            recovered.recover_native(entry.task_id, ref.revision, "continue")
        recovered._process_leases.register(chat_id=1, topic_id=None, label=f"task:{entry.task_id}:preflight", pid=os.getpid())
        with pytest.raises(ValueError, match="still alive"):
            recovered.recover_native(entry.task_id, current.revision, "continue")
        recovered._process_leases.unregister(chat_id=1, label=f"task:{entry.task_id}:preflight", pid=os.getpid())
        recovered.recover_native(entry.task_id, current.revision, "continue")
        await drain(recovered, entry.task_id)
        assert recovered.registry.get(entry.task_id).status == "done"
        assert cli.execute.await_args.args[0].resume_session == SID
    finally:
        reset_execution_context(token)
        await recovered.shutdown()
        await hub.shutdown()
