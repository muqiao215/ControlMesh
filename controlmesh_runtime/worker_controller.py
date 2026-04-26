"""Typed worker controller surface and ControlMesh adapter for the harness runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from enum import StrEnum, auto
from pathlib import Path
from typing import Any, Protocol

from controlmesh.team.contracts import (
    TEAM_NAME_SAFE_PATTERN,
    WORKER_NAME_SAFE_PATTERN,
    ensure_safe_identifier,
)
from controlmesh.team.models import TeamManifest, TeamWorkerRuntimeState
from controlmesh.team.runtime_control import TeamRuntimeController
from controlmesh.team.state import TeamStateStore
from controlmesh_runtime.events import FailureClass
from controlmesh_runtime.worker_state import WorkerState, WorkerStatus


class WorkerControllerErrorCode(StrEnum):
    """Minimal worker-controller failure taxonomy."""

    NOT_FOUND = auto()
    INVALID_REQUEST = auto()
    CONFLICT = auto()
    TIMEOUT = auto()
    INTERNAL = auto()


class WorkerControllerError(RuntimeError):
    """Structured worker-controller error."""

    def __init__(
        self,
        *,
        code: WorkerControllerErrorCode,
        failure_class: FailureClass,
        message: str,
        worker_id: str,
        operation: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failure_class = failure_class
        self.worker_id = worker_id
        self.operation = operation


class WorkerController(Protocol):
    """Minimal runtime-owned worker lifecycle surface."""

    async def create(self, worker_id: str) -> WorkerState: ...

    async def await_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> WorkerState: ...

    async def fetch_state(self, worker_id: str) -> WorkerState | None: ...

    async def restart(self, worker_id: str) -> WorkerState: ...

    async def terminate(self, worker_id: str) -> WorkerState: ...


class ControlMeshWorkerController:
    """Adapt ControlMesh's team runtime controller into the harness worker surface."""

    def __init__(
        self,
        *,
        orchestrator: Any,
        team_name: str,
        team_state_root: Path | str,
        named_sessions_path: Path | str | None = None,
        keepalive_interval_seconds: float | None = 60.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        if poll_interval_seconds <= 0:
            msg = "poll_interval_seconds must be positive"
            raise ValueError(msg)
        self._team_name = ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, team_name, "team_name")
        self._team_state_root = Path(team_state_root)
        self._controller = TeamRuntimeController(
            orchestrator=orchestrator,
            team_state_root=self._team_state_root,
            named_sessions_path=named_sessions_path,
            keepalive_interval_seconds=keepalive_interval_seconds,
        )
        self._poll_interval_seconds = poll_interval_seconds

    async def shutdown(self) -> None:
        """Release any adapter-owned keepalive tasks."""
        await self._controller.shutdown()

    async def create(self, worker_id: str) -> WorkerState:
        worker = self._normalize_worker_id(worker_id)
        await self._execute("start-worker-runtime", worker)
        return await self._require_state(worker, operation="create")

    async def await_ready(
        self,
        worker_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> WorkerState:
        worker = self._normalize_worker_id(worker_id)
        poll_interval = poll_interval_seconds or self._poll_interval_seconds
        if poll_interval <= 0:
            msg = "poll_interval_seconds must be positive"
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.INVALID_REQUEST,
                failure_class=FailureClass.CONTRACT,
                message=msg,
                worker_id=worker,
                operation="await_ready",
            )
        loop = asyncio.get_running_loop()
        deadline = None if timeout_seconds is None else loop.time() + timeout_seconds
        while True:
            state = await self.fetch_state(worker)
            if state is not None and state.status in {WorkerStatus.READY, WorkerStatus.RUNNING}:
                return state
            if state is not None and state.status != WorkerStatus.SPAWNING:
                reason = state.status_reason or f"worker entered {state.status.value}"
                raise WorkerControllerError(
                    code=WorkerControllerErrorCode.CONFLICT,
                    failure_class=FailureClass.TOOL_RUNTIME,
                    message=f"worker '{worker}' cannot become ready: {reason}",
                    worker_id=worker,
                    operation="await_ready",
                )
            if deadline is not None and loop.time() >= deadline:
                msg = f"worker '{worker}' did not become ready before timeout"
                raise WorkerControllerError(
                    code=WorkerControllerErrorCode.TIMEOUT,
                    failure_class=FailureClass.INFRA,
                    message=msg,
                    worker_id=worker,
                    operation="await_ready",
                )
            await asyncio.sleep(poll_interval)

    async def fetch_state(self, worker_id: str) -> WorkerState | None:
        worker = self._normalize_worker_id(worker_id)
        store = TeamStateStore(self._team_state_root, self._team_name, create=False)
        manifest = self._read_manifest(store, worker)
        try:
            manifest.get_worker(worker)
        except ValueError as exc:
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.NOT_FOUND,
                failure_class=FailureClass.CONTRACT,
                message=str(exc),
                worker_id=worker,
                operation="fetch_state",
            ) from exc
        try:
            runtime = store.get_worker_runtime(worker)
        except FileNotFoundError:
            return None
        return _map_controlmesh_runtime_state(runtime)

    async def restart(self, worker_id: str) -> WorkerState:
        worker = self._normalize_worker_id(worker_id)
        await self.terminate(worker)
        return await self.create(worker)

    async def terminate(self, worker_id: str) -> WorkerState:
        worker = self._normalize_worker_id(worker_id)
        await self._execute("stop-worker-runtime", worker)
        return await self._require_state(worker, operation="terminate")

    async def _require_state(self, worker_id: str, *, operation: str) -> WorkerState:
        state = await self.fetch_state(worker_id)
        if state is not None:
            return state
        msg = f"worker '{worker_id}' state missing after {operation}"
        raise WorkerControllerError(
            code=WorkerControllerErrorCode.INTERNAL,
            failure_class=FailureClass.TOOL_RUNTIME,
            message=msg,
            worker_id=worker_id,
            operation=operation,
        )

    async def _execute(self, operation: str, worker_id: str) -> dict[str, Any]:
        result = await self._controller.execute(
            operation,
            {"team_name": self._team_name, "worker": worker_id},
        )
        ok = bool(result.get("ok"))
        if ok:
            return result
        error = result.get("error")
        if not isinstance(error, Mapping):
            msg = f"worker controller operation '{operation}' failed without error payload"
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.INTERNAL,
                failure_class=FailureClass.TOOL_RUNTIME,
                message=msg,
                worker_id=worker_id,
                operation=operation,
            )
        raw_code = str(error.get("code") or "internal_error")
        message = str(error.get("message") or f"worker controller operation '{operation}' failed")
        code = _classify_controlmesh_error(raw_code, message)
        raise WorkerControllerError(
            code=code,
            failure_class=_failure_class_for_error(code),
            message=message,
            worker_id=worker_id,
            operation=operation,
        )

    def _normalize_worker_id(self, worker_id: str) -> str:
        try:
            return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, worker_id, "worker_id")
        except ValueError as exc:
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.INVALID_REQUEST,
                failure_class=FailureClass.CONTRACT,
                message=str(exc),
                worker_id=worker_id,
                operation="normalize_worker_id",
            ) from exc

    def _read_manifest(self, store: TeamStateStore, worker_id: str) -> TeamManifest:
        try:
            return store.read_manifest()
        except FileNotFoundError as exc:
            msg = f"unknown team '{self._team_name}'"
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.NOT_FOUND,
                failure_class=FailureClass.CONTRACT,
                message=msg,
                worker_id=worker_id,
                operation="read_manifest",
            ) from exc
        except ValueError as exc:
            raise WorkerControllerError(
                code=WorkerControllerErrorCode.INVALID_REQUEST,
                failure_class=FailureClass.CONTRACT,
                message=str(exc),
                worker_id=worker_id,
                operation="read_manifest",
            ) from exc


