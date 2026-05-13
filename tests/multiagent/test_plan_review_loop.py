from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from controlmesh.multiagent.commands import cmd_agents
from controlmesh.multiagent.plan_review_loop import (
    approve_phase,
    consume_pending_repair_feedback,
    create_mesh_workflow,
    handle_task_result,
    pending_release_approval_text,
    repair_phase,
    workflow_status_text,
)
from controlmesh.planning_files import PlanPhase, create_plan_files, plan_dir_for
from controlmesh.runtime import HostJob, HostJobStep
from controlmesh.session.key import SessionKey
from controlmesh.runtime.models import AgentInboxItem
from controlmesh.multiagent.release_gate import ensure_publish_gate, load_gate_state, mark_executed
from controlmesh.tasks.models import TaskEntry, TaskResult, TaskSubmit


class _FakeRegistry:
    def __init__(self, entry: TaskEntry | None = None) -> None:
        self._entry = entry

    def get(self, task_id: str) -> TaskEntry | None:
        if self._entry and self._entry.task_id == task_id:
            return self._entry
        return None


class _FakeTaskHub:
    def __init__(self, entry: TaskEntry | None = None) -> None:
        self.registry = _FakeRegistry(entry)
        self.submits: list[TaskSubmit] = []
        self.inbox: list[AgentInboxItem] = []
        self.resumes: list[tuple[str, str, str]] = []
        self.tool_results: list[dict[str, object]] = [{"content": [{"tool_use_id": "toolu"}]}]

    def submit(self, submit: TaskSubmit) -> str:
        self.submits.append(submit)
        return f"task-{len(self.submits)}"

    def resume(self, task_id: str, prompt: str, parent_agent: str = "") -> str:
        self.resumes.append((task_id, prompt, parent_agent))
        return task_id

    def read_agent_inbox(self, agent_name: str, *, limit: int = 20) -> list[AgentInboxItem]:
        assert agent_name == "main"
        return self.inbox[-limit:]

    def read_agent_inbox_filtered(
        self,
        agent_name: str,
        *,
        limit: int = 20,
        plan_id: str = "",
        chat_id: object | None = None,
        topic_id: object | None = None,
    ) -> list[AgentInboxItem]:
        assert agent_name == "main"
        items = list(self.inbox)
        if plan_id:
            items = [item for item in items if str(item.payload.get("plan_id") or "") == plan_id]
        if chat_id not in (None, ""):
            items = [item for item in items if item.payload.get("chat_id") == chat_id]
        if topic_id is None and (plan_id or chat_id not in (None, "")):
            items = [item for item in items if item.payload.get("topic_id") in (None, "")]
        elif topic_id is not None:
            items = [item for item in items if item.payload.get("topic_id") == topic_id]
        return items[-limit:]

    def consume_tool_results(
        self,
        agent_name: str,
        *,
        limit: int = 20,
        plan_id: str = "",
        chat_id: object | None = None,
        topic_id: object | None = None,
    ) -> list[dict[str, object]]:
        assert agent_name == "main"
        items = list(self.tool_results[:limit])
        self.tool_results = self.tool_results[limit:]
        return items


