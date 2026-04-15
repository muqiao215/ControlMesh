"""Narrow worker runtime start/stop automation for named-session-backed teams."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from controlmesh.cli.types import AgentRequest
from controlmesh.config import resolve_timeout
from controlmesh.team.contracts import (
    TEAM_NAME_SAFE_PATTERN,
    WORKER_NAME_SAFE_PATTERN,
    ensure_safe_identifier,
)
from controlmesh.team.models import TeamManifest, TeamRuntimeContext, TeamWorkerRuntimeState
from controlmesh.team.runtime_attachment import TeamRuntimeAttachmentManager
from controlmesh.team.state import TeamStateStore
from controlmesh.team.state.recovery import (
    TeamControlSnapshotRecoveryAdvice,
    TeamControlSnapshotRecoveryAdvisor,
    default_runtime_recovery_snapshot_max_age_seconds,
)
from controlmesh.workspace.paths import resolve_paths

_START_OPERATION = "start-worker-runtime"
_STOP_OPERATION = "stop-worker-runtime"
_HEARTBEAT_OPERATION = "heartbeat-worker-runtime"
TEAM_RUNTIME_LIFECYCLE_OPERATIONS = frozenset(
    {_START_OPERATION, _STOP_OPERATION, _HEARTBEAT_OPERATION}
)
_DEFAULT_KEEPALIVE_INTERVAL_SECONDS = 60.0
_LIVE_RUNTIME_STATUSES = frozenset({"starting", "ready", "busy", "unhealthy"})


def _success(operation: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "data": data,
    }


def _error(operation: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": False,
        "operation": operation,
        "error": {"code": code, "message": message},
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _should_skip_runtime_recovery_from_snapshot(
    advice: TeamControlSnapshotRecoveryAdvice,
) -> bool:
    if advice.status != "usable" or advice.snapshot is None:
        return False
    live_runtime_count = sum(
        advice.snapshot.runtimes.counts.get(status, 0)
        for status in _LIVE_RUNTIME_STATUSES
    )
    return live_runtime_count == 0


class TeamRuntimeController:
    """Attach lifecycle operations to the real named-session runtime unit."""

    def __init__(
        self,
        *,
        orchestrator: Any,
        team_state_root: Path | str | None = None,
        named_sessions_path: Path | str | None = None,
        keepalive_interval_seconds: float | None = _DEFAULT_KEEPALIVE_INTERVAL_SECONDS,
    ) -> None:
        if keepalive_interval_seconds is not None and keepalive_interval_seconds <= 0:
            msg = "keepalive_interval_seconds must be positive when provided"
            raise ValueError(msg)
        self._orchestrator = orchestrator
        paths = resolve_paths()
        self._team_state_root = (
            Path(team_state_root) if team_state_root is not None else paths.team_state_dir
        )
        self._snapshot_recovery_advisor = TeamControlSnapshotRecoveryAdvisor(
            paths,
            state_root=self._team_state_root,
        )
        if named_sessions_path is None:
            registry = getattr(orchestrator, "named_sessions", None)
            named_sessions_path = getattr(registry, "path", None)
        self._attachments = TeamRuntimeAttachmentManager(named_sessions_path=named_sessions_path)
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._keepalive_interval_seconds = keepalive_interval_seconds
        self._keepalive_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    @property
    def operations(self) -> frozenset[str]:
        return TEAM_RUNTIME_LIFECYCLE_OPERATIONS

    async def shutdown(self) -> None:
        """Cancel any bounded keepalive tasks owned by this controller."""
        tasks = list(self._keepalive_tasks.values())
        self._keepalive_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def recover_live_runtimes(self) -> list[TeamWorkerRuntimeState]:
        """Recover still-live named-session runtimes from canonical persisted team state."""
        recovered: list[TeamWorkerRuntimeState] = []
        recovery_now = _utc_now()
        for team_name in self._team_names():
            advice = self._snapshot_recovery_advisor.refresh_and_evaluate(
                team_name,
                max_age_seconds=default_runtime_recovery_snapshot_max_age_seconds(),
                now=recovery_now,
            )
            if _should_skip_runtime_recovery_from_snapshot(advice):
                continue
            store = TeamStateStore(self._team_state_root, team_name, create=False)
            manifest = store.read_manifest()
            for runtime in store.list_worker_runtimes():
                if runtime.status not in _LIVE_RUNTIME_STATUSES:
                    continue
                recovered_runtime = self._recover_runtime(
                    store,
                    manifest,
                    runtime.worker,
                    team_name=team_name,
                )
                if recovered_runtime is not None:
                    recovered.append(recovered_runtime)
        return recovered

    async def execute(  # noqa: PLR0911
        self,
        operation: str,
        request: Mapping[str, object] | None,
    ) -> dict[str, Any]:
        if operation not in self.operations:
            return _error(operation, "unknown_operation", f"unsupported operation '{operation}'")
        try:
            request_data = self._require_request_object(request or {})
            team_name = self._require_team_name(request_data)
            worker = self._require_worker(request_data)
            async with self._lock_for(team_name, worker):
                if operation == _START_OPERATION:
                    return await self._start_worker_runtime(team_name, worker)
                if operation == _HEARTBEAT_OPERATION:
                    owner_session_id = self._require_session_id(request_data)
                    return await self._heartbeat_worker_runtime(team_name, worker, owner_session_id)
                return await self._stop_worker_runtime(team_name, worker)
        except FileNotFoundError as exc:
            return _error(operation, "not_found", str(exc))
        except ValueError as exc:
            return _error(operation, "invalid_request", str(exc))
        except RuntimeError as exc:
            return _error(operation, "internal_error", str(exc))
        except Exception as exc:  # pragma: no cover - defensive envelope
            return _error(operation, "internal_error", str(exc))

    def _lock_for(self, team_name: str, worker: str) -> asyncio.Lock:
        key = (team_name, worker)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _store(self, team_name: str) -> TeamStateStore:
        return TeamStateStore(self._team_state_root, team_name, create=False)

    def _team_names(self) -> list[str]:
        if not self._team_state_root.exists():
            return []
        return sorted(
            path.name
            for path in self._team_state_root.iterdir()
            if path.is_dir() and (path / "manifest.json").exists()
        )

    def _runtime(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
    ) -> TeamWorkerRuntimeState | None:
        try:
            return self._attachments.reconcile_runtime_owner(store, manifest, worker)
        except FileNotFoundError:
            return None

    def _ensure_runtime_record(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
    ) -> TeamWorkerRuntimeState:
        runtime = self._runtime(store, manifest, worker)
        if runtime is not None:
            return runtime
        return store.put_worker_runtime(TeamWorkerRuntimeState(worker=worker))

    def _recover_runtime(
        self,
        store: TeamStateStore,
        manifest: TeamManifest,
        worker: str,
        *,
        team_name: str,
    ) -> TeamWorkerRuntimeState | None:
        runtime = self._runtime(store, manifest, worker)
        if runtime is None or runtime.status not in _LIVE_RUNTIME_STATUSES:
            return None
        owner_session_id = runtime.attachment_session_id
        if owner_session_id is None:
            return None
        try:
            recovered = self._attachments.renew_runtime_heartbeat(
                store,
                manifest,
                worker,
                owner_session_id=owner_session_id,
            )
        except (FileNotFoundError, ValueError):
            return None
        self._ensure_keepalive_driver(team_name, worker)
        return recovered

    async def _start_worker_runtime(self, team_name: str, worker: str) -> dict[str, Any]:
        store = self._store(team_name)
        manifest = store.read_manifest()
        worker_model = manifest.get_worker(worker)
        runtime_ref = manifest.worker_runtime_ref(worker)
        if runtime_ref.session_name is None:
            msg = f"worker '{worker}' does not declare runtime.session_name"
            raise ValueError(msg)

        runtime = self._runtime(store, manifest, worker)
        if runtime is not None and runtime.status == "busy":
            msg = f"worker runtime '{worker}' is already busy with '{runtime.dispatch_request_id}'"
            raise ValueError(msg)

        attached = self._attachments.ensure_attached_runtime(store, manifest, worker)
        if attached is not None:
            self._ensure_keepalive_driver(team_name, worker)
            return _success(
                _START_OPERATION,
                {
                    "action": "reattached",
                    "runtime": attached.model_dump(mode="json"),
                },
            )

        session_ref = runtime_ref.routable_session or manifest.leader.session
        provider = worker_model.provider or self._orchestrator.config.provider
        model = (
            self._orchestrator.config.model
            if provider == self._orchestrator.config.provider
            else self._orchestrator.default_model_for_provider(provider)
        ) or self._orchestrator.config.model
        existing = self._orchestrator.named_sessions.get(session_ref.chat_id, runtime_ref.session_name)
        if existing is not None and existing.status != "ended":
            await self._orchestrator.end_named_session(session_ref.chat_id, runtime_ref.session_name)

        prompt = self._bootstrap_prompt(
            manifest,
            worker,
            runtime_context=worker_model.runtime,
        )
        self._orchestrator.named_sessions.create_explicit(
            session_ref.chat_id,
            runtime_ref.session_name,
            provider,
            model,
            prompt,
            transport=session_ref.transport,
        )

        response = await self._orchestrator.cli_service.execute(
            AgentRequest(
                prompt=prompt,
                model_override=model,
                provider_override=provider,
                chat_id=session_ref.chat_id,
                topic_id=session_ref.topic_id,
                process_label=f"ns:{runtime_ref.session_name}",
                timeout_seconds=self._resolve_timeout(),
            )
        )
        if response.is_error or not response.session_id:
            await self._orchestrator.end_named_session(session_ref.chat_id, runtime_ref.session_name)
            message = response.result or "worker runtime bootstrap failed"
            self._record_start_failure(store, worker, runtime, message)
            return _error(_START_OPERATION, "internal_error", message)

        self._orchestrator.named_sessions.update_after_response(
            session_ref.chat_id,
            runtime_ref.session_name,
            response.session_id,
        )
        attached = self._attachments.ensure_attached_runtime(store, manifest, worker)
        if attached is None:
            msg = f"worker runtime '{worker}' failed to resolve after bootstrap"
            self._record_start_failure(store, worker, runtime, msg)
            return _error(_START_OPERATION, "internal_error", msg)
        self._ensure_keepalive_driver(team_name, worker)
        return _success(
            _START_OPERATION,
            {
                "action": "started",
                "runtime": attached.model_dump(mode="json"),
            },
        )

    async def _stop_worker_runtime(self, team_name: str, worker: str) -> dict[str, Any]:
        store = self._store(team_name)
        manifest = store.read_manifest()
        runtime_ref = manifest.worker_runtime_ref(worker)
        if runtime_ref.session_name is None:
            msg = f"worker '{worker}' does not declare runtime.session_name"
            raise ValueError(msg)

        runtime = self._runtime(store, manifest, worker)
        if runtime is not None and runtime.status == "busy":
            msg = f"worker runtime '{worker}' is busy and cannot be stopped safely"
            raise ValueError(msg)

        runtime = self._ensure_runtime_record(store, manifest, worker)
        was_stopped = runtime.status == "stopped"
        session_ref = runtime_ref.routable_session or manifest.leader.session
        session = self._orchestrator.named_sessions.get(session_ref.chat_id, runtime_ref.session_name)
        if session is not None and session.status != "ended":
            await self._orchestrator.end_named_session(session_ref.chat_id, runtime_ref.session_name)

        if runtime.status != "stopped":
            runtime = store.transition_worker_runtime(worker, "stopped", now=_utc_now())
        await self._cancel_keepalive_driver(team_name, worker)

        return _success(
            _STOP_OPERATION,
            {
                "action": "already_stopped" if was_stopped and session is None else "stopped",
                "runtime": runtime.model_dump(mode="json"),
            },
        )

    async def _heartbeat_worker_runtime(
        self,
        team_name: str,
        worker: str,
        owner_session_id: str,
    ) -> dict[str, Any]:
        store = self._store(team_name)
        manifest = store.read_manifest()
        runtime = self._attachments.renew_runtime_heartbeat(
            store,
            manifest,
            worker,
            owner_session_id=owner_session_id,
        )
        return _success(
            _HEARTBEAT_OPERATION,
            {
                "action": "renewed",
                "runtime": runtime.model_dump(mode="json"),
            },
        )

    def _ensure_keepalive_driver(self, team_name: str, worker: str) -> None:
        if self._keepalive_interval_seconds is None:
            return
        key = (team_name, worker)
        task = self._keepalive_tasks.get(key)
        if task is not None and not task.done():
            return
        self._keepalive_tasks[key] = asyncio.create_task(
            self._run_keepalive_driver(team_name, worker),
            name=f"team-runtime-keepalive:{team_name}:{worker}",
        )

    async def _cancel_keepalive_driver(self, team_name: str, worker: str) -> None:
        key = (team_name, worker)
        task = self._keepalive_tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run_keepalive_driver(self, team_name: str, worker: str) -> None:
        key = (team_name, worker)
        try:
            while True:
                assert self._keepalive_interval_seconds is not None
                await asyncio.sleep(self._keepalive_interval_seconds)
                async with self._lock_for(team_name, worker):
                    store = self._store(team_name)
                    manifest = store.read_manifest()
                    runtime = self._runtime(store, manifest, worker)
                    if runtime is None or runtime.status not in _LIVE_RUNTIME_STATUSES:
                        return
                    owner_session_id = runtime.attachment_session_id
                    if owner_session_id is None:
                        return
                    await self._heartbeat_worker_runtime(team_name, worker, owner_session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        finally:
            task = self._keepalive_tasks.get(key)
            if task is asyncio.current_task():
                self._keepalive_tasks.pop(key, None)

    def _record_start_failure(
        self,
        store: TeamStateStore,
        worker: str,
        runtime: TeamWorkerRuntimeState | None,
        message: str,
    ) -> None:
        if runtime is None:
            store.put_worker_runtime(
                TeamWorkerRuntimeState(worker=worker, status="lost", health_reason=message)
            )
            return
        if runtime.status == "lost":
            store.put_worker_runtime(runtime.model_copy(update={"health_reason": message}))
            return
        if runtime.status == "created":
            store.put_worker_runtime(
                runtime.model_copy(update={"status": "lost", "health_reason": message})
            )
            return
        store.transition_worker_runtime(
            worker,
            "lost",
            updates={"health_reason": message},
            now=_utc_now(),
        )

    def _resolve_timeout(self) -> float | None:
        try:
            return resolve_timeout(self._orchestrator.config, "normal")
        except Exception:
            return None

    def _bootstrap_prompt(
        self,
        manifest: TeamManifest,
        worker: str,
        *,
        runtime_context: TeamRuntimeContext,
    ) -> str:
        lines = [
            f"You are the ControlMesh team worker '{worker}' for team '{manifest.team_name}'.",
            "This turn is only runtime bootstrap.",
            "Reply with a single short line confirming runtime readiness for future dispatches.",
        ]
        if runtime_context.cwd:
            lines.append(f"Repository root for future work: {runtime_context.cwd}")
        if runtime_context.session_name:
            lines.append(f"Named session identity: {runtime_context.session_name}")
        return "\n".join(lines)

    def _require_request_object(self, request: object) -> Mapping[str, object]:
        if not isinstance(request, Mapping):
            msg = "request must be an object"
            raise TypeError(msg)
        return request

    def _require_team_name(self, request: Mapping[str, object]) -> str:
        value = request.get("team_name")
        if not isinstance(value, str):
            msg = "team_name is required"
            raise TypeError(msg)
        return ensure_safe_identifier(TEAM_NAME_SAFE_PATTERN, value, "team_name")

    def _require_worker(self, request: Mapping[str, object]) -> str:
        value = request.get("worker")
        if not isinstance(value, str):
            msg = "worker is required"
            raise TypeError(msg)
        return ensure_safe_identifier(WORKER_NAME_SAFE_PATTERN, value, "worker")

    def _require_session_id(self, request: Mapping[str, object]) -> str:
        value = request.get("session_id")
        if not isinstance(value, str) or not value.strip():
            msg = "session_id is required"
            raise TypeError(msg)
        return value.strip()
