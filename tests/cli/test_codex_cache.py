"""Tests for Codex model cache."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from controlmesh.cli.codex_cache import _FALLBACK_CODEX_MODELS, CodexModelCache
from controlmesh.cli.codex_discovery import CodexModelInfo


@pytest.fixture
def sample_models() -> list[CodexModelInfo]:
    """Sample model list for testing."""
    return [
        CodexModelInfo(
            id="gpt-4o",
            display_name="GPT-4o",
            description="GPT-4o model",
            supported_efforts=("low", "medium", "high"),
            default_effort="medium",
            is_default=True,
        ),
        CodexModelInfo(
            id="gpt-4o-mini",
            display_name="GPT-4o Mini",
            description="GPT-4o Mini model (no reasoning)",
            supported_efforts=(),
            default_effort="",
            is_default=False,
        ),
    ]


@pytest.fixture
def fresh_cache(sample_models: list[CodexModelInfo]) -> CodexModelCache:
    """Fresh cache (< 24h old)."""
    return CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=sample_models,
    )


@pytest.fixture
def stale_cache(sample_models: list[CodexModelInfo]) -> CodexModelCache:
    """Stale cache (> 24h old)."""
    old_time = datetime.now(UTC) - timedelta(hours=25)
    return CodexModelCache(
        last_updated=old_time.isoformat(),
        models=sample_models,
    )


async def test_load_from_disk(tmp_path: Path) -> None:
    """Should load cache from disk if present and fresh."""
    cache_path = tmp_path / "codex_models.json"
    now = datetime.now(UTC).isoformat()
    cache_path.write_text(
        f"""{{
        "last_updated": "{now}",
        "models": [
            {{
                "id": "gpt-4o",
                "display_name": "GPT-4o",
                "description": "GPT-4o model",
                "supported_efforts": ["low", "medium", "high"],
                "default_effort": "medium",
                "is_default": true
            }}
        ]
    }}"""
    )

    with patch("controlmesh.cli.codex_cache.discover_codex_models", AsyncMock()) as mock_discover:
        result = await CodexModelCache.load_or_refresh(cache_path)

        assert len(result.models) == 1
        assert result.models[0].id == "gpt-4o"
        mock_discover.assert_not_called()  # Should not refresh if fresh


async def test_refresh_on_stale(tmp_path: Path, sample_models: list[CodexModelInfo]) -> None:
    """Should refresh cache if stale (>24h)."""
    cache_path = tmp_path / "codex_models.json"
    old_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    cache_path.write_text(
        f"""{{
        "last_updated": "{old_time}",
        "models": []
    }}"""
    )

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=sample_models),
    ) as mock_discover:
        result = await CodexModelCache.load_or_refresh(cache_path)

        mock_discover.assert_called_once()
        assert len(result.models) == 2
        assert result.models[0].id == "gpt-4o"

        # Should write updated cache to disk
        assert cache_path.exists()


async def test_skip_refresh_if_recent(tmp_path: Path) -> None:
    """Should skip refresh if cache is recent (<24h)."""
    cache_path = tmp_path / "codex_models.json"
    recent_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    cache_path.write_text(
        f"""{{
        "last_updated": "{recent_time}",
        "models": [
            {{
                "id": "gpt-4o",
                "display_name": "GPT-4o",
                "description": "GPT-4o model",
                "supported_efforts": ["low"],
                "default_effort": "low",
                "is_default": true
            }}
        ]
    }}"""
    )

    with patch("controlmesh.cli.codex_cache.discover_codex_models", AsyncMock()) as mock_discover:
        result = await CodexModelCache.load_or_refresh(cache_path)

        mock_discover.assert_not_called()
        assert len(result.models) == 1


async def test_refresh_if_recent_but_empty(
    tmp_path: Path,
    sample_models: list[CodexModelInfo],
) -> None:
    """Should refresh if cache is recent but contains zero models."""
    cache_path = tmp_path / "codex_models.json"
    recent_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    cache_path.write_text(
        f"""{{
        "last_updated": "{recent_time}",
        "models": []
    }}"""
    )

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=sample_models),
    ) as mock_discover:
        result = await CodexModelCache.load_or_refresh(cache_path)

        mock_discover.assert_called_once()
        assert len(result.models) == 2


async def test_force_refresh_ignores_fresh_cache(
    tmp_path: Path,
    sample_models: list[CodexModelInfo],
) -> None:
    """Should refresh when force_refresh=True even if cache is fresh."""
    cache_path = tmp_path / "codex_models.json"
    recent_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    cache_path.write_text(
        f"""{{
        "last_updated": "{recent_time}",
        "models": [
            {{
                "id": "stale-model",
                "display_name": "stale-model",
                "description": "old",
                "supported_efforts": ["low"],
                "default_effort": "low",
                "is_default": true
            }}
        ]
    }}"""
    )

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=sample_models),
    ) as mock_discover:
        result = await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

        mock_discover.assert_called_once()
        assert len(result.models) == 2
        assert result.models[0].id == "gpt-4o"


def test_validate_model_exists(fresh_cache: CodexModelCache) -> None:
    """Should return True for existing model."""
    assert fresh_cache.validate_model("gpt-4o") is True
    assert fresh_cache.validate_model("gpt-4o-mini") is True


def test_validate_model_missing(fresh_cache: CodexModelCache) -> None:
    """Should return False for nonexistent model."""
    assert fresh_cache.validate_model("nonexistent") is False


def test_validate_reasoning_effort(fresh_cache: CodexModelCache) -> None:
    """Should validate reasoning effort against model capabilities."""
    assert fresh_cache.validate_reasoning_effort("gpt-4o", "low") is True
    assert fresh_cache.validate_reasoning_effort("gpt-4o", "medium") is True
    assert fresh_cache.validate_reasoning_effort("gpt-4o", "high") is True


def test_validate_reasoning_effort_invalid(fresh_cache: CodexModelCache) -> None:
    """Should return False for invalid or unsupported effort."""
    # Model doesn't support reasoning
    assert fresh_cache.validate_reasoning_effort("gpt-4o-mini", "low") is False

    # Invalid effort for model that supports reasoning
    assert fresh_cache.validate_reasoning_effort("gpt-4o", "extreme") is False

    # Nonexistent model
    assert fresh_cache.validate_reasoning_effort("nonexistent", "low") is False


async def test_discovery_failure_preserves_existing_disk_cache(tmp_path: Path) -> None:
    """When discovery fails and a non-empty cache exists on disk, keep it."""
    cache_path = tmp_path / "codex_models.json"
    existing = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-5.2-codex",
                display_name="gpt-5.2-codex",
                description="Existing model",
                supported_efforts=("low", "medium", "high"),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )
    cache_path.write_text(json.dumps(existing.to_json(), indent=2))

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(side_effect=Exception("Discovery failed")),
    ):
        result = await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert len(result.models) == 1
    assert result.models[0].id == "gpt-5.2-codex"
    # Verify disk file is untouched.
    disk_data = json.loads(cache_path.read_text())
    assert len(disk_data["models"]) == 1
    assert disk_data["models"][0]["id"] == "gpt-5.2-codex"


async def test_discovery_failure_uses_fallback_when_no_disk_cache(tmp_path: Path) -> None:
    """When discovery fails and no disk cache exists, use hardcoded fallback."""
    cache_path = tmp_path / "codex_models.json"
    assert not cache_path.exists()

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(side_effect=Exception("Discovery failed")),
    ):
        result = await CodexModelCache.load_or_refresh(cache_path)

    fallback_ids = {m.id for m in _FALLBACK_CODEX_MODELS}
    result_ids = {m.id for m in result.models}
    assert result_ids == fallback_ids
    # Fallback must NOT be persisted to disk.
    assert not cache_path.exists()


async def test_discovery_failure_uses_fallback_when_disk_cache_empty(tmp_path: Path) -> None:
    """When discovery fails and disk cache is empty, use hardcoded fallback."""
    cache_path = tmp_path / "codex_models.json"
    cache_path.write_text(json.dumps({"last_updated": datetime.now(UTC).isoformat(), "models": []}))

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(side_effect=Exception("Discovery failed")),
    ):
        result = await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert len(result.models) == len(_FALLBACK_CODEX_MODELS)
    # Disk still has old empty cache — fallback NOT persisted.
    disk_data = json.loads(cache_path.read_text())
    assert disk_data["models"] == []


async def test_fallback_replaced_by_successful_discovery(tmp_path: Path) -> None:
    """After using fallback, a successful discovery must replace it."""
    cache_path = tmp_path / "codex_models.json"

    # First call: discovery fails → fallback (not on disk)
    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(side_effect=Exception("fail")),
    ):
        result1 = await CodexModelCache.load_or_refresh(cache_path)
    assert len(result1.models) == len(_FALLBACK_CODEX_MODELS)
    assert not cache_path.exists()

    # Second call: discovery succeeds → real models saved to disk
    real_models = [
        CodexModelInfo(
            id="gpt-6",
            display_name="GPT-6",
            description="New model",
            supported_efforts=("low", "medium", "high"),
            default_effort="medium",
            is_default=True,
        ),
    ]
    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=real_models),
    ):
        result2 = await CodexModelCache.load_or_refresh(cache_path)
    assert len(result2.models) == 1
    assert result2.models[0].id == "gpt-6"
    # Real models are persisted.
    disk_data = json.loads(cache_path.read_text())
    assert disk_data["models"][0]["id"] == "gpt-6"


async def test_empty_discovery_result_preserves_existing_cache(tmp_path: Path) -> None:
    """When discovery returns zero models (not an exception), keep existing cache."""
    cache_path = tmp_path / "codex_models.json"
    existing = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-5.3-codex",
                display_name="gpt-5.3-codex",
                description="test",
                supported_efforts=("medium",),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )
    cache_path.write_text(json.dumps(existing.to_json(), indent=2))

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=[]),
    ):
        result = await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert len(result.models) == 1
    assert result.models[0].id == "gpt-5.3-codex"


async def test_empty_cache_not_saved_to_disk(tmp_path: Path) -> None:
    """An empty discovery result must not overwrite a non-empty disk cache."""
    cache_path = tmp_path / "codex_models.json"
    original = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="gpt-5.2-codex",
                display_name="gpt-5.2-codex",
                description="test",
                supported_efforts=("medium", "high"),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )
    cache_path.write_text(json.dumps(original.to_json(), indent=2))

    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=[]),
    ):
        await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

    disk_data = json.loads(cache_path.read_text())
    assert len(disk_data["models"]) == 1
    assert disk_data["models"][0]["id"] == "gpt-5.2-codex"


async def test_successful_discovery_overwrites_disk_cache(tmp_path: Path) -> None:
    """A successful discovery with models must update the disk cache."""
    cache_path = tmp_path / "codex_models.json"
    old = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=[
            CodexModelInfo(
                id="old-model",
                display_name="old",
                description="old",
                supported_efforts=("medium",),
                default_effort="medium",
                is_default=True,
            ),
        ],
    )
    cache_path.write_text(json.dumps(old.to_json(), indent=2))

    new_models = [
        CodexModelInfo(
            id="new-model",
            display_name="New",
            description="New model",
            supported_efforts=("low", "medium", "high"),
            default_effort="medium",
            is_default=True,
        ),
    ]
    with patch(
        "controlmesh.cli.codex_cache.discover_codex_models",
        AsyncMock(return_value=new_models),
    ):
        result = await CodexModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert len(result.models) == 1
    assert result.models[0].id == "new-model"
    disk_data = json.loads(cache_path.read_text())
    assert disk_data["models"][0]["id"] == "new-model"


def test_fallback_models_have_thinking_levels() -> None:
    """Fallback Codex models must include supported_efforts (thinking levels)."""
    assert len(_FALLBACK_CODEX_MODELS) >= 3
    for model in _FALLBACK_CODEX_MODELS:
        assert model.supported_efforts, f"{model.id} has no supported_efforts"
        assert model.default_effort, f"{model.id} has no default_effort"
    # At least one model should have xhigh effort
    has_xhigh = any("xhigh" in m.supported_efforts for m in _FALLBACK_CODEX_MODELS)
    assert has_xhigh, "No fallback model supports xhigh effort"


def test_fallback_models_have_exactly_one_default() -> None:
    """Exactly one fallback model must be marked as default."""
    defaults = [m for m in _FALLBACK_CODEX_MODELS if m.is_default]
    assert len(defaults) == 1


def test_serialize_deserialize(fresh_cache: CodexModelCache) -> None:
    """Should roundtrip serialize and deserialize."""
    json_data = fresh_cache.to_json()

    assert "last_updated" in json_data
    assert "models" in json_data
    assert len(json_data["models"]) == 2  # type: ignore[arg-type]

    restored = CodexModelCache.from_json(json_data)

    assert restored.last_updated == fresh_cache.last_updated
    assert len(restored.models) == len(fresh_cache.models)
    assert restored.models[0].id == fresh_cache.models[0].id
    assert restored.models[1].supported_efforts == fresh_cache.models[1].supported_efforts
