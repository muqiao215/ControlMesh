"""Focused tests for ``controlmesh.multiagent.supervisor._config_changed``."""

from __future__ import annotations

from pathlib import Path

from controlmesh.config import AgentConfig, FeishuConfig, MatrixConfig
from controlmesh.multiagent.supervisor import _config_changed


class TestConfigChanged:
    def test_detects_secondary_matrix_identity_change(self, tmp_path: Path) -> None:
        old = AgentConfig(
            controlmesh_home=str(tmp_path / "old"),
            transport="telegram",
            transports=["telegram", "matrix"],
            telegram_token="main-token",
            matrix=MatrixConfig(
                homeserver="https://matrix.old.example",
                user_id="@bot:old.example",
            ),
        )
        new = AgentConfig(
            controlmesh_home=str(tmp_path / "new"),
            transport="telegram",
            transports=["telegram", "matrix"],
            telegram_token="main-token",
            matrix=MatrixConfig(
                homeserver="https://matrix.new.example",
                user_id="@bot:old.example",
            ),
        )

        assert _config_changed(new, old) is True

    def test_detects_feishu_identity_change_when_enabled_as_secondary(self, tmp_path: Path) -> None:
        old = AgentConfig(
            controlmesh_home=str(tmp_path / "old"),
            transport="telegram",
            transports=["telegram", "feishu"],
            telegram_token="main-token",
            feishu=FeishuConfig(
                app_id="cli-old",
                app_secret="secret",
            ),
        )
        new = AgentConfig(
            controlmesh_home=str(tmp_path / "new"),
            transport="telegram",
            transports=["telegram", "feishu"],
            telegram_token="main-token",
            feishu=FeishuConfig(
                app_id="cli-new",
                app_secret="secret",
            ),
        )

        assert _config_changed(new, old) is True

    def test_returns_false_when_transport_identity_is_unchanged(self, tmp_path: Path) -> None:
        old = AgentConfig(
            controlmesh_home=str(tmp_path / "old"),
            transport="telegram",
            transports=["telegram", "matrix"],
            telegram_token="main-token",
            matrix=MatrixConfig(
                homeserver="https://matrix.example",
                user_id="@bot:example",
            ),
        )
        new = AgentConfig(
            controlmesh_home=str(tmp_path / "new"),
            transport="telegram",
            transports=["telegram", "matrix"],
            telegram_token="main-token",
            matrix=MatrixConfig(
                homeserver="https://matrix.example",
                user_id="@bot:example",
            ),
        )

        assert _config_changed(new, old) is False