class _FakeHostJobRunner:
    def __init__(self, job: HostJob | None = None) -> None:
        self.job = job
        self.ensure_calls: list[dict[str, object]] = []
        self.approvals: list[tuple[str, str, str]] = []
        self.started: list[str] = []

    def ensure_job(self, spec: object) -> HostJob:
        job_id = getattr(spec, "job_id", "")
        plan_id = getattr(spec, "plan_id", "")
        repo = getattr(spec, "repo", "")
        version = getattr(spec, "version", "")
        tag = getattr(spec, "tag", "")
        steps = getattr(spec, "steps", []) or []
        notes_file = ""
        if len(steps) >= 7:
            command = str(getattr(steps[6], "command", ""))
            marker = "--notes-file "
            if marker in command:
                notes_file = command.split(marker, 1)[1].split(maxsplit=1)[0]
        self.ensure_calls.append(
            {
                "job_id": job_id,
                "plan_id": plan_id,
                "repo": repo,
                "version": version,
                "tag": tag,
                "notes_file": notes_file,
            }
        )
        if self.job is None:
            self.job = HostJob(
                job_id=job_id or f"release-{tag}",
                plan_id=plan_id,
                repo=repo,
                version=version,
                tag=tag,
                state="pending",
                steps=[HostJobStep(id="pytest_full", title="pytest", command="uv run pytest -q")],
            )
        return self.job

    def approve_step(self, job_id: str, step_id: str, *, approved_by: str) -> HostJob:
        self.approvals.append((job_id, step_id, approved_by))
        assert self.job is not None
        self.job.current_step_id = step_id
        self.job.state = "running"
        return self.job

    def start(self, job_id: str) -> HostJob:
        self.started.append(job_id)
        assert self.job is not None
        return self.job

    def get(self, job_id: str) -> HostJob | None:
        if self.job is not None and self.job.job_id == job_id:
            return self.job
        return None

    def list_jobs(self) -> list[HostJob]:
        return [self.job] if self.job is not None else []


def _make_orch(tmp_path: Path, hub: _FakeTaskHub) -> SimpleNamespace:
    orch = SimpleNamespace(
        task_hub=hub,
        host_job_runner=None,
        paths=SimpleNamespace(plans_dir=tmp_path / "plans", workspace=tmp_path / "workspace"),
        supervisor=SimpleNamespace(
            health={"main": SimpleNamespace(status="running", uptime_human="1m", restart_count=0)},
            stacks={"main": SimpleNamespace(is_main=True, config=SimpleNamespace(model="test-model", reasoning_effort=""))},
        ),
        _config=SimpleNamespace(model="gpt-5.5"),
        resolve_runtime_target=lambda _requested=None: ("gpt-5.5", "codex"),
    )
    orch._foreground_state = SimpleNamespace(active_intent="", active_repo="", active_constraints="")
    orch.get_foreground_state = AsyncMock(return_value=orch._foreground_state)
    orch.sync_foreground_state = AsyncMock(return_value=orch._foreground_state)
    return orch


def _write_state(tmp_path: Path, plan_id: str, payload: dict[str, object]) -> None:
    plan_dir = plan_dir_for(tmp_path / "plans", plan_id)
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "STATE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_pending_release_approval_text_ignores_runner_without_list_jobs(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path, _FakeTaskHub())
    orch.host_job_runner = SimpleNamespace()

    assert pending_release_approval_text(orch) is None


def test_pending_release_approval_text_returns_explicit_step(tmp_path: Path) -> None:
    orch = _make_orch(tmp_path, _FakeTaskHub())
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
                job_id="release-v0.31.0",
                plan_id="plan-x",
                repo="https://github.com/org/repo",
                version="0.31.0",
                tag="v0.31.0",
                state="awaiting_approval",
                current_step_id="push_tag",
                steps=[
                    HostJobStep(
                        id="push_tag",
                        title="push tag",
                        command="git push origin v0.31.0",
                        state="awaiting_approval",
                        approval_required=True,
                    )
                ],
            )
        )
    )

    text = pending_release_approval_text(orch)

    assert text is not None
    assert "Release approval requires an explicit step." in text
    assert "push_tag" in text
    assert "approve push_tag release-v0.31.0" in text


