"""Background observer for periodic Codex model cache refresh."""

from __future__ import annotations

from pathlib import Path

from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.cli.model_cache import BaseModelCacheObserver


class CodexCacheObserver(BaseModelCacheObserver):
    """Refreshes Codex model cache periodically.

    Loads initial cache at startup and refreshes every 60 minutes.
    """

    def __init__(self, cache_path: Path) -> None:
        """Initialize observer with cache file path."""
        super().__init__(cache_path)
        self._cache: CodexModelCache | None = None

    def _provider_name(self) -> str:
        return "Codex"

    async def _load_cache(self, *, initial: bool) -> CodexModelCache:
        return await CodexModelCache.load_or_refresh(self._cache_path, force_refresh=initial)

    def _model_count(self) -> int:
        return len(self._cache.models) if self._cache else 0

    def _last_updated(self) -> str:
        return self._cache.last_updated if self._cache else ""

    def get_cache(self) -> CodexModelCache | None:
        """Return current cache (may be None if never loaded)."""
        return self._cache
