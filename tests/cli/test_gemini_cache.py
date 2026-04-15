"""Tests for Gemini model cache."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from controlmesh.cli.gemini_cache import _FALLBACK_GEMINI_MODELS, GeminiModelCache


@pytest.fixture
def sample_models() -> tuple[str, ...]:
    """Sample model tuple for testing."""
    return ("gemini-2.5-flash", "gemini-2.5-pro")


@pytest.fixture
def fresh_cache(sample_models: tuple[str, ...]) -> GeminiModelCache:
    """Fresh cache (< 24h old)."""
    return GeminiModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=sample_models,
    )


@pytest.fixture
def stale_cache(sample_models: tuple[str, ...]) -> GeminiModelCache:
    """Stale cache (> 24h old)."""
    old_time = datetime.now(UTC) - timedelta(hours=25)
    return GeminiModelCache(
        last_updated=old_time.isoformat(),
        models=sample_models,
    )


async def test_load_from_disk(tmp_path: Path) -> None:
    """Should load cache from disk if present and fresh."""
    cache_path = tmp_path / "gemini_models.json"
    now = datetime.now(UTC).isoformat()
    cache_path.write_text(
        f'{{"last_updated": "{now}", "models": ["gemini-2.5-flash", "gemini-2.5-pro"]}}'
    )

    with patch("controlmesh.cli.gemini_cache.discover_gemini_models") as mock_discover:
        result = await GeminiModelCache.load_or_refresh(cache_path)

        assert len(result.models) == 2
        assert result.models[0] == "gemini-2.5-flash"
        mock_discover.assert_not_called()


async def test_refresh_on_stale(tmp_path: Path, sample_models: tuple[str, ...]) -> None:
    """Should refresh cache if stale (>24h)."""
    cache_path = tmp_path / "gemini_models.json"
    old_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    cache_path.write_text(f'{{"last_updated": "{old_time}", "models": []}}')

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=frozenset(sample_models),
    ) as mock_discover:
        result = await GeminiModelCache.load_or_refresh(cache_path)

        mock_discover.assert_called_once()
        assert len(result.models) == 2
        assert cache_path.exists()


async def test_skip_refresh_if_recent(tmp_path: Path) -> None:
    """Should skip refresh if cache is recent (<24h)."""
    cache_path = tmp_path / "gemini_models.json"
    recent_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    cache_path.write_text(f'{{"last_updated": "{recent_time}", "models": ["gemini-2.5-flash"]}}')

    with patch("controlmesh.cli.gemini_cache.discover_gemini_models") as mock_discover:
        result = await GeminiModelCache.load_or_refresh(cache_path)

        mock_discover.assert_not_called()
        assert len(result.models) == 1


async def test_refresh_if_recent_but_empty(
    tmp_path: Path,
    sample_models: tuple[str, ...],
) -> None:
    """Should refresh if cache is recent but contains zero models."""
    cache_path = tmp_path / "gemini_models.json"
    recent_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    cache_path.write_text(f'{{"last_updated": "{recent_time}", "models": []}}')

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=frozenset(sample_models),
    ) as mock_discover:
        result = await GeminiModelCache.load_or_refresh(cache_path)

        mock_discover.assert_called_once()
        assert len(result.models) == 2


async def test_force_refresh_ignores_fresh_cache(
    tmp_path: Path,
    sample_models: tuple[str, ...],
) -> None:
    """Should refresh when force_refresh=True even if cache is fresh."""
    cache_path = tmp_path / "gemini_models.json"
    recent_time = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    cache_path.write_text(f'{{"last_updated": "{recent_time}", "models": ["old-model"]}}')

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=frozenset(sample_models),
    ) as mock_discover:
        result = await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

        mock_discover.assert_called_once()
        assert len(result.models) == 2
        assert "gemini-2.5-flash" in result.models


def test_validate_model_exists(fresh_cache: GeminiModelCache) -> None:
    """Should return True for existing model."""
    assert fresh_cache.validate_model("gemini-2.5-flash") is True
    assert fresh_cache.validate_model("gemini-2.5-pro") is True


def test_validate_model_missing(fresh_cache: GeminiModelCache) -> None:
    """Should return False for nonexistent model."""
    assert fresh_cache.validate_model("nonexistent") is False


async def test_discovery_failure_preserves_existing_disk_cache(tmp_path: Path) -> None:
    """When discovery fails and a non-empty cache exists on disk, keep it."""
    cache_path = tmp_path / "gemini_models.json"
    existing_models = ("gemini-2.5-flash", "gemini-2.5-pro")
    cache_path.write_text(
        json.dumps(
            {
                "last_updated": datetime.now(UTC).isoformat(),
                "models": list(existing_models),
            }
        )
    )

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        side_effect=Exception("Discovery failed"),
    ):
        result = await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert result.models == existing_models
    # Verify disk file is untouched (still contains the original models).
    disk_data = json.loads(cache_path.read_text())
    assert set(disk_data["models"]) == set(existing_models)


async def test_discovery_failure_uses_fallback_when_no_disk_cache(tmp_path: Path) -> None:
    """When discovery fails and no disk cache exists, use hardcoded fallback."""
    cache_path = tmp_path / "gemini_models.json"
    assert not cache_path.exists()

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        side_effect=Exception("Discovery failed"),
    ):
        result = await GeminiModelCache.load_or_refresh(cache_path)

    assert result.models == _FALLBACK_GEMINI_MODELS
    # Fallback must NOT be persisted to disk.
    assert not cache_path.exists()


async def test_discovery_failure_uses_fallback_when_disk_cache_empty(tmp_path: Path) -> None:
    """When discovery fails and disk cache is empty, use hardcoded fallback."""
    cache_path = tmp_path / "gemini_models.json"
    cache_path.write_text(json.dumps({"last_updated": datetime.now(UTC).isoformat(), "models": []}))

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        side_effect=Exception("Discovery failed"),
    ):
        result = await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert result.models == _FALLBACK_GEMINI_MODELS
    # Disk still has the old empty cache — fallback is NOT persisted.
    disk_data = json.loads(cache_path.read_text())
    assert disk_data["models"] == []


async def test_fallback_replaced_by_successful_discovery(tmp_path: Path) -> None:
    """After using fallback, a successful discovery must replace it."""
    cache_path = tmp_path / "gemini_models.json"

    # First call: discovery fails → fallback (not on disk)
    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        side_effect=Exception("fail"),
    ):
        result1 = await GeminiModelCache.load_or_refresh(cache_path)
    assert result1.models == _FALLBACK_GEMINI_MODELS
    assert not cache_path.exists()

    # Second call: discovery succeeds → real models saved to disk
    real_models = frozenset({"gemini-3-pro", "gemini-3-flash"})
    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=real_models,
    ):
        result2 = await GeminiModelCache.load_or_refresh(cache_path)
    assert set(result2.models) == real_models
    # Real models are persisted.
    disk_data = json.loads(cache_path.read_text())
    assert set(disk_data["models"]) == real_models


async def test_empty_discovery_result_preserves_existing_cache(tmp_path: Path) -> None:
    """When discovery returns zero models (not an exception), keep existing cache."""
    cache_path = tmp_path / "gemini_models.json"
    existing_models = ("gemini-2.5-flash",)
    cache_path.write_text(
        json.dumps(
            {
                "last_updated": datetime.now(UTC).isoformat(),
                "models": list(existing_models),
            }
        )
    )

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=frozenset(),
    ):
        result = await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert result.models == existing_models


async def test_empty_cache_not_saved_to_disk(tmp_path: Path) -> None:
    """An empty discovery result must not overwrite a non-empty disk cache."""
    cache_path = tmp_path / "gemini_models.json"
    original = {"last_updated": datetime.now(UTC).isoformat(), "models": ["gemini-2.5-pro"]}
    cache_path.write_text(json.dumps(original))

    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=frozenset(),
    ):
        await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

    disk_data = json.loads(cache_path.read_text())
    assert disk_data["models"] == ["gemini-2.5-pro"]


async def test_successful_discovery_overwrites_disk_cache(tmp_path: Path) -> None:
    """A successful discovery with models must update the disk cache."""
    cache_path = tmp_path / "gemini_models.json"
    cache_path.write_text(
        json.dumps({"last_updated": datetime.now(UTC).isoformat(), "models": ["old-model"]})
    )

    new_models = frozenset({"gemini-3-flash", "gemini-3-pro"})
    with patch(
        "controlmesh.cli.gemini_cache.discover_gemini_models",
        return_value=new_models,
    ):
        result = await GeminiModelCache.load_or_refresh(cache_path, force_refresh=True)

    assert set(result.models) == new_models
    disk_data = json.loads(cache_path.read_text())
    assert set(disk_data["models"]) == new_models


def test_fallback_models_are_non_empty() -> None:
    """Fallback constant must provide usable defaults."""
    assert len(_FALLBACK_GEMINI_MODELS) >= 3
    assert all(m.startswith("gemini-") for m in _FALLBACK_GEMINI_MODELS)


def test_serialize_deserialize(fresh_cache: GeminiModelCache) -> None:
    """Should roundtrip serialize and deserialize."""
    json_data = fresh_cache.to_json()

    assert "last_updated" in json_data
    assert "models" in json_data
    assert len(json_data["models"]) == 2

    restored = GeminiModelCache.from_json(json_data)

    assert restored.last_updated == fresh_cache.last_updated
    assert len(restored.models) == len(fresh_cache.models)
    assert restored.models[0] == fresh_cache.models[0]
