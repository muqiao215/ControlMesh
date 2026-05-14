from __future__ import annotations

from pathlib import Path

import pytest

from controlmesh.multiagent.release_gate import build_release_host_job_spec
from controlmesh.multiagent.plan_review_loop import approve_current_phase, approve_phase
from controlmesh.multiagent.release_gate import ensure_publish_gate
from controlmesh.planning_files import PlanPhase, create_plan_files
from controlmesh.runtime import HostJob, HostJobStep
from controlmesh.session.key import SessionKey
from tests.multiagent.test_plan_review_loop import _FakeHostJobRunner, _FakeTaskHub, _make_orch, _write_state


def test_release_host_job_spec_contains_fixed_step_graph_and_verify_tag() -> None:
    spec = build_release_host_job_spec(
        plan_id="release-plan",
        repo="/repo",
        version="0.29.0",
        tag="v0.29.0",
        notes_file="docs/release-note-v0.29.0.md",
    )

    assert [step.id for step in spec.steps] == [
        "pytest_full",
        "uv_build",
        "verify_tag_local",
        "push_main",
        "push_tag",
        "verify_remote_tag",
    ]
    assert [step.id for step in spec.steps if step.approval_required] == [
        "push_main",
        "push_tag",
    ]
    assert spec.steps[5].command == "git ls-remote --tags origin v0.29.0"


@pytest.mark.asyncio
async def test_approve_only_current_host_step(tmp_path: Path) -> None:
    plan_id = "release-step-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(PlanPhase(id="publish", title="Publish Release", workunit_kind="github_release"),),
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
        version="0.29.0",
        commit="abc1234",
        tag="v0.29.0",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.29.0",
            "repo": "https://github.com/org/repo",
            "version": "0.29.0",
            "tag": "v0.29.0",
            "notes_file": "docs/release-note-v0.29.0.md",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
            job_id="release-v0.29.0",
            plan_id=plan_id,
            repo="https://github.com/org/repo",
            version="0.29.0",
            tag="v0.29.0",
            state="awaiting_approval",
            current_step_id="push_main",
            steps=[HostJobStep(id="push_main", title="push", command="git push origin main", state="awaiting_approval", approval_required=True)],
            )
        )
    )

    text = await approve_current_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id, "push_main")

    assert "Approved release step `push_main`" in text
    assert orch.host_job_runner.approvals == [("release-v0.29.0", "push_main", "tg:9")]


@pytest.mark.asyncio
async def test_approve_without_step_is_rejected_with_explicit_instruction(tmp_path: Path) -> None:
    plan_id = "release-step-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(PlanPhase(id="publish", title="Publish Release", workunit_kind="github_release"),),
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
        version="0.29.0",
        commit="abc1234",
        tag="v0.29.0",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.29.0",
            "repo": "https://github.com/org/repo",
            "version": "0.29.0",
            "tag": "v0.29.0",
            "notes_file": "docs/release-note-v0.29.0.md",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
            job_id="release-v0.29.0",
            plan_id=plan_id,
            repo="https://github.com/org/repo",
            version="0.29.0",
            tag="v0.29.0",
            state="awaiting_approval",
            current_step_id="push_main",
            steps=[HostJobStep(id="push_main", title="push", command="git push origin main", state="awaiting_approval", approval_required=True)],
            )
        )
    )

    text = await approve_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id)

    assert "Release approval requires an explicit step." in text
    assert "approve push_main release-v0.29.0" in text
    assert orch.host_job_runner.approvals == []


@pytest.mark.asyncio
async def test_push_tag_requires_separate_approval(tmp_path: Path) -> None:
    plan_id = "release-step-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(PlanPhase(id="publish", title="Publish Release", workunit_kind="github_release"),),
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
        version="0.29.0",
        commit="abc1234",
        tag="v0.29.0",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.29.0",
            "repo": "https://github.com/org/repo",
            "version": "0.29.0",
            "tag": "v0.29.0",
            "notes_file": "docs/release-note-v0.29.0.md",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
            job_id="release-v0.29.0",
            plan_id=plan_id,
            repo="https://github.com/org/repo",
            version="0.29.0",
            tag="v0.29.0",
            state="awaiting_approval",
            current_step_id="push_main",
            steps=[HostJobStep(id="push_main", title="push", command="git push origin main", state="awaiting_approval", approval_required=True)],
            )
        )
    )

    text = await approve_current_phase(orch, SessionKey(transport="tg", chat_id=9), plan_id, "push_tag")

    assert "waiting on release step `push_main`, not `push_tag`" in text
    assert orch.host_job_runner.approvals == []


@pytest.mark.asyncio
async def test_completed_release_job_does_not_reapprove_push_tag(tmp_path: Path) -> None:
    plan_id = "release-step-plan"
    create_plan_files(
        tmp_path / "plans",
        plan_id=plan_id,
        plan_markdown="# Release Plan",
        phases=(PlanPhase(id="publish", title="Publish Release", workunit_kind="github_release"),),
        status="executing",
        current_phase=1,
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
            "awaiting_review_phase_id": "",
            "source_transport": "tg",
            "source_chat_id": 9,
            "repo": "/repo",
        },
    )
    ensure_publish_gate(
        tmp_path / "plans",
        plan_id=plan_id,
        repo="https://github.com/org/repo",
        version="0.29.0",
        commit="abc1234",
        tag="v0.29.0",
        commands=["git push origin main"],
        requested_by_task="publish-task-1",
        host_job={
            "kind": "release",
            "job_id": "release-v0.29.0",
            "repo": "https://github.com/org/repo",
            "version": "0.29.0",
            "tag": "v0.29.0",
            "notes_file": "docs/release-note-v0.29.0.md",
        },
    )
    hub = _FakeTaskHub()
    orch = _make_orch(tmp_path, hub)
    orch.host_job_runner = (
        _FakeHostJobRunner(
            HostJob(
            job_id="release-v0.29.0",
            plan_id=plan_id,
            repo="https://github.com/org/repo",
            version="0.29.0",
            tag="v0.29.0",
            state="running",
            current_step_id="verify_remote_tag",
            steps=[HostJobStep(id="verify_remote_tag", title="verify", command="git ls-remote --tags origin v0.29.0", state="completed")],
            )
        )
    )

    text = await approve_current_phase(
        orch,
        SessionKey(transport="tg", chat_id=9),
        plan_id,
        "push_tag",
    )

    assert "not currently waiting on release step `push_tag`" in text
    assert orch.host_job_runner.approvals == []
