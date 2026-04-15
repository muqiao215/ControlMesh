"""Bounded canonical markdown section writer for promotion safety."""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum, auto
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator


class CanonicalTargetFile(StrEnum):
    """Canonical markdown files allowed in the first safety pack."""

    TASK_PLAN = auto()
    PROGRESS = auto()


class CanonicalSectionName(StrEnum):
    """Canonical sections that may be written by the safety pack."""

    CURRENT_STATUS = auto()
    CURRENT_STATE = auto()
    LATEST_CHECKPOINT = auto()
    LATEST_COMPLETED = auto()
    NEXT_ACTION = auto()
    NOTES = auto()


class CanonicalWriteShape(StrEnum):
    """Allowed section patch shapes."""

    SECTION_REPLACE = auto()
    MARKER_BLOCK_UPSERT = auto()


class CanonicalSectionPatch(BaseModel):
    """One bounded canonical section patch."""

    model_config = ConfigDict(frozen=True)

    target_file: CanonicalTargetFile
    section: CanonicalSectionName
    shape: CanonicalWriteShape
    body: str
    marker: str | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> CanonicalSectionPatch:
        if not self.body.strip():
            msg = "canonical section patch body must not be empty"
            raise ValueError(msg)
        if self.target_file is CanonicalTargetFile.TASK_PLAN:
            if self.section is not CanonicalSectionName.CURRENT_STATUS:
                msg = "task_plan patches may only target current_status"
                raise ValueError(msg)
            if self.shape is not CanonicalWriteShape.SECTION_REPLACE:
                msg = "task_plan current_status must use section_replace"
                raise ValueError(msg)
        if self.target_file is CanonicalTargetFile.PROGRESS:
            if self.section in {
                CanonicalSectionName.LATEST_COMPLETED,
                CanonicalSectionName.CURRENT_STATE,
                CanonicalSectionName.NEXT_ACTION,
                CanonicalSectionName.LATEST_CHECKPOINT,
            } and self.shape is not CanonicalWriteShape.SECTION_REPLACE:
                msg = "progress section patches must use section_replace"
                raise ValueError(msg)
            if self.section is CanonicalSectionName.NOTES:
                if self.shape is not CanonicalWriteShape.MARKER_BLOCK_UPSERT:
                    msg = "progress notes patches must use marker_block_upsert"
                    raise ValueError(msg)
                if self.marker is None or not self.marker.strip():
                    msg = "progress notes marker block patches require marker"
                    raise ValueError(msg)
        return self


class CanonicalSectionWriter:
    """Apply bounded markdown section patches without widening write authority."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def write(
        self,
        *,
        line: str,
        patches: tuple[CanonicalSectionPatch, ...],
        pre_write_check: Callable[[], None] | None = None,
    ) -> tuple[str, ...]:
        if pre_write_check is not None:
            pre_write_check()
        file_to_patches: dict[CanonicalTargetFile, list[CanonicalSectionPatch]] = {}
        for patch in patches:
            file_to_patches.setdefault(patch.target_file, []).append(patch)

        updated_files: list[str] = []
        for target_file, grouped_patches in file_to_patches.items():
            path = self._path_for(line, target_file)
            text = path.read_text(encoding="utf-8")
            for patch in grouped_patches:
                text = self._apply_patch(text, patch)
            path.write_text(text, encoding="utf-8")
            updated_files.append(str(path))
        return tuple(updated_files)

    def _path_for(self, line: str, target_file: CanonicalTargetFile) -> Path:
        line_dir = self._root / "plans" / line
        name = "task_plan.md" if target_file is CanonicalTargetFile.TASK_PLAN else "progress.md"
        path = line_dir / name
        if not path.exists():
            msg = f"promotion target line '{line}' is missing canonical plan files"
            raise FileNotFoundError(msg)
        return path

    def _apply_patch(self, text: str, patch: CanonicalSectionPatch) -> str:
        if patch.shape is CanonicalWriteShape.SECTION_REPLACE:
            return _replace_markdown_section(text, _heading_for_section(patch.section), patch.body)
        return _upsert_notes_block(text, marker=patch.marker or "", block_body=patch.body)


def _heading_for_section(section: CanonicalSectionName) -> str:
    return {
        CanonicalSectionName.CURRENT_STATUS: "Current Status",
        CanonicalSectionName.LATEST_COMPLETED: "Latest Completed",
        CanonicalSectionName.CURRENT_STATE: "Current State",
        CanonicalSectionName.NEXT_ACTION: "Next Action",
        CanonicalSectionName.LATEST_CHECKPOINT: "Latest Checkpoint",
        CanonicalSectionName.NOTES: "Notes",
    }[section]


def _replace_markdown_section(text: str, heading: str, new_body: str) -> str:
    pattern = re.compile(
        rf"(^# {re.escape(heading)}\n)(.*?)(?=^# |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    replacement = rf"\1{new_body.strip()}\n\n"
    updated, count = pattern.subn(replacement, text, count=1)
    if count == 0:
        msg = f"missing markdown section '{heading}'"
        raise ValueError(msg)
    return updated


def _upsert_notes_block(text: str, *, marker: str, block_body: str) -> str:
    pattern = re.compile(
        r"(^# Notes\n)(.*?)(?=^# |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        msg = "missing markdown section 'Notes'"
        raise ValueError(msg)
    existing_body = match.group(2).strip()
    block = f"<!-- {marker}:start -->\n{block_body.strip()}\n<!-- {marker}:end -->"
    block_pattern = re.compile(
        rf"<!-- {re.escape(marker)}:start -->.*?<!-- {re.escape(marker)}:end -->",
        re.DOTALL,
    )
    if block_pattern.search(existing_body):
        new_body = block_pattern.sub(block, existing_body)
    elif existing_body:
        new_body = f"{existing_body}\n\n{block}"
    else:
        new_body = block
    replacement = f"# Notes\n{new_body}\n\n"
    return text[: match.start()] + replacement + text[match.end() :]


__all__ = [
    "CanonicalSectionName",
    "CanonicalSectionPatch",
    "CanonicalSectionWriter",
    "CanonicalTargetFile",
    "CanonicalWriteShape",
]
