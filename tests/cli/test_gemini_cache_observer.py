"""Tests for GeminiCacheObserver: periodic Gemini model cache refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from controlmesh.cli.gemini_cache import GeminiModelCache
from controlmesh.cli.gemini_cache_observer import GeminiCacheObserver


class TestGeminiCacheObserver:
    """Test GeminiCacheObserver lifecycle."""

    async def test_observer_loads_cache_at_start(self, tmp_path: Path) -> None:
        """Observer loads cache on start()."""
        cache_path = tmp_path / "gemini_cache.json"
        mock_cache = GeminiModelCache(
            last_updated="2025-01-01T00:00:00Z",
            models=("gemini-2.5-flash",),
        )
        observer = GeminiCacheObserver(cache_path)

        with patch(
            "controlmesh.cli.gemini_cache_observer.GeminiModelCache.load_or_refresh",
            new_callable=AsyncMock,
        ) as mock_load:
            mock_load.return_value = mock_cache

            await observer.start()

            mock_load.assert_called_once_with(cache_path, force_refresh=True)
            assert observer.get_cache() is mock_cache
            assert observer._running is True
            assert observer._task is not None

            await observer.stop()

    async def test_observer_stop_cancels_task(self, tmp_path: Path) -> None:
        """Observer.stop() cancels refresh task cleanly."""
        cache_path = tmp_path / "gemini_cache.json"
        mock_cache = GeminiModelCache(
            last_updated="2025-01-01T00:00:00Z",
            models=("gemini-2.5-flash",),
        )
        observer = GeminiCacheObserver(cache_path)

        with patch(
            "controlmesh.cli.gemini_cache_observer.GeminiModelCache.load_or_refresh",
            new_callable=AsyncMock,
        ) as mock_load:
            mock_load.return_value = mock_cache

            await observer.start()
            assert observer._task is not None
            assert not observer._task.done()

            await observer.stop()

            assert observer._running is False
            assert observer._task is None

    async def test_observer_get_cache_returns_none_before_start(self, tmp_path: Path) -> None:
        """get_cache() returns None before start() is called."""
        cache_path = tmp_path / "gemini_cache.json"
        observer = GeminiCacheObserver(cache_path)

        assert observer.get_cache() is None

    async def test_observer_verifies_60_minute_interval(self) -> None:
        """Verify observer uses the expected refresh interval."""
        from controlmesh.cli.model_cache import REFRESH_INTERVAL_S

        assert REFRESH_INTERVAL_S == 3600

    async def test_on_refresh_callback_called(self, tmp_path: Path) -> None:
        """on_refresh callback is invoked with model list after load."""
        cache_path = tmp_path / "gemini_cache.json"
        mock_cache = GeminiModelCache(
            last_updated="2025-01-01T00:00:00Z",
            models=("gemini-2.5-flash", "gemini-2.5-pro"),
        )
        received: list[tuple[str, ...]] = []

        observer = GeminiCacheObserver(cache_path, on_refresh=received.append)

        with patch(
            "controlmesh.cli.gemini_cache_observer.GeminiModelCache.load_or_refresh",
            new_callable=AsyncMock,
        ) as mock_load:
            mock_load.return_value = mock_cache

            await observer.start()
            await observer.stop()

        assert len(received) == 1
        assert received[0] == ("gemini-2.5-flash", "gemini-2.5-pro")

    async def test_on_refresh_not_called_for_empty_cache(self, tmp_path: Path) -> None:
        """on_refresh callback is NOT invoked when cache is empty."""
        cache_path = tmp_path / "gemini_cache.json"
        mock_cache = GeminiModelCache(
            last_updated="2025-01-01T00:00:00Z",
            models=(),
        )
        received: list[tuple[str, ...]] = []

        observer = GeminiCacheObserver(cache_path, on_refresh=received.append)

        with patch(
            "controlmesh.cli.gemini_cache_observer.GeminiModelCache.load_or_refresh",
            new_callable=AsyncMock,
        ) as mock_load:
            mock_load.return_value = mock_cache

            await observer.start()
            await observer.stop()

        assert len(received) == 0
