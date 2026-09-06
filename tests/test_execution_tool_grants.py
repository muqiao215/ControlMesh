"""Tests for tool grant issuance, mapping, rejection, and persistence."""

from __future__ import annotations

import pytest

from controlmesh.cli.base import CLIConfig
from controlmesh.cli.codex_provider import CodexCLI
from controlmesh.cli.opencode_provider import OpenCodeCLI
from controlmesh.execution_grants import (
    ToolGrantDenied,
    ToolGrantSnapshot,
    issue_tool_grant,
    map_tool_grant,
)
from controlmesh.tasks.models import TaskEntry, TaskSubmit


def _deny_write() -> ToolGrantSnapshot:
    return ToolGrantSnapshot(tool_deny=("Write", "Edit", "Bash"))


def _grant_dict() -> dict[str, object]:
    return {
        "schema_version": "controlmesh.tool_grant.v1",
        "tool_allow": ["Read"],
        "tool_deny": ["Bash"],
        "network_policy": "no_network",
        "writable_roots": ["workspace/reports"],
        "confirmation_policy": "controller_required",
        "provider_surface": "claude_tool_flags",
        "reply_transport": "feishu",
        "reply_chat": "oc_chat_1",
        "reply_topic": "omt_1",
        "reply_thread": "om_1",
    }


class TestIssuance:
    def test_issue_normalizes_and_round_trips(self) -> None:
        grant = issue_tool_grant(
            tool_deny=["Bash", "Bash", "Write"],
            network_policy="no_network",
            confirmation_policy="controller_required",
            reply_transport="feishu",
            reply_chat="oc_1",
        )
        assert grant.tool_deny == ("Bash", "Write")
        assert ToolGrantSnapshot.from_dict(grant.to_dict()) == grant

    def test_no_secret_or_content_fields(self) -> None:
        grant = issue_tool_grant(tool_deny=("Bash",), reply_chat="oc_1")
        assert set(grant.to_dict()) == {
            "schema_version",
            "tool_allow",
            "tool_deny",
            "network_policy",
            "writable_roots",
            "confirmation_policy",
            "provider_surface",
            "reply_transport",
            "reply_chat",
            "reply_topic",
            "reply_thread",
        }

    def test_issue_rejects_unknown_surface_and_bad_tokens(self) -> None:
        with pytest.raises(ValueError, match="provider_surface"):
            issue_tool_grant(provider_surface="prompt_whitelist")
        with pytest.raises(ValueError, match="tool token"):
            issue_tool_grant(tool_deny=("rm -rf /*",))
        with pytest.raises(ValueError, match="writable root"):
            issue_tool_grant(writable_roots=("../../etc",))


class TestStrictParsing:
    def test_unknown_schema_version_fails_closed(self) -> None:
        raw = _grant_dict()
        raw["schema_version"] = "controlmesh.tool_grant.v2"
        with pytest.raises(ValueError, match="schema_version"):
            ToolGrantSnapshot.from_dict(raw)

    def test_invalid_enums_fail_closed(self) -> None:
        raw = _grant_dict()
        raw["network_policy"] = "host_open"
        with pytest.raises(ValueError, match="network_policy"):
            ToolGrantSnapshot.from_dict(raw)


