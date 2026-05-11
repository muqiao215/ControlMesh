"""Lightweight runtime registry, leases, slots, and repo worktree helpers."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from controlmesh.cli.introspection import ProviderIntrospection
from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.tasks.models import TaskEntry
from controlmesh.workspace.paths import ControlMeshPaths

_LIVE_STATUSES = frozenset({"created", "running", "waiting"})
_RELEASE_WORKUNITS = frozenset({"github_release", "release_publish"})
_READONLY_WORKUNITS = frozenset({"code_review", "test_execution"})


def _now() -> float:
    return time.time()


def _read_mapping(path: Path, key: str) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        return {}
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _write_mapping(path: Path, key: str, value: dict[str, Any]) -> None:
    atomic_json_save(path, {key: value, "updated_at": _now()})


class RuntimeRegistry:
    """Persist runtime capability and health snapshots as small JSON files."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def record_provider_binding(
        self,
        *,
        requested_provider: str,
        requested_model: str,
        effective_provider: str,
        effective_model: str,
        process_label: str = "",
    ) -> None:
        registry = _read_mapping(self._paths.runtime_registry_path, "providers")
        key = requested_provider or effective_provider or "default"
        registry[key] = {
            "requested_provider": requested_provider,
            "requested_model": requested_model,
            "effective_provider": effective_provider,
            "effective_model": effective_model,
            "process_label": process_label,
            "checked_at": _now(),
        }
        _write_mapping(self._paths.runtime_registry_path, "providers", registry)

    def record_introspection(self, snapshot: ProviderIntrospection) -> None:
        health = _read_mapping(self._paths.runtime_health_path, "providers")
        health[snapshot.provider] = {
            "provider": snapshot.provider,
            "model": snapshot.model,
            "installed": snapshot.installed,
            "healthy": snapshot.healthy,
            "auth_status": snapshot.auth_status,
            "executable": snapshot.executable,
            "version": snapshot.version,
            "permission_mode": snapshot.permission_mode,
            "errors": list(snapshot.errors),
            "checked_at": snapshot.checked_at,
            "expires_at": snapshot.expires_at,
        }
        _write_mapping(self._paths.runtime_health_path, "providers", health)


