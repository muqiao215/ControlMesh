"""Start an installed ControlMesh wheel against disposable read-only alpha state."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from controlmesh.api.admin_read import AdminHistoryCatalogReader
from controlmesh.api.server import ApiServer
from controlmesh.config import ApiConfig
from controlmesh.runtime import RuntimeEvent, RuntimeEventStore
from controlmesh.session import SessionKey
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import ControlMeshPaths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    return parser.parse_args()


def _seed_state(paths: ControlMeshPaths) -> tuple[str, str]:
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    entry = registry.create(
        TaskSubmit(
            chat_id=42,
            prompt="inspect the read-only alpha",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Read-only Alpha Smoke",
        ),
        "codex",
        "gpt-5.6",
    )
    task_folder = registry.task_folder(entry.task_id)
    artifact = task_folder / "reports" / "alpha.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("read-only alpha artifact\n", encoding="utf-8")

    outside = paths.controlmesh_home.parent / "private.txt"
    outside.write_text("must not leak\n", encoding="utf-8")
    (task_folder / "private-link.txt").symlink_to(outside)

    session = SessionKey.telegram(42)
    RuntimeEventStore(paths).append_event(
        RuntimeEvent(
            event_id="alpha-smoke-started",
            session_key=session.storage_key,
            event_type="task.lifecycle.started",
            payload={"task_id": entry.task_id, "status": "running"},
            created_at="2026-08-08T00:00:00+00:00",
            transport=session.transport,
            chat_id=session.chat_id,
            topic_id=session.topic_id,
        )
    )
    return entry.task_id, artifact.relative_to(task_folder).as_posix()


async def _run(args: argparse.Namespace) -> None:
    state_dir = args.state_dir.resolve()
    paths = ControlMeshPaths(controlmesh_home=state_dir / ".controlmesh")
    task_id, artifact_path = _seed_state(paths)
    token = "alpha-smoke-token"
    server = ApiServer(
        ApiConfig(
            enabled=True,
            host="127.0.0.1",
            port=0,
            token=token,
            allow_public=True,
        ),
        read_only=True,
    )
    server.set_admin_catalog_reader(AdminHistoryCatalogReader(paths))
    server.set_provider_info(
        [
            {
                "name": "codex",
                "available": True,
                "version": "smoke",
                "capabilities": {"supports_streaming": True},
            }
        ]
    )
    await server.start()

    ready = {
        "base_url": f"http://127.0.0.1:{server.bound_port}",
        "token": token,
        "task_id": task_id,
        "artifact_path": artifact_path,
    }
    args.ready_file.write_text(json.dumps(ready), encoding="utf-8")

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for watched_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(watched_signal, stopped.set)
    try:
        await stopped.wait()
    finally:
        await server.stop()


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