@pytest.mark.asyncio
async def test_cmd_agents_run_creates_plan_workflow(tmp_path: Path) -> None:
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.cli_service = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                result=json.dumps(
                    {
                        "plan_markdown": "# Plan\n",
                        "phases": [
                            {
                                "id": "phase-001",
                                "title": "Inspect",
                                "workunit_kind": "repo_audit",
                                "allowed_edit": False,
                            },
                            {
                                "id": "phase-002",
                                "title": "Implement",
                                "workunit_kind": "phase_execution",
                                "allowed_edit": True,
                            },
                        ],
                    }
                ),
                timed_out=False,
                is_error=False,
            )
        )
    )
    key = SessionKey(transport="tg", chat_id=42)

    result = await cmd_agents(orch, key, "/agents run Build the new phased controller")

    assert "ControlMesh auto-run started." in result.text
    assert "Use `/mesh` for phased workflows." in result.text
    assert hub.submits
    submit = hub.submits[0]
    assert submit.workunit_kind == "repo_audit"
    assert submit.plan_id
    state = json.loads((plan_dir_for(tmp_path / "plans", submit.plan_id) / "STATE.json").read_text())
    assert state["controller_mode"] == "agents_review_loop"
    assert state["status"] == "executing"
    assert state["source_chat_id"] == 42
    manifest = json.loads((plan_dir_for(tmp_path / "plans", submit.plan_id) / "PHASES.json").read_text())
    assert len(manifest["phases"]) == 2


@pytest.mark.asyncio
async def test_create_mesh_workflow_autostarts_first_phase_without_background_planning(tmp_path: Path) -> None:
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.cli_service = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                result=json.dumps(
                    {
                        "plan_markdown": "# Plan\n",
                        "phases": [
                            {
                                "id": "phase-001",
                                "title": "Inspect repository",
                                "workunit_kind": "repo_audit",
                                "allowed_edit": False,
                            }
                        ],
                    }
                ),
                timed_out=False,
                is_error=False,
            )
        )
    )
    key = SessionKey(transport="tg", chat_id=7)

    start = await create_mesh_workflow(orch, key, "Fix /mesh planning semantics")

    assert start.plan_id
    assert start.phase_count == 1
    assert start.current_phase_id == "phase-001"
    assert hub.submits
    submit = hub.submits[0]
    assert submit.workunit_kind == "repo_audit"
    assert submit.plan_id == start.plan_id
    assert submit.phase_id == "phase-001"
    state = json.loads((plan_dir_for(tmp_path / "plans", start.plan_id) / "STATE.json").read_text())
    assert state["status"] == "executing"
    assert state["current_phase_id"] == "phase-001"


@pytest.mark.asyncio
async def test_create_mesh_workflow_uses_foreground_active_intent_for_handoff_text(tmp_path: Path) -> None:
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch._foreground_state = SimpleNamespace(
        active_intent="请按最小可合并方式修正 /mesh planning 被错误下放后台的问题",
        active_repo=str(tmp_path / "workspace"),
        active_constraints="local only",
    )
    orch.get_foreground_state = AsyncMock(return_value=orch._foreground_state)
    orch.cli_service = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                result=json.dumps({"plan_markdown": "# Plan\n", "phases": []}),
                timed_out=False,
                is_error=False,
            )
        )
    )

    start = await create_mesh_workflow(orch, SessionKey(transport="tg", chat_id=9), "开始全自动")

    assert "修正 /mesh planning 被错误下放后台的问题" in start.objective


@pytest.mark.asyncio
async def test_create_mesh_workflow_caps_phase_count_at_five(tmp_path: Path) -> None:
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.cli_service = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                result=json.dumps(
                    {
                        "plan_markdown": "# Plan\n",
                        "phases": [
                            {"id": f"phase-00{i}", "title": f"Phase {i}", "workunit_kind": "repo_audit", "allowed_edit": False}
                            for i in range(1, 7)
                        ],
                    }
                ),
                timed_out=False,
                is_error=False,
            )
        )
    )

    start = await create_mesh_workflow(orch, SessionKey(transport="tg", chat_id=10), "Refactor /mesh")

    manifest = json.loads((plan_dir_for(tmp_path / "plans", start.plan_id) / "PHASES.json").read_text())
    assert len(manifest["phases"]) == 5
    assert start.phase_count == 5


