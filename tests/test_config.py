"""Tests for config and model registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from controlmesh.config import (
    AgentConfig,
    CodexHooksConfig,
    DockerConfig,
    ModelRegistry,
    QQBotAccountConfig,
    QQBotConfig,
    StreamingConfig,
    WeixinConfig,
    deep_merge_config,
    reset_gemini_models,
)
from controlmesh.gateways.config import (
    GatewayDispatchConfig,
    GatewayEventRuleConfig,
    GatewayTargetConfig,
)
from controlmesh.team.contracts import TEAM_TOPOLOGIES

# -- AgentConfig defaults --


@pytest.fixture(autouse=True)
def _reset_gemini_models() -> None:
    reset_gemini_models()


def test_agent_config_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.provider == "claude"
    assert cfg.model == "opus"
    assert cfg.idle_timeout_minutes == 1440
    assert cfg.daily_reset_hour == 4
    assert cfg.cli_timeout == 1800.0
    assert cfg.permission_mode == "bypassPermissions"
    assert cfg.gemini_api_key is None
    assert cfg.telegram_token == ""
    assert cfg.allowed_user_ids == []
    assert cfg.codex_hooks == CodexHooksConfig()
    assert cfg.gateways == GatewayDispatchConfig()


def test_config_example_validates_against_agent_config() -> None:
    payload = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
    cfg = AgentConfig.model_validate(payload)
    assert cfg.api.token == ""
    assert cfg.gateways.events["ask-user-question"].enabled is False


def test_agent_config_normalizes_nullish_gemini_api_key() -> None:
    assert AgentConfig(gemini_api_key="null").gemini_api_key is None
    assert AgentConfig(gemini_api_key=" NONE ").gemini_api_key is None
    assert AgentConfig(gemini_api_key="   ").gemini_api_key is None


def test_agent_config_streaming_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.streaming.enabled is True
    assert cfg.streaming.output_mode == "conversation"
    assert cfg.streaming.tool_display == "name"
    assert cfg.streaming.min_chars == 200
    assert cfg.streaming.max_chars == 1200
    assert cfg.streaming.edit_interval_seconds == 3.0


def test_agent_config_docker_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.docker.enabled is False
    assert cfg.docker.image_name == "controlmesh-sandbox"


def test_agent_config_rejects_invalid_types() -> None:
    with pytest.raises(ValidationError, match="idle_timeout_minutes"):
        AgentConfig(idle_timeout_minutes="not_a_number")  # type: ignore[arg-type]


# -- deep_merge_config --


def test_deep_merge_adds_new_keys() -> None:
    user: dict[str, object] = {"model": "sonnet"}
    defaults: dict[str, object] = {"model": "opus", "provider": "claude"}
    merged, changed = deep_merge_config(user, defaults)
    assert merged["model"] == "sonnet"
    assert merged["provider"] == "claude"
    assert changed is True


def test_deep_merge_preserves_user_values() -> None:
    user: dict[str, object] = {"model": "sonnet", "provider": "codex"}
    defaults: dict[str, object] = {"model": "opus", "provider": "claude"}
    merged, changed = deep_merge_config(user, defaults)
    assert merged["model"] == "sonnet"
    assert merged["provider"] == "codex"
    assert changed is False


def test_deep_merge_nested() -> None:
    user: dict[str, object] = {"streaming": {"enabled": False}}
    defaults: dict[str, object] = {"streaming": {"enabled": True, "min_chars": 200}}
    merged, changed = deep_merge_config(user, defaults)
    streaming = merged["streaming"]
    assert isinstance(streaming, dict)
    assert streaming["enabled"] is False
    assert streaming["min_chars"] == 200
    assert changed is True


def test_deep_merge_no_change() -> None:
    data: dict[str, object] = {"a": 1, "b": 2}
    defaults: dict[str, object] = {"a": 99, "b": 99}
    _, changed = deep_merge_config(data, defaults)
    assert changed is False


# -- ModelRegistry --


def test_registry_provider_for_claude() -> None:
    reg = ModelRegistry()
    assert reg.provider_for("opus") == "claude"
    assert reg.provider_for("sonnet") == "claude"
    assert reg.provider_for("haiku") == "claude"


def test_registry_provider_for_codex() -> None:
    reg = ModelRegistry()
    assert reg.provider_for("gpt-5.2-codex") == "codex"
    assert reg.provider_for("gpt-5.3-codex") == "codex"
    assert reg.provider_for("o3") == "codex"


def test_registry_provider_for_gemini_prefix() -> None:
    reg = ModelRegistry()
    reset_gemini_models()
    assert reg.provider_for("gemini-2.5-pro") == "gemini"


def test_streaming_config_fields() -> None:
    s = StreamingConfig(
        enabled=False,
        output_mode="conversation",
        tool_display="details",
        min_chars=100,
    )
    assert s.enabled is False
    assert s.output_mode == "conversation"
    assert s.tool_display == "details"
    assert s.min_chars == 100


def test_streaming_config_rejects_unknown_output_mode() -> None:
    with pytest.raises(ValidationError, match="output_mode"):
        StreamingConfig(output_mode="verbose")  # type: ignore[arg-type]


def test_streaming_config_rejects_unknown_tool_display() -> None:
    with pytest.raises(ValidationError, match="tool_display"):
        StreamingConfig(tool_display="raw")  # type: ignore[arg-type]


def test_docker_config_fields() -> None:
    d = DockerConfig(enabled=True, image_name="custom")
    assert d.enabled is True
    assert d.image_name == "custom"


# -- AgentConfig transports normalization --


def test_transport_backward_compat_populates_transports() -> None:
    """Legacy single ``transport`` field fills ``transports`` list."""
    cfg = AgentConfig(transport="telegram")
    assert cfg.transports == ["telegram"]
    assert cfg.transport == "telegram"


def test_transport_matrix_backward_compat() -> None:
    """transport='matrix' with empty transports normalizes correctly."""
    cfg = AgentConfig(transport="matrix")
    assert cfg.transports == ["matrix"]
    assert cfg.transport == "matrix"


def test_transport_feishu_backward_compat() -> None:
    """transport='feishu' with empty transports normalizes correctly."""
    cfg = AgentConfig(transport="feishu")
    assert cfg.transports == ["feishu"]
    assert cfg.transport == "feishu"
    assert cfg.feishu.mode == "bot_only"
    assert cfg.feishu.progress_mode == "text"


def test_feishu_progress_mode_accepts_card_stream() -> None:
    cfg = AgentConfig(
        transport="feishu",
        feishu={"runtime_mode": "native", "progress_mode": "card_stream"},
    )

    assert cfg.feishu.progress_mode == "card_stream"


def test_feishu_card_stream_requires_native_runtime_mode() -> None:
    with pytest.raises(ValueError, match="runtime_mode='native'"):
        AgentConfig(
            transport="feishu",
            feishu={"runtime_mode": "bridge", "progress_mode": "card_stream"},
        )


@pytest.mark.parametrize("topology", TEAM_TOPOLOGIES)
def test_tasks_default_topology_accepts_approved_values(topology: str) -> None:
    cfg = AgentConfig(tasks={"default_topology": topology})

    assert cfg.tasks.default_topology == topology


def test_tasks_default_topology_rejects_unapproved_values() -> None:
    with pytest.raises(ValidationError, match="default_topology"):
        AgentConfig(tasks={"default_topology": "auto"})


def test_transport_weixin_backward_compat() -> None:
    """transport='weixin' with empty transports normalizes correctly."""
    cfg = AgentConfig(transport="weixin")
    assert cfg.transports == ["weixin"]
    assert cfg.transport == "weixin"
    assert cfg.weixin == WeixinConfig()
    assert cfg.weixin.mode == "ilink"
    assert cfg.weixin.enabled is False


def test_transport_qqbot_backward_compat() -> None:
    cfg = AgentConfig(transport="qqbot")
    assert cfg.transports == ["qqbot"]
    assert cfg.transport == "qqbot"
    assert cfg.qqbot == QQBotConfig()


def test_qqbot_account_config_fields() -> None:
    cfg = QQBotAccountConfig(
        app_id="1903891442",
        client_secret="secret",
        allow_from=["user-a"],
        group_allow_from=["group-a"],
        dm_policy="allowlist",
        group_policy="disabled",
        group_message_mode="mention_patterns",
        mention_patterns=["ControlMesh", "@CM"],
        activate_on_bot_reply=True,
    )
    assert cfg.app_id == "1903891442"
    assert cfg.client_secret == "secret"
    assert cfg.allow_from == ["user-a"]
    assert cfg.group_allow_from == ["group-a"]
    assert cfg.dm_policy == "allowlist"
    assert cfg.group_policy == "disabled"
    assert cfg.group_message_mode == "mention_patterns"
    assert cfg.mention_patterns == ["ControlMesh", "@CM"]
    assert cfg.activate_on_bot_reply is True


def test_qqbot_config_accepts_accounts_mapping() -> None:
    cfg = AgentConfig(
        transport="qqbot",
        qqbot={
            "app_id": "1903891442",
            "client_secret": "secret",
            "accounts": {
                "bot2": {
                    "app_id": "1903891443",
                    "client_secret_file": "/tmp/qqbot-secret.txt",
                }
            },
        },
    )
    assert cfg.qqbot.app_id == "1903891442"
    assert cfg.qqbot.accounts["bot2"].app_id == "1903891443"
    assert cfg.qqbot.accounts["bot2"].client_secret_file == "/tmp/qqbot-secret.txt"


def test_api_config_accepts_string_chat_ref() -> None:
    cfg = AgentConfig(api={"chat_id": "qqbot:c2c:OPENID"})
    assert cfg.api.chat_id == "qqbot:c2c:OPENID"


def test_transports_multi_sets_primary_transport() -> None:
    """Explicit multi-transport sets ``transport`` to first entry."""
    cfg = AgentConfig(transports=["telegram", "matrix"])
    assert cfg.transports == ["telegram", "matrix"]
    assert cfg.transport == "telegram"


def test_transports_multi_reversed_order() -> None:
    """Primary transport is always the first in the list."""
    cfg = AgentConfig(transports=["matrix", "telegram"])
    assert cfg.transport == "matrix"


def test_is_multi_transport_single() -> None:
    cfg = AgentConfig(transport="telegram")
    assert cfg.is_multi_transport is False


def test_is_multi_transport_multiple() -> None:
    cfg = AgentConfig(transports=["telegram", "matrix"])
    assert cfg.is_multi_transport is True


def test_transports_default_is_telegram() -> None:
    """Default AgentConfig has transports=['telegram']."""
    cfg = AgentConfig()
    assert cfg.transports == ["telegram"]
    assert cfg.is_multi_transport is False


def test_gateway_target_command_requires_command() -> None:
    with pytest.raises(ValidationError, match="command gateways require a non-empty command"):
        GatewayTargetConfig(type="command")


def test_gateway_target_webhook_requires_url() -> None:
    with pytest.raises(ValidationError, match="webhook gateways require a non-empty url"):
        GatewayTargetConfig(type="webhook")


def test_gateway_target_command_accepts_command() -> None:
    cfg = GatewayTargetConfig(type="command", command="echo ok")
    assert cfg.command == "echo ok"


def test_gateway_target_webhook_method_is_normalized() -> None:
    cfg = GatewayTargetConfig(type="webhook", url="http://localhost", method=" post ")
    assert cfg.method == "POST"


def test_gateway_event_rule_requires_gateway_when_enabled() -> None:
    with pytest.raises(ValidationError, match="enabled gateway event rules require a non-empty gateway"):
        GatewayEventRuleConfig(instruction="send")


def test_gateway_event_rule_requires_instruction_when_enabled() -> None:
    with pytest.raises(ValidationError, match="enabled gateway event rules require a non-empty instruction"):
        GatewayEventRuleConfig(gateway="local")


def test_gateway_dispatch_enabled_names() -> None:
    cfg = GatewayDispatchConfig(
        enabled=True,
        gateways={
            "a": GatewayTargetConfig(type="command", command="echo a"),
            "b": GatewayTargetConfig(type="command", command="echo b", enabled=False),
        },
        events={
            "session-end": GatewayEventRuleConfig(gateway="a", instruction="done"),
        },
    )
    assert cfg.enabled_gateway_names() == ("a",)


def test_gateway_dispatch_enabled_event_names() -> None:
    cfg = GatewayDispatchConfig(
        enabled=True,
        gateways={
            "a": GatewayTargetConfig(type="command", command="echo a"),
        },
        events={
            "session-end": GatewayEventRuleConfig(gateway="a", instruction="done"),
            "idle": GatewayEventRuleConfig(enabled=False),
        },
    )
    assert cfg.enabled_event_names() == ("session-end",)


def test_gateway_dispatch_rejects_unknown_gateway_reference() -> None:
    with pytest.raises(ValidationError, match="references unknown gateway 'missing'"):
        GatewayDispatchConfig(
            enabled=True,
            gateways={"a": GatewayTargetConfig(type="command", command="echo a")},
            events={"session-end": GatewayEventRuleConfig(gateway="missing", instruction="done")},
        )


def test_gateway_dispatch_rejects_disabled_gateway_reference() -> None:
    with pytest.raises(ValidationError, match="references disabled gateway 'a'"):
        GatewayDispatchConfig(
            enabled=True,
            gateways={"a": GatewayTargetConfig(type="command", command="echo a", enabled=False)},
            events={"session-end": GatewayEventRuleConfig(gateway="a", instruction="done")},
        )
