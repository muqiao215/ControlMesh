"""Fail-closed artifact file access primitives for the planned download API."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO, Self

from controlmesh.api.admin_read import AdminHistoryCatalogReader
from controlmesh.api.protocol_adapters import task_artifact_to_protocol


class InvalidArtifactPathError(ValueError):
    """Raised when a public artifact relative path is lexically invalid."""


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when an artifact cannot be accessed without crossing its boundary."""


@dataclass(frozen=True, slots=True)
class OpenedArtifact:
    """Metadata and an already validated binary stream for one artifact."""

    stream: BinaryIO
    relative_path: str
    name: str
    mime: str
    size: int

    def close(self) -> None:
        """Close the validated stream."""
        self.stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


def validate_artifact_relative_path(raw_path: str) -> PurePosixPath:
    """Validate the public POSIX-style path used to identify an artifact."""
    if not raw_path or raw_path.lower().startswith("file:"):
        raise InvalidArtifactPathError("artifact path is invalid")
    if "\\" in raw_path or any(ord(character) < 32 or ord(character) == 127 for character in raw_path):
        raise InvalidArtifactPathError("artifact path is invalid")

    windows_path = PureWindowsPath(raw_path)
    parts = raw_path.split("/")
    if raw_path.startswith("/") or windows_path.drive or any(part in {"", ".", ".."} for part in parts):
        raise InvalidArtifactPathError("artifact path is invalid")
    return PurePosixPath(*parts)


def open_task_artifact(
    reader: AdminHistoryCatalogReader,
    task_id: str,
    raw_relative_path: str,
) -> OpenedArtifact:
    """Open an allowlisted task artifact without reopening an unchecked path."""
    relative_path = validate_artifact_relative_path(raw_relative_path)
    task_folder = reader.task_folder(task_id)
    if task_folder is None:
        raise ArtifactNotFoundError("artifact not found")

    try:
        resolved_folder = task_folder.resolve(strict=True)
        if not resolved_folder.is_dir():
            raise ArtifactNotFoundError("artifact not found")
        candidate = resolved_folder.joinpath(*relative_path.parts)
        artifact = task_artifact_to_protocol(task_id, resolved_folder, candidate)
    except (OSError, RuntimeError) as exc:
        raise ArtifactNotFoundError("artifact not found") from exc

    if artifact is None or artifact.relative_path != relative_path.as_posix():
        raise ArtifactNotFoundError("artifact not found")

    stream, file_stat = _open_regular_file_beneath(resolved_folder, relative_path.parts)
    return OpenedArtifact(
        stream=stream,
        relative_path=relative_path.as_posix(),
        name=relative_path.name,
        mime=artifact.mime or "application/octet-stream",
        size=file_stat.st_size,
    )


def _open_regular_file_beneath(root: Path, parts: tuple[str, ...]) -> tuple[BinaryIO, os.stat_result]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or os.open not in os.supports_dir_fd:
        raise ArtifactNotFoundError("artifact not found")

    directory_flags = os.O_RDONLY | directory | nofollow
    file_flags = os.O_RDONLY | nofollow
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags |= close_on_exec
    file_flags |= close_on_exec

    directory_fd: int | None = None
    file_fd: int | None = None
    opened: tuple[BinaryIO, os.stat_result]
    try:
        directory_fd = os.open(root, directory_flags)
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        file_stat = os.fstat(file_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ArtifactNotFoundError("artifact not found")
        stream = os.fdopen(file_fd, "rb", closefd=True)
        file_fd = None
        opened = stream, file_stat
    except (OSError, RuntimeError) as exc:
        raise ArtifactNotFoundError("artifact not found") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)
    return opened