class TestCrossProviderMapping:
    def test_claude_denies_are_unioned_with_config(self) -> None:
        mapping = map_tool_grant(
            "claude",
            _deny_write(),
            config_disallowed=("mcp__internal__secrets",),
        )
        assert mapping.surface == "claude_tool_flags"
        assert mapping.flags == ("--disallowedTools", "mcp__internal__secrets", "Write", "Edit", "Bash")

    def test_claude_no_network_is_rejected_without_isolation(self) -> None:
        with pytest.raises(ToolGrantDenied, match="no_network_unenforceable"):
            map_tool_grant("claude", ToolGrantSnapshot(network_policy="no_network"))

    def test_claude_override_conflicts_rejected(self) -> None:
        with pytest.raises(ToolGrantDenied, match="override_conflicts"):
            map_tool_grant(
                "claude",
                _deny_write(),
                config_cli_parameters=("--dangerously-skip-permissions",),
            )

    def test_restrictive_controller_required_is_rejected(self) -> None:
        grant = ToolGrantSnapshot(
            tool_deny=("Write",),
            confirmation_policy="controller_required",
        )
        with pytest.raises(ToolGrantDenied, match="controller_approval_unavailable"):
            map_tool_grant("claude", grant)
        with pytest.raises(ToolGrantDenied, match="controller_approval_unavailable"):
            map_tool_grant("codex", grant)

    def test_floor_controller_required_stays_legacy(self) -> None:
        mapping = map_tool_grant(
            "claude",
            ToolGrantSnapshot(confirmation_policy="controller_required"),
        )
        assert mapping.flags == ()

    def test_claude_allowlist_is_not_enforceable(self) -> None:
        with pytest.raises(ToolGrantDenied, match="allowlist"):
            map_tool_grant("claude", ToolGrantSnapshot(tool_allow=("Read",)))

    def test_claude_bypass_conflicts_with_restrictive_grant(self) -> None:
        with pytest.raises(ToolGrantDenied, match="bypass"):
            map_tool_grant(
                "claude",
                _deny_write(),
                config_permission_mode="bypassPermissions",
            )

    def test_codex_maps_network_toggle_on_workspace_write(self) -> None:
        mapping = map_tool_grant(
            "codex",
            ToolGrantSnapshot(network_policy="no_network"),
            config_sandbox_mode="workspace-write",
        )
        assert mapping.flags == ("-c", 'sandbox_workspace_write={"network_access": false}')

    def test_codex_read_only_sandbox_needs_no_extra_flag(self) -> None:
        mapping = map_tool_grant(
            "codex",
            ToolGrantSnapshot(network_policy="no_network"),
            config_sandbox_mode="read-only",
        )
        assert mapping.flags == ()

    def test_codex_rejects_tool_granularity_and_bypass_and_full_access(self) -> None:
        with pytest.raises(ToolGrantDenied, match="tool_granularity"):
            map_tool_grant("codex", _deny_write())
        with pytest.raises(ToolGrantDenied, match="bypass"):
            map_tool_grant(
                "codex",
                ToolGrantSnapshot(network_policy="no_network"),
                config_permission_mode="bypassPermissions",
            )
        with pytest.raises(ToolGrantDenied, match="full_access"):
            map_tool_grant(
                "codex",
                ToolGrantSnapshot(network_policy="no_network"),
                config_sandbox_mode="full-access",
            )

    def test_unproven_surfaces_reject_restrictive_grants(self) -> None:
        for provider in ("gemini", "opencode", "claw", "openai_agents"):
            with pytest.raises(ToolGrantDenied):
                map_tool_grant(provider, _deny_write())

    def test_floor_grant_maps_to_no_flags_for_every_provider(self) -> None:
        floor = ToolGrantSnapshot(confirmation_policy="controller_required")
        for provider in ("claude", "codex", "gemini", "opencode", "claw", "openai_agents"):
            mapping = map_tool_grant(provider, floor)
            assert mapping.flags == ()
            assert mapping.surface.endswith("_floor")

    def test_floor_grant_never_widens_static_config(self) -> None:
        mapping = map_tool_grant(
            "claude",
            ToolGrantSnapshot(),
            config_disallowed=("Bash",),
        )
        assert mapping.flags == ()


class TestAdapterEnforcement:
    def _config(self, **overrides: object) -> CLIConfig:
        overrides.setdefault("provider", "claude")
        return CLIConfig(
            docker_container="sandbox-1",
            working_dir="/tmp/wk",
            **overrides,
        )

    def test_claude_build_command_applies_grant_flags(self) -> None:
        from controlmesh.cli.claude_provider import ClaudeCodeCLI

        cli = ClaudeCodeCLI(self._config(permission_mode="default", tool_grant=_deny_write()))
        cmd = cli._build_command("hello")
        idx = cmd.index("--disallowedTools")
        assert cmd[idx + 1 : idx + 4] == ["Write", "Edit", "Bash"]

    def test_claude_build_command_rejects_before_launch(self) -> None:
        from controlmesh.cli.claude_provider import ClaudeCodeCLI

        cli = ClaudeCodeCLI(self._config(permission_mode="bypassPermissions", tool_grant=_deny_write()))
        with pytest.raises(ToolGrantDenied):
            cli._build_command("hello")

    def test_codex_build_command_applies_network_flag(self) -> None:
        cli = CodexCLI(
            self._config(
                provider="codex",
                permission_mode="default",
                sandbox_mode="workspace-write",
                tool_grant=ToolGrantSnapshot(network_policy="no_network"),
            )
        )
        cmd = cli._build_command("hello")
        assert 'sandbox_workspace_write={"network_access": false}' in cmd

    def test_opencode_build_command_rejects_restrictive_grant(self) -> None:
        cli = OpenCodeCLI(self._config(provider="opencode", tool_grant=_deny_write()))
        with pytest.raises(ToolGrantDenied, match="config_overlay_unverified"):
            cli._build_command("hello")


