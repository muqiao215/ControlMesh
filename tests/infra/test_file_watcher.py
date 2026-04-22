"""Tests for ``controlmesh.infra.file_watcher``."""

from __future__ import annotations

import asyncio
from pathlib import Path

from controlmesh.infra.file_watcher import FileWatcher


class TestFileWatcher:
    async def test_start_snapshots_existing_file_before_polling(self, tmp_path: Path) -> None:
        path = tmp_path / "agents.json"
        path.write_text("[]", encoding="utf-8")

        changed = asyncio.Event()
        calls = 0

        async def on_change() -> None:
            nonlocal calls
            calls += 1
            changed.set()

        watcher = FileWatcher(path, on_change, interval=0.01)
        await watcher.start()
        try:
            await asyncio.sleep(0.03)
            assert calls == 0

            path.write_text('[{"name": "sub1"}]', encoding="utf-8")
            await asyncio.wait_for(changed.wait(), timeout=0.2)
            assert calls == 1
        finally:
            await watcher.stop()

    async def test_start_is_idempotent_while_running(self, tmp_path: Path) -> None:
        path = tmp_path / "agents.json"
        path.write_text("[]", encoding="utf-8")

        async def on_change() -> None:
            return None

        watcher = FileWatcher(path, on_change, interval=0.01)
        await watcher.start()
        try:
            first_task = watcher._task
            await watcher.start()
            assert watcher._task is first_task
            assert watcher.last_mtime == path.stat().st_mtime
        finally:
            await watcher.stop()
