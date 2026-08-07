"""Deterministic Python oracle for the task-lifecycle parity matrix."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from controlmesh.api.admin_read import AdminHistoryCatalogReader
from controlmesh.api.artifact_access import (
    open_task_artifact,
    validate_artifact_relative_path,
)
from controlmesh.tasks.hub import TaskHub
from controlmesh.tasks.models import TaskInFlight, TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import ControlMeshPaths

SCHEMA_VERSION = "controlmesh.task_lifecycle_golden.v1"
REQUIRED_DOMAINS = (
    "create",
    "tell",
    "ask_parent",
    "resume",
    "cancel",
    "recovery",
    "workspace",
    "artifact",
)


def _submit() -> TaskSubmit:
    return TaskSubmit(
        chat_id=42,
        prompt="Review the repository.",
        message_id=7,
        thread_id=11,
        parent_agent="main",
        transport="web",
        name="Repository review",
    )


def _config() -> MagicMock:
    value = MagicMock()
    value.enabled = True
    value.max_parallel = 5
    value.timeout_seconds = 60.0
    return value


def _cli() -> MagicMock:
    value = MagicMock()
    value.resolve_provider.return_value = ("codex", "gpt-5")
    return value


def _case(
    case_id: str, domain: str, operation: str, expected: dict[str, object]
) -> dict[str, object]:
    return {"id": case_id, "domain": domain, "operation": operation, "expected": expected}


def _error(callable_) -> dict[str, str]:
    try:
        callable_()
    except Exception as exc:  # the exception type and public message are the contract
        return {"type": type(exc).__name__, "message": str(exc)}
    raise AssertionError("oracle operation unexpectedly succeeded")


async def build_matrix() -> dict[str, object]:
    """Execute production Python ownership paths and return normalized observations."""
    with tempfile.TemporaryDirectory(prefix="controlmesh-golden-") as raw_root:
        root = Path(raw_root)
        paths = ControlMeshPaths(controlmesh_home=root / "home", framework_root=root / "repo")
        registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
        with patch("controlmesh.tasks.registry.secrets.token_hex", return_value="a1b2c3d4"):
            created = registry.create(_submit(), "codex", "gpt-5", thinking="high")
        folder = registry.task_folder(created.task_id)
        events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
        cases: list[dict[str, object]] = [
            _case(
                "create.basic",
                "create",
                "TaskRegistry.create",
                {
                    "task": {
                        "task_id": created.task_id,
                        "status": created.status,
                        "provider": created.provider,
                        "model": created.model,
                        "thinking": created.thinking,
                        "transport": created.transport,
                        "chat_id": created.chat_id,
                        "thread_id": created.thread_id,
                    },
                    "seeded_files": sorted(path.name for path in folder.iterdir()),
                    "event_types": [event["event_type"] for event in events],
                },
            ),
        ]

        hub = TaskHub(registry, paths, cli_service=_cli(), config=_config())

        async def wait_forever() -> None:
            await asyncio.Future()

        inflight_task = asyncio.create_task(wait_forever())
        hub._in_flight[created.task_id] = TaskInFlight(entry=created, asyncio_task=inflight_task)
        with patch("controlmesh.tasks.hub.datetime") as clock:
            clock.now.return_value.isoformat.return_value = "<timestamp>"
            clock.side_effect = None
            sequence = hub.tell(created.task_id, "Use the canonical schema", parent_agent="main")
        updates = hub.pull_updates(created.task_id, mark_read=False)
        cases.append(
            _case(
                "tell.running",
                "tell",
                "TaskHub.tell",
                {
                    "sequence": sequence,
                    "updates": updates,
                },
            )
        )
        inflight_task.cancel()
        await asyncio.gather(inflight_task, return_exceptions=True)
        cases.append(
            _case(
                "tell.not_running",
                "tell",
                "TaskHub.tell",
                {
                    "error": _error(lambda: hub.tell(created.task_id, "too late")),
                },
            )
        )

        question_handler = AsyncMock()
        hub.set_question_handler("main", question_handler)
        response = await hub.forward_question(created.task_id, "Which contract?")
        await asyncio.sleep(0)
        questioned = registry.get(created.task_id)
        assert questioned is not None
        cases.append(
            _case(
                "ask_parent.basic",
                "ask_parent",
                "TaskHub.forward_question",
                {
                    "response": response,
                    "question_count": questioned.question_count,
                    "last_question": questioned.last_question,
                    "delivery_count": question_handler.await_count,
                },
            )
        )
        missing = await hub.forward_question("missing-task", "Anyone there?")
        cases.append(
            _case(
                "ask_parent.missing",
                "ask_parent",
                "TaskHub.forward_question",
                {"response": missing},
            )
        )

        registry.update_status(
            created.task_id, "waiting", session_id="session-1", error="old", result_preview="old"
        )
        hub._spawn = MagicMock()  # type: ignore[method-assign]
        resumed = hub.resume(created.task_id, "Use JSON Schema")
        resumed_entry = registry.get(created.task_id)
        assert resumed_entry is not None
        cases.append(
            _case(
                "resume.waiting",
                "resume",
                "TaskHub.resume",
                {
                    "returned_task_id": resumed,
                    "same_task_id": resumed == created.task_id,
                    "status": resumed_entry.status,
                    "provider": resumed_entry.provider,
                    "model": resumed_entry.model,
                    "session_id": resumed_entry.session_id,
                    "last_question": resumed_entry.last_question,
                    "error": resumed_entry.error,
                },
            )
        )
        registry.update_status(created.task_id, "waiting", session_id="")
        cases.append(
            _case(
                "resume.no_session",
                "resume",
                "TaskHub.resume",
                {
                    "error": _error(lambda: hub.resume(created.task_id, "continue")),
                },
            )
        )

        cases.append(
            _case(
                "cancel.missing",
                "cancel",
                "TaskHub.cancel",
                {"cancelled": await hub.cancel("missing-task")},
            )
        )
        registry.update_status(created.task_id, "running", session_id="session-1")
        cancel_task = asyncio.create_task(wait_forever())
        hub._in_flight[created.task_id] = TaskInFlight(entry=created, asyncio_task=cancel_task)
        cases.append(
            _case(
                "cancel.running",
                "cancel",
                "TaskHub.cancel",
                {"cancelled": await hub.cancel(created.task_id)},
            )
        )

        registry.update_status(created.task_id, "running")
        reloaded = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
        recovered = reloaded.get(created.task_id)
        assert recovered is not None
        cases.append(
            _case(
                "recovery.restart_stale",
                "recovery",
                "TaskRegistry.__init__",
                {
                    "status": recovered.status,
                    "error": recovered.error,
                    "task_id_preserved": recovered.task_id == created.task_id,
                },
            )
        )

        custom_dir = root / "agents" / "reviewer" / "workspace" / "tasks"
        with patch("controlmesh.tasks.registry.secrets.token_hex", return_value="b2c3d4e5"):
            custom = reloaded.create(_submit(), "codex", "gpt-5", tasks_dir=custom_dir)
        cases.append(
            _case(
                "workspace.custom_tasks_dir",
                "workspace",
                "TaskRegistry.create",
                {
                    "tasks_dir": "<root>/agents/reviewer/workspace/tasks",
                    "task_folder": "<root>/agents/reviewer/workspace/tasks/b2c3d4e5",
                    "default_folder_used": (paths.tasks_dir / custom.task_id).exists(),
                },
            )
        )

        artifact = reloaded.task_folder(custom.task_id) / "reports" / "summary.txt"
        artifact.parent.mkdir()
        artifact.write_text("safe content", encoding="utf-8")
        reader = AdminHistoryCatalogReader(paths)
        with open_task_artifact(reader, custom.task_id, "reports/summary.txt") as opened:
            cases.append(
                _case(
                    "artifact.read",
                    "artifact",
                    "open_task_artifact",
                    {
                        "relative_path": opened.relative_path,
                        "name": opened.name,
                        "mime": opened.mime,
                        "size": opened.size,
                        "content": opened.stream.read().decode(),
                    },
                )
            )
        cases.append(
            _case(
                "artifact.traversal",
                "artifact",
                "validate_artifact_relative_path",
                {
                    "error": _error(lambda: validate_artifact_relative_path("../secret.txt")),
                },
            )
        )
        cases.append(
            _case(
                "artifact.missing_task",
                "artifact",
                "open_task_artifact",
                {
                    "error": _error(
                        lambda: open_task_artifact(reader, "missing-task", "RESULT.md")
                    ),
                },
            )
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "oracle": "python",
            "normalizers": ["task_ids", "timestamps", "temporary_roots", "process_ids"],
            "required_domains": list(REQUIRED_DOMAINS),
            "cases": cases,
        }


def generate_matrix() -> dict[str, object]:
    return asyncio.run(build_matrix())