class TestPersistenceAndRecovery:
    def test_task_entry_round_trips_grant(self) -> None:
        entry = TaskEntry(
            task_id="task-1",
            chat_id=1,
            parent_agent="main",
            name="n",
            prompt_preview="p",
            tool_grant=ToolGrantSnapshot.from_dict(_grant_dict()),
        )
        restored = TaskEntry.from_dict(entry.to_dict())
        assert restored.tool_grant == entry.tool_grant

    def test_old_record_without_grant_loads_as_none(self) -> None:
        entry = TaskEntry(
            task_id="task-1",
            chat_id=1,
            parent_agent="main",
            name="n",
            prompt_preview="p",
        )
        raw = entry.to_dict()
        assert "tool_grant" in raw
        del raw["tool_grant"]
        restored = TaskEntry.from_dict(raw)
        assert restored.tool_grant is None

    def test_corrupt_grant_fails_closed(self) -> None:
        entry = TaskEntry(
            task_id="task-1",
            chat_id=1,
            parent_agent="main",
            name="n",
            prompt_preview="p",
        )
        raw = entry.to_dict()
        raw["tool_grant"] = {"schema_version": "controlmesh.tool_grant.v1", "tool_deny": ["bad token"]}
        with pytest.raises(ValueError, match="tool token"):
            TaskEntry.from_dict(raw)

    def test_submit_default_grant_is_none(self) -> None:
        submit = TaskSubmit(
            chat_id=1, prompt="p", message_id=1, thread_id=None, parent_agent="main"
        )
        assert submit.tool_grant is None

    def test_rebind_is_verbatim_across_round_trip(self) -> None:
        grant = ToolGrantSnapshot.from_dict(_grant_dict())
        entry = TaskEntry(
            task_id="task-1",
            chat_id=1,
            parent_agent="main",
            name="n",
            prompt_preview="p",
            tool_grant=grant,
        )
        restored = TaskEntry.from_dict(entry.to_dict())
        assert restored.tool_grant is not None
        assert restored.tool_grant.restrictive
        assert restored.tool_grant.tool_deny == grant.tool_deny
        assert restored.tool_grant.network_policy == grant.network_policy


class TestSubmitIssuanceAndReplyTarget:
    def test_submit_issuance_narrows_only(self) -> None:
        from controlmesh.execution_grants import issue_task_grant_for_submit

        grant = issue_task_grant_for_submit(
            source_scope="cron",
            requested_tool_deny=("Bash",),
            requested_no_network=False,
            transport="feishu",
            chat_id="oc_1",
        )
        assert grant.tool_deny == ("Bash",)
        assert grant.confirmation_policy == "controller_required"
        assert grant.reply_chat == "oc_1"
        assert not grant.tool_allow

    def test_trusted_local_scope_keeps_provider_runtime_floor(self) -> None:
        from controlmesh.execution_grants import issue_task_grant_for_submit

        grant = issue_task_grant_for_submit(
            source_scope="local_foreground",
            transport="feishu",
            chat_id="oc_1",
        )
        assert grant.confirmation_policy == "provider_runtime"
        assert not grant.restrictive

    def test_reply_target_mismatch_blocks_delivery(self) -> None:
        from controlmesh.errors import ControlMeshError
        from controlmesh.execution_grants import validate_reply_target

        grant = ToolGrantSnapshot(reply_transport="feishu", reply_chat="oc_1")
        validate_reply_target(grant, transport="feishu", chat_id="oc_1")
        with pytest.raises(ControlMeshError, match="reply_target_mismatch"):
            validate_reply_target(grant, transport="feishu", chat_id="oc_other")

    def test_legacy_grant_accepts_trusted_target(self) -> None:
        from controlmesh.execution_grants import validate_reply_target

        validate_reply_target(None, transport="feishu", chat_id="oc_1")
        validate_reply_target(
            ToolGrantSnapshot(), transport="feishu", chat_id="oc_1"
        )
