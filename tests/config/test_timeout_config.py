"""Tests for TimeoutConfig and resolve_timeout."""

from __future__ import annotations

from controlmesh.config import AgentConfig, TimeoutConfig, deep_merge_config, resolve_timeout


class TestTimeoutConfigDefaults:
    def test_default_values(self) -> None:
        cfg = TimeoutConfig()
        assert cfg.normal == 600.0
        assert cfg.background == 1800.0
        assert cfg.subagent == 3600.0
        assert cfg.warning_intervals == [60.0, 10.0]
        assert cfg.extend_on_activity is True
        assert cfg.activity_extension == 120.0
        assert cfg.max_extensions == 3

    def test_agent_config_has_timeouts(self) -> None:
        cfg = AgentConfig()
        assert isinstance(cfg.timeouts, TimeoutConfig)
        # cli_timeout=1800.0 syncs to timeouts.normal via model_validator
        assert cfg.timeouts.normal == cfg.cli_timeout

    def test_custom_values(self) -> None:
        cfg = TimeoutConfig(normal=300.0, background=900.0, subagent=1800.0)
        assert cfg.normal == 300.0
        assert cfg.background == 900.0
        assert cfg.subagent == 1800.0


class TestCliTimeoutSync:
    def test_cli_timeout_syncs_to_timeouts_normal(self) -> None:
        """When cli_timeout is set to non-default and timeouts.normal is default, sync."""
        cfg = AgentConfig(cli_timeout=300.0)
        assert cfg.timeouts.normal == 300.0

    def test_explicit_timeouts_normal_overrides_cli_timeout(self) -> None:
        """When timeouts.normal is explicitly set, it wins over cli_timeout."""
        cfg = AgentConfig(cli_timeout=300.0, timeouts=TimeoutConfig(normal=900.0))
        assert cfg.timeouts.normal == 900.0

    def test_default_cli_timeout_syncs(self) -> None:
        """When cli_timeout differs from TimeoutConfig default, it syncs."""
        cfg = AgentConfig()
        assert cfg.cli_timeout == 1800.0
        assert cfg.timeouts.normal == 1800.0


class TestResolveTimeout:
    def test_resolve_normal(self) -> None:
        cfg = AgentConfig()
        assert resolve_timeout(cfg, "normal") == 1800.0

    def test_resolve_background(self) -> None:
        cfg = AgentConfig()
        assert resolve_timeout(cfg, "background") == 1800.0

    def test_resolve_subagent(self) -> None:
        cfg = AgentConfig()
        assert resolve_timeout(cfg, "subagent") == 3600.0

    def test_resolve_unknown_falls_back_to_cli_timeout(self) -> None:
        cfg = AgentConfig(cli_timeout=999.0)
        assert resolve_timeout(cfg, "unknown") == 999.0

    def test_resolve_custom_values(self) -> None:
        cfg = AgentConfig(timeouts=TimeoutConfig(normal=100.0, background=200.0, subagent=300.0))
        assert resolve_timeout(cfg, "normal") == 100.0
        assert resolve_timeout(cfg, "background") == 200.0
        assert resolve_timeout(cfg, "subagent") == 300.0


class TestDeepMergeWithTimeouts:
    def test_old_config_without_timeouts_gets_defaults(self) -> None:
        old_config: dict[str, object] = {
            "provider": "claude",
            "cli_timeout": 600.0,
        }
        defaults = AgentConfig().model_dump()
        merged, changed = deep_merge_config(old_config, defaults)
        assert changed is True
        assert "timeouts" in merged

    def test_partial_timeouts_gets_completed(self) -> None:
        partial: dict[str, object] = {
            "timeouts": {
                "normal": 300.0,
            },
        }
        defaults = AgentConfig().model_dump()
        merged, changed = deep_merge_config(partial, defaults)
        assert changed is True
        timeouts = merged["timeouts"]
        assert isinstance(timeouts, dict)
        assert timeouts["normal"] == 300.0
        assert "background" in timeouts
        assert "subagent" in timeouts

    def test_full_roundtrip(self) -> None:
        cfg = AgentConfig(timeouts=TimeoutConfig(normal=100.0, background=200.0, subagent=300.0))
        dumped = cfg.model_dump()
        loaded = AgentConfig(**dumped)
        assert loaded.timeouts.normal == 100.0
        assert loaded.timeouts.background == 200.0
        assert loaded.timeouts.subagent == 300.0
