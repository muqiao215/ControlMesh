"""Rendering helpers for terminal responses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from controlmesh.orchestrator.registry import OrchestratorResult

if TYPE_CHECKING:
    from rich.console import Console


def render_result(console: Console, result: OrchestratorResult | None) -> None:
    """Render an orchestrator result in the enhanced terminal."""
    if result is None:
        return
    text = result.text.strip()
    if text:
        console.print(text)
