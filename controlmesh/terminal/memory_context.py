"""Explicit memory injection support for enhanced terminal mode."""

from __future__ import annotations

import asyncio

from controlmesh.memory.commands import search_memory
from controlmesh.workspace.paths import ControlMeshPaths


class TerminalMemoryContext:
    """Holds memory snippets that should affect only the next enhanced turn."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths
        self._pending_blocks: list[str] = []
        self._last_hits: dict[str, str] = {}

    async def search(self, query: str) -> list[tuple[str, str]]:
        """Search memory and cache terminal-local hit ids."""
        result = await asyncio.to_thread(search_memory, self._paths, query)
        self._last_hits.clear()
        rows: list[tuple[str, str]] = []
        for index, hit in enumerate(result.hits, start=1):
            hit_id = f"hit_{index:03d}"
            block = f"{hit.kind.value} {hit.source_path}\n{hit.snippet}"
            self._last_hits[hit_id] = block
            rows.append((hit_id, block))
        return rows

    def inject(self, hit_id: str) -> str:
        """Queue one cached hit for the next enhanced message."""
        block = self._last_hits.get(hit_id)
        if block is None:
            msg = f"Unknown memory hit: {hit_id}. Run /memory search <query> first."
            raise KeyError(msg)
        self._pending_blocks.append(block)
        return block

    def consume_for_prompt(self, text: str) -> str:
        """Apply queued memory blocks to one enhanced prompt, then clear them."""
        if not self._pending_blocks:
            return text
        joined = "\n\n".join(self._pending_blocks)
        self._pending_blocks.clear()
        return f"[ControlMesh memory context]\n{joined}\n[/ControlMesh memory context]\n\n{text}"
