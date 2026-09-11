"""Live Python input/output oracle for the TS runtime authorization port.

No provider process, operator store, network request or generated fixture is used.
The matrix calls current production owners, rather than duplicating their logic.
"""

from __future__ import annotations

import itertools
import json

from controlmesh.bus.envelope import ExecutionContext, Origin, SourceScope
from controlmesh.execution_grants import (
    ReplyTargetMismatch,
    ToolGrantDenied,
    ToolGrantSnapshot,
    issue_task_grant_for_submit,
    map_tool_grant,
    validate_reply_target,
)
from controlmesh.execution_policy import evaluate_execution_policy


def generate_cases() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    for origin, scope, sandbox in itertools.product(Origin, SourceScope, (False, True)):
        context = ExecutionContext("a" * 32, origin, scope, "oracle", "b" * 24)
        cases.append(
            {
                "kind": "policy",
                "input": {"context": context.to_dict(), "sandbox_available": sandbox},
                "output": evaluate_execution_policy(context, sandbox_available=sandbox).to_dict(),
            }
        )
    grants = (
        None,
        ToolGrantSnapshot(),
        ToolGrantSnapshot(tool_deny=("Write", "Edit", "Bash")),
        ToolGrantSnapshot(tool_allow=("Read", "Grep")),
        ToolGrantSnapshot(network_policy="no_network"),
        ToolGrantSnapshot(writable_roots=("workspace/source",)),
        ToolGrantSnapshot(confirmation_policy="controller_required"),
        ToolGrantSnapshot(tool_deny=("Write",), confirmation_policy="controller_required"),
    )
    configurations = (
        {},
        {"config_disallowed": ["mcp__internal__secrets", "Write"]},
        {"config_disallowed": ["Bash(rm *)", "Read(**/.env)"]},
        {"config_permission_mode": "bypassPermissions"},
        {"config_sandbox_mode": "workspace-write"},
        {"config_sandbox_mode": "read-only"},
        {"config_sandbox_mode": "full-access"},
        {"config_cli_parameters": ["--dangerously-skip-permissions"]},
        {"config_cli_parameters": ["-c", 'sandbox_workspace_write={"network_access": true}']},
    )
    for provider, grant, config in itertools.product(
        ("claude", "codex", "gemini", "opencode", "claw", "openai_agents"), grants, configurations
    ):
        output: dict[str, object]
        try:
            mapped = map_tool_grant(provider, grant, **config)  # type: ignore[arg-type]
            output = {
                "provider": mapped.provider,
                "surface": mapped.surface,
                "flags": list(mapped.flags),
            }
        except ToolGrantDenied as exc:
            output = {"denied_reason": exc.reason_code}
        cases.append(
            {
                "kind": "mapping",
                "input": {
                    "provider": provider,
                    "grant": grant.to_dict() if grant else None,
                    "config": config,
                },
                "output": output,
            }
        )
    for scope, network in itertools.product(SourceScope, (False, True)):
        source = {
            "source_scope": scope.value,
            "requested_tool_deny": ["Bash", "Bash", "Write"],
            "requested_no_network": network,
            "transport": "oracle",
            "chat_id": "chat",
            "topic_id": "topic",
            "thread_id": "thread",
        }
        cases.append(
            {
                "kind": "submit",
                "input": source,
                "output": issue_task_grant_for_submit(**source).to_dict(),  # type: ignore[arg-type]
            }
        )
    pinned = ToolGrantSnapshot(
        reply_transport="feishu", reply_chat="chat", reply_topic="topic", reply_thread="thread"
    )
    for grant, changed in itertools.product(
        (None, ToolGrantSnapshot(), pinned), ("", "transport", "chat_id", "topic_id", "thread_id")
    ):
        target = {
            "transport": "feishu",
            "chat_id": "chat",
            "topic_id": "topic",
            "thread_id": "thread",
        }
        if changed:
            target[changed] = "other"
        output = {"accepted": True}
        try:
            validate_reply_target(grant, **target)
        except ReplyTargetMismatch as exc:
            output = {"accepted": False, "field": exc.field}
        cases.append(
            {
                "kind": "reply",
                "input": {"grant": grant.to_dict() if grant else None, "target": target},
                "output": output,
            }
        )
    return cases


if __name__ == "__main__":
    print(json.dumps(generate_cases(), ensure_ascii=False, separators=(",", ":")))
