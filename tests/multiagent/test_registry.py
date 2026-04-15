"""Tests for multiagent/registry.py: AgentRegistry load/save/add/remove."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from controlmesh.multiagent.models import SubAgentConfig
from controlmesh.multiagent.registry import AgentRegistry


@pytest.fixture
def agents_path(tmp_path: Path) -> Path:
    return tmp_path / "agents.json"


class TestRegistryLoad:
    """Test AgentRegistry.load() behavior."""

    def test_missing_file_returns_empty(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        assert reg.load() == []

    def test_valid_json_array(self, agents_path: Path) -> None:
        data = [
            {"name": "sub1", "telegram_token": "tok:1"},
            {"name": "sub2", "telegram_token": "tok:2", "provider": "codex"},
        ]
        agents_path.write_text(json.dumps(data))
        reg = AgentRegistry(agents_path)
        agents = reg.load()
        assert len(agents) == 2
        assert agents[0].name == "sub1"
        assert agents[1].provider == "codex"

    def test_corrupt_json_returns_empty(self, agents_path: Path) -> None:
        agents_path.write_text("{not valid json")
        reg = AgentRegistry(agents_path)
        assert reg.load() == []

    def test_non_array_json_returns_empty(self, agents_path: Path) -> None:
        agents_path.write_text('{"name": "sub1"}')
        reg = AgentRegistry(agents_path)
        assert reg.load() == []

    def test_empty_array_returns_empty(self, agents_path: Path) -> None:
        agents_path.write_text("[]")
        reg = AgentRegistry(agents_path)
        assert reg.load() == []

    def test_invalid_entry_is_skipped(self, agents_path: Path) -> None:
        data = [
            {"name": "sub1", "telegram_token": "tok:1"},
            {"invalid": "missing name and token"},
            {"name": "sub3", "telegram_token": "tok:3"},
        ]
        agents_path.write_text(json.dumps(data))
        reg = AgentRegistry(agents_path)
        agents = reg.load()
        assert len(agents) == 2
        assert agents[0].name == "sub1"
        assert agents[1].name == "sub3"

    def test_path_property(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        assert reg.path == agents_path


class TestRegistrySave:
    """Test AgentRegistry.save() behavior."""

    def test_save_creates_file(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        agents = [SubAgentConfig(name="sub1", telegram_token="tok:1")]
        reg.save(agents)
        assert agents_path.is_file()

    def test_save_roundtrip(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        original = [
            SubAgentConfig(name="sub1", telegram_token="tok:1"),
            SubAgentConfig(name="sub2", telegram_token="tok:2", provider="codex"),
        ]
        reg.save(original)
        loaded = reg.load()
        assert len(loaded) == 2
        assert loaded[0].name == "sub1"
        assert loaded[1].provider == "codex"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        deep_path = tmp_path / "a" / "b" / "agents.json"
        reg = AgentRegistry(deep_path)
        reg.save([SubAgentConfig(name="sub1", telegram_token="tok:1")])
        assert deep_path.is_file()

    def test_save_excludes_none_values(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.save([SubAgentConfig(name="sub1", telegram_token="tok:1")])
        raw = json.loads(agents_path.read_text())
        assert len(raw) == 1
        assert "provider" not in raw[0]  # None fields excluded


class TestRegistryAdd:
    """Test AgentRegistry.add() behavior."""

    def test_add_new_agent(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.add(SubAgentConfig(name="sub1", telegram_token="tok:1"))
        agents = reg.load()
        assert len(agents) == 1
        assert agents[0].name == "sub1"

    def test_add_multiple_agents(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.add(SubAgentConfig(name="sub1", telegram_token="tok:1"))
        reg.add(SubAgentConfig(name="sub2", telegram_token="tok:2"))
        agents = reg.load()
        assert len(agents) == 2

    def test_add_duplicate_name_raises(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.add(SubAgentConfig(name="sub1", telegram_token="tok:1"))
        with pytest.raises(ValueError, match="already exists"):
            reg.add(SubAgentConfig(name="sub1", telegram_token="tok:2"))


class TestRegistryRemove:
    """Test AgentRegistry.remove() behavior."""

    def test_remove_existing(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.add(SubAgentConfig(name="sub1", telegram_token="tok:1"))
        reg.add(SubAgentConfig(name="sub2", telegram_token="tok:2"))

        removed = reg.remove("sub1")
        assert removed is not None
        assert removed.name == "sub1"
        assert len(reg.load()) == 1

    def test_remove_nonexistent_returns_none(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        assert reg.remove("nonexistent") is None

    def test_remove_last_agent(self, agents_path: Path) -> None:
        reg = AgentRegistry(agents_path)
        reg.add(SubAgentConfig(name="sub1", telegram_token="tok:1"))
        reg.remove("sub1")
        assert reg.load() == []
