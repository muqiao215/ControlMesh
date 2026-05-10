from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from controlmesh.multiagent.commands import cmd_agents
from controlmesh.multiagent.plan_review_loop import (
    approve_phase,
    consume_pending_repair_feedback,
    handle_task_result,
    repair_phase,
    workflow_status_text,
)
from controlmesh.planning_files import PlanPhase, create_plan_files, plan_dir_for
from controlmesh.session.key import SessionKey
from controlmesh.runtime.models import AgentInboxItem
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

    def submit(self, submit: TaskSubmit) -> str:
        self.submits.append(submit)
        return f"task-{len(self.submits)}"

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


def _make_orch(tmp_path: Path, hub: _FakeTaskHub) -> SimpleNamespace:
    return SimpleNamespace(
        task_hub=hub,
        paths=SimpleNamespace(plans_dir=tmp_path / "plans", workspace=tmp_path / "workspace"),
        supervisor=SimpleNamespace(
            health={"main": SimpleNamespace(status="running", uptime_human="1m", restart_count=0)},
            stacks={"main": SimpleNamespace(is_main=True, config=SimpleNamespace(model="test-model", reasoning_effort=""))},
        ),
    )


def _write_state(tmp_path: Path, plan_id: str, payload: dict[str, object]) -> None:
    plan_dir = plan_dir_for(tmp_path / "plans", plan_id)
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "STATE.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_cmd_agents_run_creates_plan_workflow(tmp_path: Path) -> None:
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    key = SessionKey(transport="tg", chat_id=42)

    result = await cmd_agents(orch, key, "/agents run Build the new phased controller")

    assert "Started agent workflow." in result.text
    assert hub.submits
    submit = hub.submits[0]
    assert submit.workunit_kind == "plan_with_files"
    state = json.loads((plan_dir_for(tmp_path / "plans", "task-1") / "STATE.json").read_text())
    assert state["controller_mode"] == "agents_review_loop"
    assert state["status"] == "planning"
    assert state["source_chat_id"] == 42


@pytest.mark.asyncio
async def test_handle_task_result_autostarts_first_phase(tmp_path: Path) -> None:
    plan_id = "plan-1"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Plan",
        phases=(
            PlanPhase(
                id="phase-1",
                title="Contracts",
                workunit_kind="phase_execution",
                provider="claude",
                model="sonnet",
            ),
        ),
        status="ready_for_implementation",
    )
    _write_state(
        tmp_path,
        plan_id,
        {
            "schema_version": 1,
            "plan_id": plan_id,
            "status": "planning",
            "controller_mode": "agents_review_loop",
            "source_transport": "tg",
            "source_chat_id": 7,
            "repo": "/repo",
        },
    )
    entry = TaskEntry(
        task_id=plan_id,
        chat_id=7,
        parent_agent="main",
        name="plan",
        prompt_preview="",
        provider="codex",
        model="gpt-5.5",
        status="done",
        workunit_kind="plan_with_files",
        plan_id=plan_id,
    )
    hub = _FakeTaskHub(entry)
    orch = _make_orch(tmp_path, hub)

    note = await handle_task_result(
        orch,
        TaskResult(
            task_id=plan_id,
            chat_id=7,
            parent_agent="main",
            name="plan",
            prompt_preview="",
            result_text="ok",
            status="done",
            elapsed_seconds=1,
            provider="codex",
            model="gpt-5.5",
        ),
    )

    assert "Started phase `phase-1` automatically" in note
    assert hub.submits
    submit = hub.submits[0]
    assert submit.workunit_kind == "phase_execution"
    assert submit.plan_id == plan_id
    assert submit.phase_id == "phase-1"
    assert submit.provider_override == "claude"
    assert submit.model_override == "sonnet"
    state = json.loads((plan_dir_for(tmp_path / "plans", plan_id) / "STATE.json").read_text())
    assert state["status"] == "executing"
    assert state["current_phase_id"] == "phase-1"


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
    assert "- waiting_for: repair_feedback" in workflow_status_text(orch, plan_id)

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
    assert "[button:Approve|/agents approve plan-4]" in note
    assert "[button:Repair|/agents repair plan-4]" in note
    assert "[button:Status|/agents status plan-4]" in note


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

    text = workflow_status_text(orch, plan_id)

    assert "- main_inbox:" in text
    assert "task.done: Phase 1 worker completed with summarized result" in text
    assert "Unrelated plan result" not in text
