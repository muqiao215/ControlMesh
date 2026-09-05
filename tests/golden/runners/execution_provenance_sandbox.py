"""Production-Python oracle for source-aware execution admission."""

from __future__ import annotations

import asyncio
from pathlib import Path

from controlmesh.bus.envelope import ExecutionContext, Origin, SourceScope
from controlmesh.cli.param_resolver import TaskExecutionConfig
from controlmesh.execution_policy import ExecutionPolicyDenied, evaluate_execution_policy
from controlmesh.infra.task_runner import run_oneshot_task

SCHEMA_VERSION = "controlmesh.execution_provenance_sandbox_golden.v1"
REQUIRED_CASES = (
    "policy.local_foreground_host_compatibility",
    "policy.direct_message_host_compatibility",
    "policy.group_message_fail_closed",
    "policy.bot_handoff_fail_closed",
    "policy.api_fail_closed",
    "policy.cron_fail_closed",
    "policy.webhook_fail_closed",
    "policy.heartbeat_fail_closed",
    "policy.group_message_sandbox_ready",
    "boundary.denial_before_provider_command",
)


def _context(scope: SourceScope, origin: Origin) -> ExecutionContext:
    return ExecutionContext.issue(
        origin=origin,
        source_scope=scope,
        transport="golden",
        source_id=scope.value,
    )


def _normalized(decision: object) -> dict[str, object]:
    payload = decision.to_dict()  # type: ignore[union-attr]
    # Trace/source refs are intentionally opaque runtime identifiers.  The
    # golden gate compares policy semantics, never paths, prompts, or IDs.
    payload["trace_id"] = "<generated>"
    payload["source_ref"] = "<hashed>"
    return payload


def _config(context: ExecutionContext, *, docker_container: str = "") -> TaskExecutionConfig:
    return TaskExecutionConfig(
        provider="codex",
        model="gpt-5-codex",
        reasoning_effort="",
        cli_parameters=[],
        permission_mode="",
        working_dir="/workspace",
        file_access="workspace",
        docker_container=docker_container,
        execution_context=context,
    )


async def _denial_before_command() -> dict[str, object]:
    """Use the real one-shot boundary and prove command construction is skipped."""
    import controlmesh.cron.execution as execution_module

    called = False
    original = execution_module.build_cmd

    def marker(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        return original(*args, **kwargs)

    execution_module.build_cmd = marker  # type: ignore[assignment]
    try:
        try:
            await run_oneshot_task(
                _config(_context(SourceScope.GROUP_MESSAGE, Origin.USER)),
                "golden prompt",
                cwd=Path("task"),
                timeout_seconds=1,
                timeout_label="golden",
            )
        except ExecutionPolicyDenied as exc:
            return {
                "id": "boundary.denial_before_provider_command",
                "accepted": False,
                "reason_code": exc.decision.reason_code,
                "build_cmd_called": called,
                "provider_process_started": False,
            }
        raise AssertionError("required sandbox denial unexpectedly succeeded")
    finally:
        execution_module.build_cmd = original


def generate_matrix() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    policy_cases = (
        ("policy.local_foreground_host_compatibility", SourceScope.LOCAL_FOREGROUND, Origin.USER, False),
        ("policy.direct_message_host_compatibility", SourceScope.DIRECT_MESSAGE, Origin.USER, False),
        ("policy.group_message_fail_closed", SourceScope.GROUP_MESSAGE, Origin.USER, False),
        ("policy.bot_handoff_fail_closed", SourceScope.BOT_HANDOFF, Origin.INTERAGENT, False),
        ("policy.api_fail_closed", SourceScope.API, Origin.API, False),
        ("policy.cron_fail_closed", SourceScope.CRON, Origin.CRON, False),
        ("policy.webhook_fail_closed", SourceScope.WEBHOOK, Origin.WEBHOOK_CRON, False),
        ("policy.heartbeat_fail_closed", SourceScope.HEARTBEAT, Origin.HEARTBEAT, False),
        ("policy.group_message_sandbox_ready", SourceScope.GROUP_MESSAGE, Origin.USER, True),
    )
    for case_id, scope, origin, sandbox_available in policy_cases:
        decision = evaluate_execution_policy(
            _context(scope, origin),
            sandbox_available=sandbox_available,
        )
        cases.append({"id": case_id, "accepted": decision.outcome == "accepted", "decision": _normalized(decision)})

    cases.append(asyncio.run(_denial_before_command()))
    order = {case_id: index for index, case_id in enumerate(REQUIRED_CASES)}
    cases.sort(key=lambda case: order[str(case["id"])])
    return {
        "schema_version": SCHEMA_VERSION,
        "production_owner": "python",
        "identity_fields": ["trace_id", "origin", "source_scope", "transport", "source_ref"],
        "cases": cases,
    }