@pytest.mark.asyncio
async def test_approve_phase_starts_next_pending_phase(tmp_path: Path) -> None:
    plan_id = "plan-2"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(
            PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution", status="completed"),
            PlanPhase(
                id="phase-2",
                title="Executor",
                workunit_kind="phase_execution",
                provider="claude",
                model="sonnet",
            ),
        ),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 9,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)

    text = await approve_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id)

    assert "Started next phase `phase-2` automatically" in text
    assert hub.submits[0].phase_id == "phase-2"
    assert hub.submits[0].provider_override == "claude"
    assert hub.submits[0].model_override == "sonnet"
    state = json.loads((plan_dir_for(tmp_path / "plans", plan_id) / "STATE.json").read_text())
    assert state["status"] == "executing"
    assert state["current_phase_id"] == "phase-2"


@pytest.mark.asyncio
async def test_approve_phase_resumes_plan_level_publish_gate(tmp_path: Path) -> None:
    plan_id = "release-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(
            PlanPhase(
                id="publish",
                title="Publish Release",
                workunit_kind="github_release",
                metadata={"gate_kind": "release_publish"},
            ),
        ),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "awaiting_publish_approval",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "publish",
            "awaiting_review_phase_id": "publish",
            "source_transport": "tg",
            "source_chat_id": 9,
            "repo": "/repo",
        },
    )
    ensure_publish_gate(
        tmp_path / "plans",
        plan_id=plan_id,
        repo="https://github.com/org/repo",
        version="0.24.33",
        commit="ddf996a",
        tag="v0.24.33",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.24.33",
            "repo": "https://github.com/org/repo",
            "version": "0.24.33",
            "tag": "v0.24.33",
            "notes_file": "docs/release-note-v0.24.33.md",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
                job_id="release-v0.24.33",
                plan_id=plan_id,
                repo="https://github.com/org/repo",
                version="0.24.33",
                tag="v0.24.33",
                state="pending",
                steps=[HostJobStep(id="pytest_full", title="pytest", command="uv run pytest -q")],
            )
        )
    )

    text = await approve_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id)

    assert "Approved publish gate" in text
    assert hub.resumes == []
    assert orch.host_job_runner.started == ["release-v0.24.33"]
    gate = load_gate_state(tmp_path / "plans", plan_id)
    assert gate["status"] == "executing"
    assert gate["executor_task_id"] == "release-v0.24.33"


@pytest.mark.asyncio
async def test_release_publish_phase_marks_executed_before_generic_review(tmp_path: Path) -> None:
    plan_id = "release-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release",
        phases=(PlanPhase(id="publish", title="Publish", workunit_kind="phase_execution"),),
        status="executing",
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "executing",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "publish",
            "source_transport": "tg",
            "source_chat_id": 13,
            "repo": "/repo",
        },
    )
    ensure_publish_gate(
        tmp_path / "plans",
        plan_id=plan_id,
        repo="/repo",
        version="0.24.33",
        commit="ddf996a",
        tag="v0.24.33",
        commands=["git push origin v0.24.33"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.24.33",
            "repo": "/repo",
            "version": "0.24.33",
            "tag": "v0.24.33",
            "notes_file": "docs/release-note-v0.24.33.md",
        },
    )
    entry = TaskEntry(
        task_id="publish-task-1",
        chat_id=13,
        parent_agent="main",
        name="publish",
        prompt_preview="",
        provider="claude",
        model="sonnet",
        status="done",
        workunit_kind="phase_execution",
        plan_id=plan_id,
        phase_id="publish",
        phase_metadata={"gate_kind": "release_publish"},
    )
    hub = _FakeTaskHub(entry)
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
                job_id="release-v0.24.33",
                plan_id=plan_id,
                repo="/repo",
                version="0.24.33",
                tag="v0.24.33",
                state="completed",
                current_step_id="gh_release_create",
                steps=[HostJobStep(id="gh_release_create", title="release", command="gh release create")],
            )
        )
    )

    note = await handle_task_result(
        orch,
        TaskResult(
            task_id="publish-task-1",
            chat_id=13,
            parent_agent="main",
            name="publish",
            prompt_preview="",
            result_text="published",
            status="done",
            elapsed_seconds=1,
            provider="claude",
            model="sonnet",
        ),
    )

    assert note is not None
    assert "publish host job completed" in note
    assert (tmp_path / "plans" / plan_id / "publish" / "EXECUTED.json").is_file()
    gate = load_gate_state(tmp_path / "plans", plan_id)
    assert gate["status"] == "executed"


