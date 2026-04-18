"""Compatibility shim for bundled feishu-auth-kit native tool prompt helpers."""

from controlmesh._plugins.feishu_auth_kit.feishu_auth_kit.native_agent_tools import (
    FeishuNativeAgentToolSelection,
    FeishuNativeAgentToolSpec,
    build_native_agent_tool_selection_prompt,
    build_tool_result_followup_prompt,
    native_agent_tool_specs,
    parse_native_agent_tool_selection,
)

__all__ = [
    "FeishuNativeAgentToolSelection",
    "FeishuNativeAgentToolSpec",
    "build_native_agent_tool_selection_prompt",
    "build_tool_result_followup_prompt",
    "native_agent_tool_specs",
    "parse_native_agent_tool_selection",
]
