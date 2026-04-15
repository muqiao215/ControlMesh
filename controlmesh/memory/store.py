"""File bootstrap helpers for ControlMesh memory-v2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.memory.models import DreamingSweepState
from controlmesh.workspace.paths import ControlMeshPaths

_AUTHORITY_TEMPLATE = """# ControlMesh Memory v2

This file is the additive, human-readable authority for durable memory promoted
from daily notes and future dreaming/search layers. It does not replace the
legacy `memory_system/MAINMEMORY.md` yet.

## Durable Memory

### Fact

### Preference

### Decision

### Project

### Person
"""

_DREAM_DIARY_TEMPLATE = """# ControlMesh Dream Diary

This file stores cross-day synthesis output. Entries are append-only and
reviewable; machine state lives under `memory/.dreams/`.
"""


def daily_note_path(paths: ControlMeshPaths, note_date: date) -> Path:
    """Resolve a daily note path under ``memory/YYYY-MM-DD.md``."""
    return paths.memory_v2_daily_dir / f"{note_date.isoformat()}.md"


def initialize_memory_v2(paths: ControlMeshPaths) -> None:
    """Create the additive memory-v2 layout if it does not exist yet."""
    paths.memory_v2_daily_dir.mkdir(parents=True, exist_ok=True)
    paths.memory_v2_machine_state_dir.mkdir(parents=True, exist_ok=True)

    if not paths.authority_memory_path.exists():
        atomic_text_save(paths.authority_memory_path, _AUTHORITY_TEMPLATE)
    if not paths.dream_diary_path.exists():
        atomic_text_save(paths.dream_diary_path, _DREAM_DIARY_TEMPLATE)
    if not paths.dreaming_sweep_state_path.exists():
        from controlmesh.memory.dreaming import save_sweep_state

        save_sweep_state(paths, DreamingSweepState())
    if not paths.dreaming_checkpoints_path.exists():
        from controlmesh.memory.dreaming import save_checkpoints

        save_checkpoints(paths, {})
    if not paths.memory_promotion_log_path.exists():
        from controlmesh.infra.json_store import atomic_json_save

        atomic_json_save(paths.memory_promotion_log_path, {})
    if not paths.dreaming_sweep_log_path.exists():
        atomic_text_save(paths.dreaming_sweep_log_path, "")


def ensure_daily_note(paths: ControlMeshPaths, note_date: date) -> Path:
    """Create a daily note skeleton if missing and return its path."""
    initialize_memory_v2(paths)
    note_path = daily_note_path(paths, note_date)
    if not note_path.exists():
        content = f"""# Daily Memory: {note_date.isoformat()}

## Events

## Signals

## Promotion Candidates
"""
        atomic_text_save(note_path, content)
    return note_path


def append_dream_entry(
    paths: ControlMeshPaths,
    *,
    title: str,
    body: str,
    dreamed_at: datetime | None = None,
) -> None:
    """Append a reviewable dream entry to ``DREAMS.md``."""
    initialize_memory_v2(paths)
    stamp = (dreamed_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")
    existing = paths.dream_diary_path.read_text(encoding="utf-8").rstrip()
    entry = f"\n\n## {stamp} - {title}\n\n{body.strip()}\n"
    atomic_text_save(paths.dream_diary_path, existing + entry)