@pytest.mark.asyncio
async def test_approve_phase_waits_for_publish_execution_before_verify(tmp_path: Path) -> None:
    plan_id = "release-plan-verify"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(
            PlanPhase(id="publish", title="Publish", workunit_kind="github_release", status="completed"),
            PlanPhase(
                id="verify",
                title="Verify",
                workunit_kind="test_execution",
                metadata={"wait_for_publish_execution": True},
            ),
        ),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "publish",
            "awaiting_review_phase_id": "publish",
            "source_transport": "tg",
            "source_chat_id": 9,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)

    text = await approve_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id)
    assert "waiting for publish execution before verify can start" in text.lower()
    assert not hub.submits

    mark_executed(
        tmp_path / "plans",
        plan_id=plan_id,
        payload={"main_pushed": True, "tag_pushed": True},
    )
    text2 = await approve_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id)
    assert "Started next phase `verify` automatically" in text2
    assert hub.submits[0].phase_id == "verify"


@pytest.mark.asyncio
async def test_repair_phase_reruns_current_phase_with_feedback(tmp_path: Path) -> None:
    plan_id = "plan-3"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution", status="completed"),),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 11,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)

    text = await repair_phase(
        orch,
        SessionKey(transport="tg", chat_id=11),
        plan_id,
        "Please tighten the contract fields.",
    )

    assert "Started rerun task `task-1`" in text
    assert "Please tighten the contract fields." in hub.submits[0].prompt
    state = json.loads((plan_dir_for(tmp_path / "plans", plan_id) / "STATE.json").read_text())
    assert state["status"] == "executing"
    assert state["current_phase_id"] == "phase-1"


@pytest.mark.asyncio
async def test_repair_phase_without_feedback_waits_for_next_chat_message(tmp_path: Path) -> None:
    plan_id = "plan-3b"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution", status="completed"),),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 11,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    key = SessionKey(transport="tg", chat_id=11)

    text = await repair_phase(orch, key, plan_id, "")

    assert "waiting for repair feedback" in text
    assert not hub.submits
    assert "Waiting for: repair_feedback" in workflow_status_text(orch, plan_id)

    consumed = await consume_pending_repair_feedback(
        orch,
        key,
        "Please tighten the contract fields.",
    )

    assert consumed is not None
    assert "Started rerun task `task-1`" in consumed
    assert "Please tighten the contract fields." in hub.submits[0].prompt
    state = json.loads((plan_dir_for(tmp_path / "plans", plan_id) / "STATE.json").read_text())
    assert state["status"] == "executing"
    assert "repair_feedback_waiting" not in state


@pytest.mark.asyncio
async def test_pending_repair_feedback_is_scoped_to_same_conversation(tmp_path: Path) -> None:
    plan_id = "plan-3c"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution", status="completed"),),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 11,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)

    await repair_phase(orch, SessionKey(transport="tg", chat_id=11, topic_id=5), plan_id, "")

    consumed = await consume_pending_repair_feedback(
        orch,
        SessionKey(transport="tg", chat_id=11, topic_id=6),
        "wrong topic feedback",
    )

    assert consumed is None
    assert not hub.submits


