"""Production-Python oracle for tool-grant enforcement mapping."""

from __future__ import annotations

from controlmesh.execution_grants import (
    ToolGrantDenied,
    ToolGrantSnapshot,
    map_tool_grant,
)

SCHEMA_VERSION = "controlmesh.tool_grant_mapping_golden.v1"
REQUIRED_CASES = (
    "mapping.claude.deny_union",
    "mapping.claude.no_network_tools",
    "mapping.claude.allowlist_rejected",
    "mapping.claude.bypass_conflicts",
    "mapping.codex.network_toggle",
    "mapping.codex.read_only_network_floor",
    "mapping.codex.tool_deny_rejected",
    "mapping.codex.bypass_conflicts",
    "mapping.codex.full_access_conflict",
    "mapping.gemini.restrictive_rejected",
    "mapping.opencode.restrictive_rejected",
    "mapping.claw.surface_unproven",
    "mapping.openai_agents.surface_unproven",
    "mapping.floor.no_flags",
)

_DENY_WRITE_TOOLS = ToolGrantSnapshot(tool_deny=("Write", "Edit", "Bash"))
_NO_NETWORK = ToolGrantSnapshot(network_policy="no_network")
_ALLOW_ONLY = ToolGrantSnapshot(tool_allow=("Read", "Grep"))


def _case(
    case_id: str,
    provider: str,
    grant: ToolGrantSnapshot | None,
    *,
    config_allowed: tuple[str, ...] = (),
    config_disallowed: tuple[str, ...] = (),
    config_permission_mode: str = "",
    config_sandbox_mode: str = "",
) -> dict[str, object]:
    try:
        mapping = map_tool_grant(
            provider,
            grant,
            config_allowed=config_allowed,
            config_disallowed=config_disallowed,
            config_permission_mode=config_permission_mode,
            config_sandbox_mode=config_sandbox_mode,
        )
    except ToolGrantDenied as exc:
        return {
            "id": case_id,
            "provider": provider,
            "surface": "rejected",
            "flags": [],
            "denied_reason": exc.reason_code,
        }
    return {
        "id": case_id,
        "provider": provider,
        "surface": mapping.surface,
        "flags": list(mapping.flags),
        "denied_reason": "",
    }


def generate_matrix() -> dict[str, object]:
    """Generate the normalized grant-mapping matrix from production code."""
    cases = [
        _case(
            "mapping.claude.deny_union",
            "claude",
            _DENY_WRITE_TOOLS,
            config_disallowed=("mcp__internal__secrets",),
        ),
        _case("mapping.claude.no_network_tools", "claude", _NO_NETWORK),
        _case("mapping.claude.allowlist_rejected", "claude", _ALLOW_ONLY),
        _case(
            "mapping.claude.bypass_conflicts",
            "claude",
            _DENY_WRITE_TOOLS,
            config_permission_mode="bypassPermissions",
        ),
        _case(
            "mapping.codex.network_toggle",
            "codex",
            _NO_NETWORK,
            config_sandbox_mode="workspace-write",
        ),
        _case(
            "mapping.codex.read_only_network_floor",
            "codex",
            _NO_NETWORK,
            config_sandbox_mode="read-only",
        ),
        _case("mapping.codex.tool_deny_rejected", "codex", _DENY_WRITE_TOOLS),
        _case(
            "mapping.codex.bypass_conflicts",
            "codex",
            _NO_NETWORK,
            config_permission_mode="bypassPermissions",
        ),
        _case(
            "mapping.codex.full_access_conflict",
            "codex",
            _NO_NETWORK,
            config_sandbox_mode="full-access",
        ),
        _case("mapping.gemini.restrictive_rejected", "gemini", _DENY_WRITE_TOOLS),
        _case("mapping.opencode.restrictive_rejected", "opencode", _DENY_WRITE_TOOLS),
        _case("mapping.claw.surface_unproven", "claw", _DENY_WRITE_TOOLS),
        _case("mapping.openai_agents.surface_unproven", "openai_agents", _DENY_WRITE_TOOLS),
        _case(
            "mapping.floor.no_flags",
            "claude",
            ToolGrantSnapshot(confirmation_policy="controller_required"),
        ),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "production_owner": "python",
        "cases": cases,
    }
