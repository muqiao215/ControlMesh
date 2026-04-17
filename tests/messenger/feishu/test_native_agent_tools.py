"""Tests for Feishu native agent-tool selection and prompt plumbing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from controlmesh.cli.types import AgentResponse
from controlmesh.messenger.feishu.bot import FeishuIncomingText
from controlmesh.messenger.feishu.native_tools.agent_runtime import (
    build_tool_result_followup_prompt,
    parse_native_agent_tool_selection,
)

from .test_bot import _make_bot


def test_parse_native_agent_tool_selection_accepts_json_object() -> None:
    selection = parse_native_agent_tool_selection(
        '{"tool_name":"contact.search_user","arguments":{"query":"Alice"}}'
    )

    assert selection is not None
    assert selection.tool_name == "contact.search_user"
    assert selection.arguments == {"query": "Alice"}


def test_parse_native_agent_tool_selection_rejects_unknown_tool() -> None:
    assert parse_native_agent_tool_selection('{"tool_name":"unknown","arguments":{}}') is None
    assert parse_native_agent_tool_selection('{"tool_name":"none","arguments":{}}') is None


def test_build_tool_result_followup_prompt_includes_original_request_and_result() -> None:
    prompt = build_tool_result_followup_prompt(
        original_text="帮我找 Alice",
        tool_name="contact.search_user",
        arguments={"query": "Alice"},
        result={"users": [{"name": "Alice"}]},
    )

    assert "帮我找 Alice" in prompt
    assert "contact.search_user" in prompt
    assert '"Alice"' in prompt
    assert "Do not emit another Feishu native tool selection JSON" in prompt


async def test_bot_native_agent_tool_selection_executes_before_final_agent_turn(
    tmp_path: Path,
) -> None:
    bot = _make_bot(tmp_path, runtime_mode="native")
    bot._send_plain_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
    bot._send_text_to_chat_ref = AsyncMock()  # type: ignore[method-assign]
    bot._native_tool_executor = SimpleNamespace(
        execute=AsyncMock(return_value={"users": [{"name": "Alice", "open_id": "ou_alice"}]})
    )
    bot._orchestrator = SimpleNamespace(
        cli_service=SimpleNamespace(
            execute=AsyncMock(
                return_value=AgentResponse(
                    result='{"tool_name":"contact.search_user","arguments":{"query":"Alice"}}'
                )
            )
        ),
        handle_message_streaming=AsyncMock(return_value=SimpleNamespace(text="Alice 是 ou_alice")),
    )

    await bot.handle_incoming_text(
        FeishuIncomingText(
            sender_id="ou_sender",
            chat_id="oc_chat_1",
            message_id="om_1",
            text="帮我查一下 Alice",
        )
    )

    bot._orchestrator.cli_service.execute.assert_awaited_once()
    bot._native_tool_executor.execute.assert_awaited_once()
    tool_call = bot._native_tool_executor.execute.await_args
    assert tool_call.args[0] == "contact.search_user"
    assert tool_call.args[1] == {"query": "Alice"}
    final_prompt = bot._orchestrator.handle_message_streaming.await_args.args[1]
    assert "Feishu native tool result" in final_prompt
    assert "ou_alice" in final_prompt
    assert bot._send_text_to_chat_ref.await_args_list[-1].args[:2] == (
        "oc_chat_1",
        "Alice 是 ou_alice",
    )
    assert bot._send_text_to_chat_ref.await_args_list[-1].kwargs == {
        "reply_to_message_id": "om_1"
    }