@pytest.mark.asyncio
async def test_cmd_agents_repair_without_feedback_enters_waiting_state(tmp_path: Path) -> None:
    plan_id = "plan-3d"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution", status="completed"),),
        status="executing",
        current_phase=1,
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 11,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)

    result = await cmd_agents(orch, SessionKey(transport="tg", chat_id=11), f"/agents repair {plan_id}")

    assert "waiting for repair feedback" in result.text
    assert not hub.submits


@pytest.mark.asyncio
async def test_phase_completion_note_includes_review_buttons(tmp_path: Path) -> None:
    plan_id = "plan-4"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution"),),
        status="executing",
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "executing",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 13,
            "repo": "/repo",
        },
    )
    entry = TaskEntry(
        task_id="phase-task-1",
        chat_id=13,
        parent_agent="main",
        name="phase",
        prompt_preview="",
        provider="codex",
        model="gpt-5.5",
        status="done",
        workunit_kind="phase_execution",
        plan_id=plan_id,
        phase_id="phase-1",
    )
    hub = _FakeTaskHub(entry)
    orch = _make_orch(tmp_path, hub)

    note = await handle_task_result(
        orch,
        TaskResult(
            task_id="phase-task-1",
            chat_id=13,
            parent_agent="main",
            name="phase",
            prompt_preview="",
            result_text="ok",
            status="done",
            elapsed_seconds=1,
            provider="codex",
            model="gpt-5.5",
        ),
    )

    assert note is not None
    assert "[button:Approve|/mesh approve plan-4]" in note
    assert "[button:Repair|/mesh repair plan-4]" in note
    assert "[button:Status|/mesh status plan-4]" in note


def test_workflow_status_includes_recent_main_inbox_items(tmp_path: Path) -> None:
    plan_id = "plan-inbox"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(PlanPhase(id="phase-1", title="Contracts", workunit_kind="phase_execution"),),
        status="executing",
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "review_required",
            "controller_mode": "agents_review_loop",
            "current_phase_id": "phase-1",
            "awaiting_review_phase_id": "phase-1",
            "source_transport": "tg",
            "source_chat_id": 13,
            "repo": "/repo",
        },
    )
    hub = _FakeTaskHub()
    hub.inbox.append(
        AgentInboxItem(
            to_agent="main",
            kind="task.done",
            summary="Phase 1 worker completed with summarized result",
            from_task="task-1",
            result_ref="task:task-1/result",
            payload={"plan_id": plan_id, "chat_id": 13, "topic_id": None},
        )
    )
    hub.inbox.append(
        AgentInboxItem(
            to_agent="main",
            kind="task.done",
            summary="Unrelated plan result",
            from_task="task-2",
            result_ref="task:task-2/result",
            payload={"plan_id": "other-plan", "chat_id": 13, "topic_id": None},
        )
    )
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
                job_id="release-v0.24.33",
                plan_id=plan_id,
                repo="/repo",
                version="0.24.33",
                tag="v0.24.33",
                state="awaiting_approval",
                current_step_id="push_tag",
                steps=[
                    HostJobStep(
                        id="push_tag",
                        title="push tag",
                        command="git push origin v0.24.33",
                        state="awaiting_approval",
                        approval_required=True,
                    )
                ],
            )
        )
    )
    ensure_publish_gate(
        tmp_path / "plans",
        plan_id=plan_id,
        repo="/repo",
        version="0.24.33",
        commit="abc1234",
        tag="v0.24.33",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.24.33",
            "repo": "/repo",
            "version": "0.24.33",
            "tag": "v0.24.33",
            "notes_file": "docs/release-note-v0.24.33.md",
        },
    )

    text = workflow_status_text(orch, plan_id)

    assert "Main inbox:" in text
    assert "job id: release-v0.24.33" in text
    assert "status: awaiting_approval" in text
    assert "awaiting approval:" in text
    assert "- push_tag" in text
    assert "task.done: Phase 1 worker completed with summarized result" in text
    assert "Unrelated plan result" not in text
