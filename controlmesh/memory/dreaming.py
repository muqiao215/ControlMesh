"""JSON-backed dreaming sweep state, checkpoints, locks, and sweep runner."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_text_save
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.memory.models import (
    DreamingCheckpoint,
    DreamingLock,
    DreamingSweepMode,
    DreamingSweepNoteResult,
    DreamingSweepResult,
    DreamingSweepState,
    PromotionSourceKind,
)
from controlmesh.memory.promotion import (
    apply_candidates,
    parse_promotion_candidates,
    preview_candidates,
)
from controlmesh.memory.store import append_dream_entry, initialize_memory_v2
from controlmesh.workspace.paths import ControlMeshPaths


@dataclass(frozen=True)
class _ProcessedNote:
    note_result: DreamingSweepNoteResult
    checkpoint: DreamingCheckpoint | None = None
    applied_keys: list[str] | None = None


@dataclass(frozen=True)
class _SweepContext:
    mode: DreamingSweepMode
    min_score: float
    processed_at: datetime


def load_sweep_state(paths: ControlMeshPaths) -> DreamingSweepState:
    """Load sweep state, falling back to defaults."""
    raw = load_json(paths.dreaming_sweep_state_path)
    if not isinstance(raw, dict):
        return DreamingSweepState()
    return DreamingSweepState.model_validate(raw)


def save_sweep_state(paths: ControlMeshPaths, state: DreamingSweepState) -> None:
    """Persist sweep state atomically."""
    atomic_json_save(paths.dreaming_sweep_state_path, state.model_dump(mode="json"))


def load_checkpoints(paths: ControlMeshPaths) -> dict[str, DreamingCheckpoint]:
    """Load dreaming checkpoints keyed by daily note date."""
    raw = load_json(paths.dreaming_checkpoints_path)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, DreamingCheckpoint] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = DreamingCheckpoint.model_validate(value)
    return result


def save_checkpoints(paths: ControlMeshPaths, checkpoints: dict[str, DreamingCheckpoint]) -> None:
    """Persist dreaming checkpoints atomically."""
    data = {key: checkpoint.model_dump(mode="json") for key, checkpoint in checkpoints.items()}
    atomic_json_save(paths.dreaming_checkpoints_path, data)


def acquire_dream_lock(
    paths: ControlMeshPaths,
    *,
    owner: str,
    now: datetime | None = None,
    ttl_seconds: int = 900,
) -> DreamingLock | None:
    """Acquire the dreaming lock or return ``None`` if it is still held."""
    current_time = now or datetime.now(UTC)
    lock = DreamingLock(
        owner=owner,
        acquired_at=current_time.isoformat(),
        expires_at=(current_time + timedelta(seconds=ttl_seconds)).isoformat(),
    )
    payload = json.dumps(lock.model_dump(mode="json"), ensure_ascii=False, indent=2)

    while True:
        try:
            fd = os.open(
                paths.dreaming_lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            raw = load_json(paths.dreaming_lock_path)
            if not isinstance(raw, dict):
                paths.dreaming_lock_path.unlink(missing_ok=True)
                continue
            active = DreamingLock.model_validate(raw)
            if datetime.fromisoformat(active.expires_at) > current_time:
                return None
            with suppress(FileNotFoundError):
                paths.dreaming_lock_path.unlink()
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
        except Exception:
            paths.dreaming_lock_path.unlink(missing_ok=True)
            raise
        return lock


def release_dream_lock(paths: ControlMeshPaths, *, owner: str) -> bool:
    """Release the dreaming lock when the owner matches."""
    raw = load_json(paths.dreaming_lock_path)
    if not isinstance(raw, dict):
        return False
    active = DreamingLock.model_validate(raw)
    if active.owner != owner:
        return False
    paths.dreaming_lock_path.unlink(missing_ok=True)
    return True


def preview_dreaming_sweep(
    paths: ControlMeshPaths,
    *,
    owner: str,
    now: datetime | None = None,
    min_score: float = 0.0,
) -> DreamingSweepResult:
    """Preview a deterministic local dreaming sweep over daily notes."""
    return _run_dreaming_sweep(
        paths,
        mode=DreamingSweepMode.PREVIEW,
        owner=owner,
        now=now,
        min_score=min_score,
    )


def apply_dreaming_sweep(
    paths: ControlMeshPaths,
    *,
    owner: str,
    now: datetime | None = None,
    min_score: float = 0.0,
) -> DreamingSweepResult:
    """Apply a deterministic local dreaming sweep over daily notes."""
    return _run_dreaming_sweep(
        paths,
        mode=DreamingSweepMode.APPLY,
        owner=owner,
        now=now,
        min_score=min_score,
    )


def _run_dreaming_sweep(
    paths: ControlMeshPaths,
    *,
    mode: DreamingSweepMode,
    owner: str,
    now: datetime | None,
    min_score: float,
) -> DreamingSweepResult:
    initialize_memory_v2(paths)
    current_time = now or datetime.now(UTC)
    lock = acquire_dream_lock(paths, owner=owner, now=current_time)
    if lock is None:
        msg = "dreaming sweep already locked"
        raise RuntimeError(msg)

    state = _mark_sweep_running(paths, mode=mode, started_at=current_time)

    checkpoints = load_checkpoints(paths)
    context = _SweepContext(mode=mode, min_score=min_score, processed_at=current_time)

    try:
        result, checkpoints = _collect_sweep_result(
            paths,
            checkpoints=checkpoints,
            context=context,
            owner=owner,
            started_at=lock.acquired_at,
        )
        _persist_sweep_result(
            paths,
            mode=mode,
            checkpoints=checkpoints,
            result=result,
            dreamed_at=current_time,
        )
    except Exception as exc:
        state.status = "failed"
        state.last_run_mode = mode.value
        state.last_completed_at = current_time.isoformat()
        state.last_error = str(exc)
        save_sweep_state(paths, state)
        raise
    finally:
        release_dream_lock(paths, owner=owner)

    _update_sweep_state(paths, state=state, mode=mode, result=result)
    return result


def _iter_daily_note_paths(paths: ControlMeshPaths) -> list[Path]:
    return sorted(path for path in paths.memory_v2_daily_dir.glob("*.md") if path.is_file())


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _collect_sweep_result(
    paths: ControlMeshPaths,
    *,
    checkpoints: dict[str, DreamingCheckpoint],
    context: _SweepContext,
    owner: str,
    started_at: str,
) -> tuple[DreamingSweepResult, dict[str, DreamingCheckpoint]]:
    note_results: list[DreamingSweepNoteResult] = []
    promoted_candidate_keys: list[str] = []
    changed_notes = 0
    skipped_unchanged_notes = 0
    selected_count = 0
    applied_count = 0
    last_processed_day: str | None = None

    for note_path in _iter_daily_note_paths(paths):
        processed_note = _process_daily_note(
            paths,
            note_path=note_path,
            checkpoint=checkpoints.get(note_path.stem),
            context=context,
        )
        note_result = processed_note.note_result
        note_results.append(note_result)
        last_processed_day = note_result.note_date

        if note_result.changed:
            changed_notes += 1
            selected_count += note_result.selected_count
            applied_count += note_result.applied_count
            if processed_note.checkpoint is not None:
                checkpoints[note_result.note_date] = processed_note.checkpoint
            if processed_note.applied_keys:
                promoted_candidate_keys.extend(processed_note.applied_keys)
            continue

        skipped_unchanged_notes += 1

    return (
        DreamingSweepResult(
            mode=context.mode,
            owner=owner,
            started_at=started_at,
            completed_at=context.processed_at.isoformat(),
            processed_notes=len(note_results),
            changed_notes=changed_notes,
            skipped_unchanged_notes=skipped_unchanged_notes,
            selected_count=selected_count,
            applied_count=applied_count,
            last_processed_day=last_processed_day,
            promoted_candidate_keys=promoted_candidate_keys,
            note_results=note_results,
        ),
        checkpoints,
    )


def _process_daily_note(
    paths: ControlMeshPaths,
    *,
    note_path: Path,
    checkpoint: DreamingCheckpoint | None,
    context: _SweepContext,
) -> _ProcessedNote:
    note_date = date.fromisoformat(note_path.stem)
    note_date_text = note_date.isoformat()
    note_text = note_path.read_text(encoding="utf-8")
    note_hash = _hash_content(note_text)
    relative_path = note_path.relative_to(paths.workspace).as_posix()

    if checkpoint is not None and checkpoint.note_hash == note_hash:
        return _ProcessedNote(
            note_result=DreamingSweepNoteResult(
                note_date=note_date_text,
                note_path=relative_path,
                note_hash=note_hash,
                changed=False,
                candidate_count=len(checkpoint.candidate_keys),
            )
        )

    candidates = parse_promotion_candidates(
        note_text,
        source_path=Path(relative_path),
        source_date=note_date,
        source_kind=PromotionSourceKind.DREAMING_SWEEP,
    )
    preview = preview_candidates(paths, candidates, min_score=context.min_score)
    applied_keys: list[str] = []
    applied_count = 0
    next_checkpoint: DreamingCheckpoint | None = None

    if context.mode is DreamingSweepMode.APPLY:
        apply_result = apply_candidates(
            paths,
            candidates,
            min_score=context.min_score,
            applied_on=note_date,
        )
        applied_count = apply_result.applied_count
        applied_keys = apply_result.applied_keys
        next_checkpoint = DreamingCheckpoint(
            note_date=note_date_text,
            note_path=relative_path,
            note_hash=note_hash,
            candidate_keys=[candidate.key for candidate in candidates],
            processed_at=context.processed_at.isoformat(),
        )

    return _ProcessedNote(
        note_result=DreamingSweepNoteResult(
            note_date=note_date_text,
            note_path=relative_path,
            note_hash=note_hash,
            changed=True,
            candidate_count=len(candidates),
            selected_count=len(preview.selected),
            applied_count=applied_count,
            skipped_existing=preview.skipped_existing,
            skipped_low_score=preview.skipped_low_score,
        ),
        checkpoint=next_checkpoint,
        applied_keys=applied_keys,
    )


def _append_sweep_log(paths: ControlMeshPaths, result: DreamingSweepResult) -> None:
    existing = paths.dreaming_sweep_log_path.read_text(encoding="utf-8")
    payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    separator = "" if existing.endswith("\n") or not existing else "\n"
    atomic_text_save(paths.dreaming_sweep_log_path, f"{existing}{separator}{payload}\n")


def _mark_sweep_running(
    paths: ControlMeshPaths,
    *,
    mode: DreamingSweepMode,
    started_at: datetime,
) -> DreamingSweepState:
    state = load_sweep_state(paths)
    state.status = "running"
    state.last_run_mode = mode.value
    state.last_started_at = started_at.isoformat()
    state.last_error = None
    save_sweep_state(paths, state)
    return state


def _persist_sweep_result(
    paths: ControlMeshPaths,
    *,
    mode: DreamingSweepMode,
    checkpoints: dict[str, DreamingCheckpoint],
    result: DreamingSweepResult,
    dreamed_at: datetime,
) -> None:
    if mode is DreamingSweepMode.APPLY:
        save_checkpoints(paths, checkpoints)
        if result.changed_notes > 0 or result.applied_count > 0:
            append_dream_entry(
                paths,
                title="Dreaming sweep apply",
                body=_render_sweep_summary(result),
                dreamed_at=dreamed_at,
            )
    _append_sweep_log(paths, result)


def _update_sweep_state(
    paths: ControlMeshPaths,
    *,
    state: DreamingSweepState,
    mode: DreamingSweepMode,
    result: DreamingSweepResult,
) -> None:
    state.status = "previewed" if mode is DreamingSweepMode.PREVIEW else "completed"
    state.last_run_mode = mode.value
    state.last_completed_at = result.completed_at
    state.last_processed_day = result.last_processed_day
    state.last_changed_notes = result.changed_notes
    state.last_selected_count = result.selected_count
    state.last_applied_count = result.applied_count
    state.last_error = None
    state.promoted_candidate_keys = list(result.promoted_candidate_keys)
    save_sweep_state(paths, state)


def _render_sweep_summary(result: DreamingSweepResult) -> str:
    lines = [
        f"mode: {result.mode.value}",
        f"processed_notes: {result.processed_notes}",
        f"changed_notes: {result.changed_notes}",
        f"skipped_unchanged_notes: {result.skipped_unchanged_notes}",
        f"selected_count: {result.selected_count}",
        f"applied_count: {result.applied_count}",
    ]
    if result.last_processed_day is not None:
        lines.append(f"last_processed_day: {result.last_processed_day}")
    if result.promoted_candidate_keys:
        lines.append(
            "promoted_candidate_keys: " + ", ".join(result.promoted_candidate_keys)
        )
    note_lines = [
        (
            f"- {note_result.note_date}: changed={note_result.changed}, "
            f"selected={note_result.selected_count}, applied={note_result.applied_count}"
        )
        for note_result in result.note_results
    ]
    return "\n".join([*lines, "", "notes:", *note_lines])
