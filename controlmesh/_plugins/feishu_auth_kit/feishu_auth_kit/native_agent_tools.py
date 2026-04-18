from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class FeishuNativeAgentToolSpec:
    """Small agent-facing description for one native Feishu tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    required_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeishuNativeAgentToolSelection:
    """A model-selected Feishu native tool call."""

    tool_name: str
    arguments: dict[str, Any]
    reason: str = ""


def native_agent_tool_specs() -> tuple[FeishuNativeAgentToolSpec, ...]:
    """Return the current native Feishu tools exposed to the agent selector."""
    return (
        FeishuNativeAgentToolSpec(
            name="contact.search_user",
            description="Search Feishu contacts by a human query.",
            parameters={"query": "string", "page_size": "integer optional"},
            required_scopes=("contact:user:search",),
        ),
        FeishuNativeAgentToolSpec(
            name="contact.get_user",
            description="Read one Feishu user's profile by open_id, union_id, or user_id.",
            parameters={"user_id": "string", "user_id_type": "open_id|union_id|user_id optional"},
            required_scopes=(
                "contact:contact.base:readonly",
                "contact:user.base:readonly",
            ),
        ),
        FeishuNativeAgentToolSpec(
            name="im.get_messages",
            description="Read recent messages from a known Feishu chat_id.",
            parameters={"chat_id": "string", "page_size": "integer optional"},
            required_scopes=(
                "im:chat:read",
                "im:message:readonly",
                "im:message.group_msg:get_as_user",
                "im:message.p2p_msg:get_as_user",
            ),
        ),
        FeishuNativeAgentToolSpec(
            name="drive.list_files",
            description="List files from Feishu Drive root or a known folder_token.",
            parameters={
                "folder_token": "string optional",
                "page_size": "integer optional",
                "page_token": "string optional",
            },
            required_scopes=("space:document:retrieve",),
        ),
    )


def get_native_agent_tool_spec(tool_name: str) -> FeishuNativeAgentToolSpec | None:
    """Return one native tool spec by name."""
    for spec in native_agent_tool_specs():
        if spec.name == tool_name:
            return spec
    return None


def native_user_auth_scopes() -> tuple[str, ...]:
    """Return the deduped user-scope set needed by current native Feishu tools."""
    deduped: dict[str, None] = {"offline_access": None}
    for spec in native_agent_tool_specs():
        for scope in spec.required_scopes:
            deduped.setdefault(scope, None)
    return tuple(deduped)


def build_native_agent_tool_selection_prompt(
    *,
    user_text: str,
    inbound_context: Mapping[str, Any],
) -> str:
    """Build a compact one-shot prompt asking the model to choose a native tool."""
    tools = "\n".join(
        (
            f"- {spec.name}: {spec.description} "
            f"parameters={json.dumps(spec.parameters, ensure_ascii=False, sort_keys=True)}"
        )
        for spec in native_agent_tool_specs()
    )
    context_json = json.dumps(dict(inbound_context), ensure_ascii=False, sort_keys=True)
    return (
        "You are the Feishu native tool selector.\n"
        "Choose exactly one tool only when it directly helps answer the user. "
        "Never guess IDs that are not present in the user message or inbound context.\n\n"
        "Available tools:\n"
        f"{tools}\n\n"
        "Return JSON only, no markdown:\n"
        '{"tool_name":"contact.search_user","arguments":{"query":"Alice"},"reason":"optional"}\n'
        'or {"tool_name":"none","arguments":{},"reason":"no useful native tool"}\n\n'
        f"Inbound context JSON:\n{context_json}\n\n"
        f"User message:\n{user_text}"
    )


def parse_native_agent_tool_selection(text: str) -> FeishuNativeAgentToolSelection | None:
    """Parse and validate a model tool-selection response."""
    payload = _extract_json_object(text)
    if payload is None:
        return None
    tool_name = str(payload.get("tool_name") or "").strip()
    if not tool_name or tool_name == "none":
        return None
    allowed = {spec.name for spec in native_agent_tool_specs()}
    if tool_name not in allowed:
        return None
    arguments = payload.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    return FeishuNativeAgentToolSelection(
        tool_name=tool_name,
        arguments={str(key): value for key, value in arguments.items()},
        reason=str(payload.get("reason") or ""),
    )


def build_tool_result_followup_prompt(
    *,
    original_text: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> str:
    """Build the main agent prompt after a native tool result is available."""
    payload = {"tool_name": tool_name, "arguments": arguments, "result": result}
    return (
        "A Feishu native tool was executed before this response.\n\n"
        f"Original user message:\n{original_text}\n\n"
        "Feishu native tool result:\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n"
        "```\n\n"
        "Answer the user directly using the tool result. "
        "Do not emit another Feishu native tool selection JSON."
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    candidate = fence.group(1) if fence else stripped
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