def _classify_controlmesh_error(raw_code: str, message: str) -> WorkerControllerErrorCode:
    normalized = message.lower()
    if raw_code == "not_found" or normalized.startswith("unknown worker"):
        return WorkerControllerErrorCode.NOT_FOUND
    if raw_code == "invalid_request" and "busy" in normalized:
        return WorkerControllerErrorCode.CONFLICT
    if raw_code == "invalid_request":
        return WorkerControllerErrorCode.INVALID_REQUEST
    return WorkerControllerErrorCode.INTERNAL


def _failure_class_for_error(code: WorkerControllerErrorCode) -> FailureClass:
    if code in {WorkerControllerErrorCode.NOT_FOUND, WorkerControllerErrorCode.INVALID_REQUEST}:
        return FailureClass.CONTRACT
    if code == WorkerControllerErrorCode.TIMEOUT:
        return FailureClass.INFRA
    return FailureClass.TOOL_RUNTIME


def _map_controlmesh_runtime_state(runtime: TeamWorkerRuntimeState) -> WorkerState:
    status_map = {
        "created": WorkerStatus.SPAWNING,
        "starting": WorkerStatus.SPAWNING,
        "ready": WorkerStatus.READY,
        "busy": WorkerStatus.RUNNING,
        "unhealthy": WorkerStatus.DEGRADED,
        "stopped": WorkerStatus.FINISHED,
        "lost": WorkerStatus.FAILED,
    }
    reason = runtime.health_reason
    if reason is None:
        reason = {
            "created": "controlmesh runtime created",
            "starting": "controlmesh runtime starting",
            "stopped": "controlmesh runtime stopped",
        }.get(runtime.status)
    return WorkerState(
        worker_id=runtime.worker,
        status=status_map[runtime.status],
        status_reason=reason,
        updated_at=runtime.updated_at or runtime.heartbeat_at or runtime.created_at or runtime.stopped_at,
    )


__all__ = [
    "ControlMeshWorkerController",
    "WorkerController",
    "WorkerControllerError",
    "WorkerControllerErrorCode",
]
