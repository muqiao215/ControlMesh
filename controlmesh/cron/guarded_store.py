"""A02 compatibility repair: all cooperating JSON writers lock + reload + mutate.

The sidecar lock supports POSIX flock and Windows byte-range locking; it is never unlinked.
Uncooperative watchdog/Ansible/direct writes remain outside this guarantee.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar
from collections.abc import Callable, Iterator

T = TypeVar("T")
MAX_REGISTRY_BYTES = 16 * 1024 * 1024


class CorruptRegistryError(ValueError):
    pass


class LockedJsonJobs:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).absolute()
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A different fd for every operation also serializes threads in one process.
        if self.lock_path.is_symlink():
            raise ValueError("symlink_lock_not_supported")
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if sys.platform == "win32":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_REGISTRY_BYTES + 1)
        except FileNotFoundError:
            return {"jobs": []}
        if len(raw) > MAX_REGISTRY_BYTES:
            raise CorruptRegistryError("registry_too_large")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise CorruptRegistryError(
                "invalid_json; refusing to replace it with an empty registry"
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise CorruptRegistryError("expected object containing jobs array")
        ids: set[str] = set()
        for job in data["jobs"]:
            if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not job["id"]:
                raise CorruptRegistryError("invalid job identity")
            if job["id"] in ids:
                raise CorruptRegistryError("duplicate job identity")
            ids.add(job["id"])
        return data

    def mutate(self, operation: Callable[[dict[str, Any]], T]) -> tuple[T, dict[str, Any]]:
        with self._lock():
            if self.path.is_symlink():
                raise ValueError("symlink_registry_not_supported")
            data = self._read()  # Never use a caller's cached copy here.
            before = copy.deepcopy(data)
            result = operation(data)
            # Validate on-disk shape again before writing (unknown metadata is preserved).
            if not isinstance(data.get("jobs"), list):
                raise ValueError("operation removed jobs array")
            ids = [row.get("id") for row in data["jobs"] if isinstance(row, dict)]
            if (
                len(ids) != len(data["jobs"])
                or len(ids) != len(set(ids))
                or any(not isinstance(i, str) or not i for i in ids)
            ):
                raise ValueError("operation produced invalid job identities")
            if data != before:
                self._atomic_write(data)
            return result, copy.deepcopy(data)

    def _atomic_write(self, data: dict[str, Any]) -> None:
        payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        if len(payload) > MAX_REGISTRY_BYTES:
            raise ValueError("registry_too_large")
        fd, name = tempfile.mkstemp(prefix="." + self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                # This registry can contain operational instructions; do not broaden permissions.
                if sys.platform != "win32":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            Path(name).replace(self.path)
            if sys.platform != "win32":
                dir_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        finally:
            Path(name).unlink(missing_ok=True)
