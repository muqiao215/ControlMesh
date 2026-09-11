"""Live one-shot owner oracle. Binary lookup is mocked; no provider/model is invoked."""

from __future__ import annotations

import json
from dataclasses import asdict
from itertools import product
from unittest.mock import patch

from controlmesh.cli.param_resolver import TaskExecutionConfig
from controlmesh.cron.execution import UnsupportedOneShotProviderError, build_cmd, observe_one_shot
from controlmesh.execution_grants import ToolGrantDenied, ToolGrantSnapshot


def cases() -> list[dict]:
    results: list[dict] = []
    grants = [
        None,
        ToolGrantSnapshot(tool_deny=("bash",)),
        ToolGrantSnapshot(network_policy="no_network"),
        ToolGrantSnapshot(confirmation_policy="controller_required"),
    ]
    for provider, mode, uid, force, grant in product(
        ["claude", "codex", "gemini", "opencode", "claw"],
        ["bypassPermissions", "dontAsk", "read-only"],
        [0, 1000],
        [True, False],
        grants,
    ):
        config = {
            "provider": provider,
            "model": "fixture/model",
            "permission_mode": mode,
            "reasoning_effort": "high",
            "cli_parameters": ["--fixture", "value with spaces"],
            "claude_root_permission_mode": "dontAsk",
            "claude_root_force_bypass_via_is_sandbox": force,
        }
        prompt = '准确保留换行\n"quotes" and $(literal)'
        with (
            patch("controlmesh.cron.execution.which", return_value=f"/fixture/{provider}"),
            patch("controlmesh.cron.execution.find_gemini_cli", return_value="/fixture/gemini"),
            patch("controlmesh.cron.execution.os.geteuid", return_value=uid),
        ):
            try:
                command = build_cmd(
                    TaskExecutionConfig(
                        **config, working_dir="/fixture", file_access="all", tool_grant=grant
                    ),
                    prompt,
                )
                assert command is not None
                output = {
                    "command": command.cmd,
                    "stdin_text": command.stdin_input.decode()
                    if command.stdin_input is not None
                    else None,
                    "env_overrides": command.env_overrides,
                }
            except ToolGrantDenied as exc:
                output = {"denied_reason": exc.reason_code}
        results.append(
            {
                "kind": "command",
                "config": config,
                "executable": f"/fixture/{provider}",
                "prompt": prompt,
                "uid": uid,
                "grant": grant.to_dict() if grant else None,
                "output": output,
            }
        )
    streams = [
        [],
        [{"result": "answer"}],
        [{"response": "答案"}],
        [{"type": "message", "role": "model", "content": "answer"}],
        [{"result": "partial", "is_error": True}],
        [{"error": {"message": "failed"}}],
        [None],
        [42],
        ["string"],
        [{"type": "tool_result", "content": "insufficient_quota"}],
        [{"result": "usage limit reached; quoted prose"}],
        [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
            {"type": "turn.completed"},
        ],
        [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "partial"}},
            {"type": "turn.failed", "error": {"message": "failed"}},
        ],
        [
            {"type": "text", "sessionID": "ses_Fixture", "part": {"text": "answer"}},
            {"type": "step_finish", "sessionID": "ses_Fixture", "part": {"reason": "stop"}},
        ],
        [
            {"type": "text", "sessionID": "ses_Fixture", "part": {"text": "answer"}},
            {"type": "step_finish", "sessionID": "ses_Other", "part": {"reason": "stop"}},
        ],
        [
            {"type": "text", "sessionID": "ses_Fixture", "part": {"text": "answer"}},
            {"type": "step_finish", "sessionID": "ses_Fixture", "part": {"reason": "tool-calls"}},
        ],
        [
            {
                "type": "error",
                "error": {
                    "data": {"message": "insufficient_quota; resets at 2026-09-12 01:00:00+08:00"}
                },
            }
        ],
    ]
    for provider, events in product(["claude", "codex", "gemini", "opencode", "claw"], streams):
        results.extend(
            {
                "kind": "observation",
                "provider": provider,
                "stdout": raw,
                "stderr": "",
                "output": asdict(observe_one_shot(provider, raw.encode(), b"")),
            }
            for raw in (json.dumps(events), "\n".join(json.dumps(event) for event in events))
        )
    for provider in ["openai_agents", "unknown"]:
        with patch("controlmesh.cron.execution.which") as lookup:
            try:
                build_cmd(
                    TaskExecutionConfig(
                        provider=provider,
                        model="fixture",
                        reasoning_effort="",
                        cli_parameters=[],
                        permission_mode="dontAsk",
                        working_dir="/fixture",
                        file_access="all",
                    ),
                    "fixture",
                )
            except UnsupportedOneShotProviderError:
                pass
            else:
                raise AssertionError("unsupported provider did not reject")
            lookup.assert_not_called()
    return results


if __name__ == "__main__":
    print(json.dumps(cases(), ensure_ascii=False))