class SlotManager:
    """Persist per-slot task leases used by routing/admission."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        raw_path = getattr(paths, "runtime_slots_path", None)
        self._path = raw_path if isinstance(raw_path, Path) else None

    def acquire(self, slot_name: str, *, task_id: str, capacity: int = 9999) -> bool:
        if self._path is None:
            return True
        if not slot_name:
            return True
        slots = _read_mapping(self._path, "slots")
        slot = slots.setdefault(slot_name, {"capacity": capacity, "leases": {}})
        leases = slot.setdefault("leases", {})
        self.reap_expired(max_age_seconds=24 * 3600)
        if task_id not in leases and len(leases) >= int(slot.get("capacity") or capacity):
            return False
        slot["capacity"] = capacity
        leases[task_id] = {"task_id": task_id, "acquired_at": _now()}
        _write_mapping(self._path, "slots", slots)
        return True

    def release(self, slot_name: str, *, task_id: str) -> None:
        if self._path is None:
            return
        if not slot_name:
            return
        slots = _read_mapping(self._path, "slots")
        slot = slots.get(slot_name)
        if not isinstance(slot, dict):
            return
        leases = slot.get("leases")
        if isinstance(leases, dict):
            leases.pop(task_id, None)
        _write_mapping(self._path, "slots", slots)

    def reap_expired(self, *, max_age_seconds: float) -> int:
        if self._path is None:
            return 0
        slots = _read_mapping(self._path, "slots")
        cutoff = _now() - max_age_seconds
        removed = 0
        for slot in slots.values():
            if not isinstance(slot, dict):
                continue
            leases = slot.get("leases")
            if not isinstance(leases, dict):
                continue
            for task_id, lease in list(leases.items()):
                if not isinstance(lease, dict) or float(lease.get("acquired_at") or 0.0) < cutoff:
                    leases.pop(task_id, None)
                    removed += 1
        if removed:
            _write_mapping(self._path, "slots", slots)
        return removed


class ProcessLeaseStore:
    """Persistent process lease ledger for foreground/background subprocesses."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def register(
        self,
        *,
        chat_id: object,
        topic_id: object | None,
        label: str,
        pid: int | None,
        provider: str = "",
    ) -> None:
        processes = _read_mapping(self._path, "processes")
        lease_id = self._lease_id(chat_id, label, pid)
        processes[lease_id] = {
            "lease_id": lease_id,
            "chat_id": chat_id,
            "topic_id": topic_id,
            "label": label,
            "pid": pid,
            "provider": provider,
            "status": "running",
            "started_at": _now(),
            "heartbeat_at": _now(),
        }
        _write_mapping(self._path, "processes", processes)

    def unregister(self, *, chat_id: object, label: str, pid: int | None) -> None:
        processes = _read_mapping(self._path, "processes")
        lease_id = self._lease_id(chat_id, label, pid)
        processes.pop(lease_id, None)
        _write_mapping(self._path, "processes", processes)

    def find_by_label(self, *, chat_id: object, label: str) -> dict[str, Any] | None:
        processes = _read_mapping(self._path, "processes")
        for lease in processes.values():
            if not isinstance(lease, dict):
                continue
            if lease.get("chat_id") == chat_id and lease.get("label") == label:
                return dict(lease)
        return None

    def set_status(
        self,
        *,
        chat_id: object,
        label: str,
        pid: int | None,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        processes = _read_mapping(self._path, "processes")
        lease_id = self._lease_id(chat_id, label, pid)
        lease = processes.get(lease_id)
        if not isinstance(lease, dict):
            return
        lease["status"] = status
        lease["heartbeat_at"] = _now()
        if details:
            for key, value in details.items():
                lease[key] = value
        _write_mapping(self._path, "processes", processes)

    def mark_label_status(
        self,
        *,
        chat_id: object,
        label: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        processes = _read_mapping(self._path, "processes")
        changed = False
        for lease in processes.values():
            if not isinstance(lease, dict):
                continue
            if lease.get("chat_id") != chat_id or lease.get("label") != label:
                continue
            lease["status"] = status
            lease["heartbeat_at"] = _now()
            if details:
                for key, value in details.items():
                    lease[key] = value
            changed = True
        if changed:
            _write_mapping(self._path, "processes", processes)
        return changed

    def reap_dead(self) -> int:
        processes = _read_mapping(self._path, "processes")
        removed = 0
        for lease_id, lease in list(processes.items()):
            if not isinstance(lease, dict):
                processes.pop(lease_id, None)
                removed += 1
                continue
            pid = lease.get("pid")
            if not isinstance(pid, int) or not _pid_exists(pid):
                processes.pop(lease_id, None)
                removed += 1
        if removed:
            _write_mapping(self._path, "processes", processes)
        return removed

    @staticmethod
    def _lease_id(chat_id: object, label: str, pid: int | None) -> str:
        return f"{chat_id}:{label}:{pid or 'unknown'}"


@dataclass(frozen=True, slots=True)
class RepoBinding:
    """Task-local repository/worktree binding."""

    repo: str
    repo_path: Path
    worktree_path: Path
    base_ref: str
    commit_sha: str
    mode: str
    branch: str = ""
    repo_lock: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "repo": self.repo,
            "repo_path": str(self.repo_path),
            "worktree_path": str(self.worktree_path),
            "base_ref": self.base_ref,
            "commit_sha": self.commit_sha,
            "mode": self.mode,
        }
        if self.branch:
            payload["branch"] = self.branch
        if self.repo_lock:
            payload["repo_lock"] = self.repo_lock
        return payload


class RepoWorktreeManager:
    """Create isolated per-task git worktrees and release locks."""

    def __init__(self, paths: ControlMeshPaths) -> None:
        self._paths = paths

    def bind_task(self, entry: TaskEntry, *, repo_path: Path | None = None) -> RepoBinding | None:
        repo = self._resolve_repo_path(entry, repo_path)
        if repo is None:
            return None
        commit = _git(repo, "rev-parse", "HEAD")
        base_ref = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        worktree_path = self._paths.worktrees_dir / entry.task_id
        release_lock = self.release_lock_name(repo) if self._is_release(entry) else ""
        if self._is_release(entry):
            binding = RepoBinding(
                repo=repo.name,
                repo_path=repo,
                worktree_path=repo,
                base_ref=base_ref,
                commit_sha=commit,
                mode="release_locked",
                repo_lock=release_lock,
            )
        elif self._is_writable(entry):
            branch = f"task/{entry.task_id}"
            self._ensure_worktree(repo, worktree_path, branch=branch)
            binding = RepoBinding(
                repo=repo.name,
                repo_path=repo,
                worktree_path=worktree_path,
                base_ref=base_ref,
                commit_sha=commit,
                mode="writable_worktree",
                branch=branch,
            )
        else:
            self._ensure_worktree(repo, worktree_path, detach=commit)
            binding = RepoBinding(
                repo=repo.name,
                repo_path=repo,
                worktree_path=worktree_path,
                base_ref=base_ref,
                commit_sha=commit,
                mode="readonly",
            )
        self._write_binding(entry, binding)
        return binding

    def acquire_release_lock(self, repo_path: Path) -> Path:
        name = self.release_lock_name(repo_path)
        self._paths.runtime_locks_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._paths.runtime_locks_dir / f"repo-{name}.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"repo_lock": name, "pid": os.getpid(), "created_at": _now()}) + "\n")
        return lock_path

    def release_lock_name(self, repo_path: Path) -> str:
        return f"{repo_path.name}:release"

    def _write_binding(self, entry: TaskEntry, binding: RepoBinding) -> None:
        folder = Path(entry.tasks_dir) / entry.task_id if entry.tasks_dir else self._paths.tasks_dir / entry.task_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "REPO_BINDING.json").write_text(
            json.dumps(binding.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _ensure_worktree(
        self,
        repo: Path,
        worktree_path: Path,
        *,
        branch: str = "",
        detach: str = "",
    ) -> None:
        if worktree_path.exists():
            return
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if branch:
            _git(repo, "worktree", "add", "-B", branch, str(worktree_path), "HEAD")
            return
        _git(repo, "worktree", "add", "--detach", str(worktree_path), detach or "HEAD")

    def _resolve_repo_path(self, entry: TaskEntry, repo_path: Path | None) -> Path | None:
        candidates: list[Path] = []
        if repo_path is not None:
            candidates.append(repo_path)
        repo_meta = entry.phase_metadata.get("repo_path") or entry.phase_metadata.get("repo")
        if repo_meta and str(repo_meta).startswith(("/", "~", ".")):
            candidates.append(Path(str(repo_meta)).expanduser())
        framework_root = getattr(self._paths, "framework_root", None)
        if isinstance(framework_root, Path):
            candidates.append(framework_root)
        for candidate in candidates:
            if not isinstance(candidate, Path):
                continue
            resolved = candidate.resolve()
            if (resolved / ".git").exists() or _git(resolved, "rev-parse", "--git-dir", check=False):
                return resolved
        return None

    @staticmethod
    def _is_writable(entry: TaskEntry) -> bool:
        if entry.workunit_kind in _READONLY_WORKUNITS:
            return False
        return any(
            perm in {"repo_write", "git_write", "publish", "release_create"}
            for perm in entry.worker_business_permissions
        )

    @staticmethod
    def _is_release(entry: TaskEntry) -> bool:
        return (
            entry.workunit_kind in _RELEASE_WORKUNITS
            or entry.phase_metadata.get("gate_kind") == "release_publish"
            or "release" in entry.name.lower()
        )


def append_task_event(folder: Path, event_type: str, payload: dict[str, Any] | None = None) -> None:
    """Append a task-local event into events.jsonl."""
    folder.mkdir(parents=True, exist_ok=True)
    item = {
        "event_type": event_type,
        "created_at": _now(),
        "payload": payload or {},
    }
    with (folder / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()
