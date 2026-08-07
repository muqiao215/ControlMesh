"""Tests for the read-only admin catalog HTTP surface."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from aiohttp import web

from controlmesh.api.admin_read import (
    DEFAULT_CATALOG_LIMIT,
    MAX_CATALOG_LIMIT,
    AdminHistoryCatalogReader,
    parse_catalog_limit,
)
from controlmesh.api.catalog_http import CatalogHttpHandlers
from controlmesh.api.v1_facade import V1FacadeHttpHandlers
from controlmesh.history import TranscriptStore, TranscriptTurn
from controlmesh.runtime import RuntimeEvent, RuntimeEventStore
from controlmesh.session import SessionKey
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.team.models import (
    TeamLeader,
    TeamManifest,
    TeamPhaseState,
    TeamSessionRef,
    TeamTask,
    TeamWorker,
)
from controlmesh.team.state import TeamStateStore
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def _seed_catalog_sources(paths: ControlMeshPaths) -> TaskRegistry:
    transcript_store = TranscriptStore(paths)
    runtime_store = RuntimeEventStore(paths)

    session_a = SessionKey.telegram(101)
    session_b = SessionKey.telegram(202, 7)

    transcript_store.append_turn(
        TranscriptTurn(
            turn_id="turn-a1",
            session_key=session_a.storage_key,
            surface_session_id=session_a.storage_key,
            role="user",
            visible_content="alpha transcript",
            source="normal_chat",
            created_at="2026-04-11T10:00:00+00:00",
            transport=session_a.transport,
            chat_id=session_a.chat_id,
            topic_id=session_a.topic_id,
        )
    )
    transcript_store.append_turn(
        TranscriptTurn(
            turn_id="turn-b1",
            session_key=session_b.storage_key,
            surface_session_id=session_b.storage_key,
            role="assistant",
            visible_content="beta transcript",
            source="normal_chat",
            created_at="2026-04-11T11:00:00+00:00",
            transport=session_b.transport,
            chat_id=session_b.chat_id,
            topic_id=session_b.topic_id,
        )
    )

    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    first = registry.create(
        TaskSubmit(
            chat_id=11,
            prompt="first task prompt",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="First Task",
        ),
        "codex",
        "gpt-5.2",
    )
    second = registry.create(
        TaskSubmit(
            chat_id=22,
            prompt="second task prompt",
            message_id=2,
            thread_id=9,
            parent_agent="main",
            name="Second Task",
        ),
        "claude",
        "opus",
    )
    registry.update_status(
        second.task_id,
        "done",
        session_id="ia-main",
        result_preview="done preview",
        last_question="where next?",
    )
    first_folder = registry.task_folder(first.task_id)
    (first_folder / "RESULT.md").write_text("# Result\n\nDone.", encoding="utf-8")
    (first_folder / "generated").mkdir(parents=True, exist_ok=True)
    (first_folder / "generated" / "EVIDENCE.json").write_text(
        json.dumps({"task_id": first.task_id, "status": "done"}),
        encoding="utf-8",
    )
    runtime_store.append_event(
        RuntimeEvent(
            event_id="runtime-a1",
            session_key=session_a.storage_key,
            event_type="task.lifecycle.started",
            payload={"worker": "alpha", "task_id": first.task_id, "status": "running"},
            created_at="2026-04-11T10:05:00+00:00",
            transport=session_a.transport,
            chat_id=session_a.chat_id,
            topic_id=session_a.topic_id,
        )
    )
    runtime_store.append_event(
        RuntimeEvent(
            event_id="runtime-b1",
            session_key=session_b.storage_key,
            event_type="worker.finished",
            payload={"worker": "beta"},
            created_at="2026-04-11T11:05:00+00:00",
            transport=session_b.transport,
            chat_id=session_b.chat_id,
            topic_id=session_b.topic_id,
        )
    )

    for team_name, owner, updated_at in (
        ("alpha-team", "worker-1", "2026-04-11T09:00:00+00:00"),
        ("beta-team", "worker-2", "2026-04-11T12:00:00+00:00"),
    ):
        store = TeamStateStore(paths.team_state_dir, team_name)
        store.write_manifest(
            TeamManifest(
                team_name=team_name,
                task_description=f"{team_name} manifest",
                leader=TeamLeader(
                    agent_name="main",
                    session=TeamSessionRef(transport="tg", chat_id=77),
                ),
                workers=[TeamWorker(name=owner, role="executor", provider="codex")],
            )
        )
        store.upsert_task(
            TeamTask(
                task_id=f"{team_name}-task",
                subject=f"{team_name} task",
                owner=owner,
                updated_at=updated_at,
            )
        )
        store.write_phase(TeamPhaseState(current_phase="execute"))

    return registry


def _make_app(tmp_path: Path) -> web.Application:
    paths = _paths(tmp_path)
    _seed_catalog_sources(paths)

    handlers = CatalogHttpHandlers(token="test-token")
    handlers.set_reader(AdminHistoryCatalogReader(paths))

    app = web.Application()
    app.router.add_get("/catalog/sessions", handlers.handle_sessions)
    app.router.add_get("/catalog/tasks", handlers.handle_tasks)
    app.router.add_get("/catalog/teams", handlers.handle_teams)
    return app


def _make_v1_app(tmp_path: Path) -> web.Application:
    paths = _paths(tmp_path)
    _seed_catalog_sources(paths)

    return _make_v1_handlers_app(paths)


def _make_v1_handlers_app(paths: ControlMeshPaths) -> web.Application:
    handlers = V1FacadeHttpHandlers(
        token="test-token",
        provider_info_getter=lambda: [
            {
                "name": "codex",
                "available": True,
                "version": "1.2.3",
                "capabilities": {"supports_streaming": True},
            },
            {
                "name": "gemini",
                "available": False,
                "status": "not configured",
            },
        ],
    )
    handlers.set_reader(AdminHistoryCatalogReader(paths))

    app = web.Application()
    app.router.add_get("/api/v1/tasks", handlers.handle_tasks)
    app.router.add_get("/api/v1/tasks/{task_id}/events", handlers.handle_task_events)
    app.router.add_get("/api/v1/tasks/{task_id}/artifacts", handlers.handle_task_artifacts)
    app.router.add_get("/api/v1/tasks/{task_id}", handlers.handle_task)
    app.router.add_get("/api/v1/providers", handlers.handle_providers)
    app.router.add_get("/api/v1/topologies", handlers.handle_topologies)
    return app


@pytest.fixture
async def api_client(tmp_path: Path, aiohttp_client):
    return await aiohttp_client(_make_app(tmp_path))


@pytest.fixture
async def v1_client(tmp_path: Path, aiohttp_client):
    return await aiohttp_client(_make_v1_app(tmp_path))


@pytest.fixture
async def custom_artifact_facade(tmp_path: Path, aiohttp_client):
    paths = _paths(tmp_path)
    registry = _seed_catalog_sources(paths)
    custom_tasks_dir = tmp_path / "agents" / "reviewer" / "tasks"
    entry = registry.create(
        TaskSubmit(
            chat_id=33,
            prompt="custom artifact task",
            message_id=3,
            thread_id=None,
            parent_agent="reviewer",
            name="Custom Artifact Task",
        ),
        "codex",
        "gpt-5.2",
        tasks_dir=custom_tasks_dir,
    )
    task_folder = registry.task_folder(entry.task_id)
    client = await aiohttp_client(_make_v1_handlers_app(paths))
    return client, paths, entry.task_id, task_folder


class TestAdminHistoryCatalogReader:
    def test_empty_sources_return_empty_catalogs(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        reader = AdminHistoryCatalogReader(paths)

        assert reader.sessions()["total"] == 0
        assert reader.sessions()["items"] == []
        assert reader.tasks()["total"] == 0
        assert reader.tasks()["items"] == []
        assert reader.teams()["total"] == 0
        assert reader.teams()["items"] == []

    def test_sessions_returns_distinct_transcript_and_runtime_counts(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _seed_catalog_sources(paths)

        body = AdminHistoryCatalogReader(paths).sessions(limit=1)

        assert body["limit"] == 1
        assert body["total"] == 2
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["transcript"]["count"] == 1
        assert item["runtime"]["count"] == 1
        assert item["last_seen"] == item["runtime"]["last_seen"]

    def test_tasks_and_teams_return_separate_derived_shapes(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        _seed_catalog_sources(paths)
        reader = AdminHistoryCatalogReader(paths)

        task_body = reader.tasks(limit=2)
        team_body = reader.teams(limit=2)

        assert task_body["total"] == 2
        assert task_body["items"][0]["source_kind"] == "task_registry"
        assert "runtime" not in task_body["items"][0]
        assert team_body["total"] == 2
        assert team_body["items"][0]["source_kind"] == "team_state"
        assert team_body["items"][0]["entity_counts"]["manifest"] == 1
        assert team_body["items"][0]["entity_counts"]["phase"] == 1
        assert team_body["items"][0]["entity_counts"]["task"] == 1

    @pytest.mark.parametrize(
        ("raw_limit", "expected"),
        [
            (None, DEFAULT_CATALOG_LIMIT),
            ("", DEFAULT_CATALOG_LIMIT),
            ("1", 1),
            ("999", MAX_CATALOG_LIMIT),
        ],
    )
    def test_parse_catalog_limit_bounds_values(
        self,
        raw_limit: str | None,
        expected: int,
    ) -> None:
        assert parse_catalog_limit(raw_limit) == expected

    @pytest.mark.parametrize("raw_limit", ["-1", "abc"])
    def test_parse_catalog_limit_rejects_invalid_values(self, raw_limit: str) -> None:
        with pytest.raises(ValueError, match="invalid catalog limit"):
            parse_catalog_limit(raw_limit)


class TestAdminCatalogAuth:
    async def test_catalog_sessions_requires_bearer_token(self, api_client) -> None:
        resp = await api_client.get("/catalog/sessions")
        assert resp.status == 401
        assert await resp.json() == {"error": "unauthorized"}

    async def test_catalog_sessions_rejects_wrong_bearer_token(self, api_client) -> None:
        resp = await api_client.get(
            "/catalog/sessions",
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status == 401
        assert await resp.json() == {"error": "unauthorized"}


class TestAdminCatalogEndpoints:
    async def test_catalog_endpoints_return_503_without_configured_reader(self, aiohttp_client) -> None:
        handlers = CatalogHttpHandlers(token="test-token")
        app = web.Application()
        app.router.add_get("/catalog/sessions", handlers.handle_sessions)
        client = await aiohttp_client(app)

        resp = await client.get(
            "/catalog/sessions",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 503
        assert await resp.json() == {"error": "catalog reader not configured"}

    async def test_catalog_sessions_returns_bounded_distinct_transcript_and_runtime_counts(
        self, api_client
    ) -> None:
        resp = await api_client.get(
            "/catalog/sessions",
            params={"limit": "1"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["limit"] == 1
        assert body["total"] == 2
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert set(item) >= {
            "session_key",
            "transport",
            "chat_id",
            "topic_id",
            "transcript",
            "runtime",
            "last_seen",
        }
        assert item["transcript"]["count"] == 1
        assert item["runtime"]["count"] == 1
        assert item["transcript"]["last_seen"] != ""
        assert item["runtime"]["last_seen"] != ""
        assert item["last_seen"] == item["runtime"]["last_seen"]

    async def test_catalog_tasks_returns_task_catalog_rows(self, api_client) -> None:
        resp = await api_client.get(
            "/catalog/tasks",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        item = body["items"][0]
        assert set(item) >= {
            "task_id",
            "status",
            "session_id",
            "source_kind",
            "chat_id",
            "name",
            "provider",
            "model",
            "result_preview",
            "last_question",
        }
        assert item["source_kind"] == "task_registry"
        assert "transcript" not in item
        assert "runtime" not in item

    async def test_catalog_teams_returns_separate_team_entity_counts(self, api_client) -> None:
        resp = await api_client.get(
            "/catalog/teams",
            params={"limit": "1"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["limit"] == 1
        assert body["total"] == 2
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert set(item) >= {
            "team_name",
            "entity_counts",
            "status_counts",
            "owner_ids",
            "worker_ids",
            "last_seen",
        }
        assert item["entity_counts"]["manifest"] == 1
        assert item["entity_counts"]["phase"] == 1
        assert item["entity_counts"]["task"] == 1
        assert item["status_counts"]["pending"] == 1

    async def test_catalog_endpoints_reject_invalid_limit(self, api_client) -> None:
        resp = await api_client.get(
            "/catalog/teams",
            params={"limit": "-1"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 400
        assert await resp.json() == {"error": "invalid 'limit' query parameter"}

    async def test_catalog_sessions_supports_practical_concurrent_reads(self, api_client) -> None:
        async def fetch() -> tuple[int, dict[str, object]]:
            resp = await api_client.get(
                "/catalog/sessions",
                headers={"Authorization": "Bearer test-token"},
            )
            return resp.status, await resp.json()

        results = await asyncio.gather(*(fetch() for _ in range(8)))

        for status, body in results:
            assert status == 200
            assert body["total"] == 2
            assert len(body["items"]) == 2


class TestV1ReadOnlyFacade:
    async def test_v1_tasks_requires_bearer_token(self, v1_client) -> None:
        resp = await v1_client.get("/api/v1/tasks")

        assert resp.status == 401
        body = await resp.json()
        assert body["schema_version"] == "controlmesh.error.v1"
        assert body["code"] == "PERMISSION_DENIED"

    async def test_v1_tasks_returns_protocol_task_rows(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["total"] == 2
        assert body["limit"] == DEFAULT_CATALOG_LIMIT
        item = body["items"][0]
        assert item["schema_version"] == "controlmesh.task.v1"
        assert item["source_kind"] == "task_registry"
        assert item["status"] in {"running", "done"}
        assert "task_id" in item
        assert "parent_agent" in item
        assert "created_at" in item

    async def test_v1_task_returns_one_protocol_task(self, v1_client) -> None:
        list_resp = await v1_client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer test-token"},
        )
        task_id = (await list_resp.json())["items"][0]["task_id"]

        resp = await v1_client.get(
            f"/api/v1/tasks/{task_id}",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["schema_version"] == "controlmesh.task.v1"
        assert body["task_id"] == task_id

    async def test_v1_task_returns_protocol_404(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/tasks/missing-task",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 404
        body = await resp.json()
        assert body["schema_version"] == "controlmesh.error.v1"
        assert body["code"] == "TASK_NOT_FOUND"

    async def test_v1_task_events_returns_protocol_task_events(self, v1_client) -> None:
        list_resp = await v1_client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer test-token"},
        )
        tasks = (await list_resp.json())["items"]
        task_id = next(task["task_id"] for task in tasks if task["status"] == "running")

        resp = await v1_client.get(
            f"/api/v1/tasks/{task_id}/events",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert len(body) == 1
        assert body[0]["schema_version"] == "controlmesh.task_event.v1"
        assert body[0]["task_id"] == task_id
        assert body[0]["event_type"] == "task.lifecycle.started"
        assert body[0]["status"] == "running"

    async def test_v1_task_events_returns_protocol_404(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/tasks/missing-task/events",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 404
        body = await resp.json()
        assert body["schema_version"] == "controlmesh.error.v1"
        assert body["code"] == "TASK_NOT_FOUND"

    async def test_v1_task_artifacts_returns_python_resolved_metadata(
        self,
        v1_client,
        tmp_path: Path,
    ) -> None:
        list_resp = await v1_client.get(
            "/api/v1/tasks",
            headers={"Authorization": "Bearer test-token"},
        )
        tasks = (await list_resp.json())["items"]
        task_id = next(task["task_id"] for task in tasks if task["status"] == "running")

        resp = await v1_client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        paths = {item["relative_path"] for item in body}
        assert "RESULT.md" in paths
        assert "generated/EVIDENCE.json" in paths
        result = next(item for item in body if item["relative_path"] == "RESULT.md")
        assert result["schema_version"] == "controlmesh.artifact.v1"
        assert result["task_id"] == task_id
        assert result["name"] == "RESULT.md"
        assert result["size"] > 0
        assert not result["relative_path"].startswith("/")
        assert str(tmp_path) not in json.dumps(body)

    async def test_v1_task_artifacts_use_custom_tasks_dir_and_omit_symlink_escape(
        self,
        custom_artifact_facade,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, _paths, task_id, task_folder = custom_artifact_facade
        artifact = task_folder / "reports" / "summary.txt"
        artifact.parent.mkdir()
        artifact.write_text("safe artifact", encoding="utf-8")
        outside = tmp_path / "outside-secret.txt"
        outside.write_text("must not leak", encoding="utf-8")
        (task_folder / "escaped-secret.txt").symlink_to(outside)

        def fail_registry_init(*_args, **_kwargs) -> None:
            raise AssertionError("read-only facade instantiated TaskRegistry")

        monkeypatch.setattr(TaskRegistry, "__init__", fail_registry_init)
        resp = await client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        relative_paths = {item["relative_path"] for item in body}
        assert "reports/summary.txt" in relative_paths
        assert "escaped-secret.txt" not in relative_paths
        assert "outside-secret.txt" not in relative_paths
        assert all(not Path(item["relative_path"]).is_absolute() for item in body)
        assert str(tmp_path) not in json.dumps(body)

    async def test_v1_task_artifacts_return_empty_for_empty_or_missing_folder(
        self,
        custom_artifact_facade,
    ) -> None:
        client, _paths, task_id, task_folder = custom_artifact_facade
        shutil.rmtree(task_folder)
        task_folder.mkdir(parents=True)

        empty_resp = await client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert empty_resp.status == 200
        assert await empty_resp.json() == []

        task_folder.rmdir()
        missing_resp = await client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert missing_resp.status == 200
        assert await missing_resp.json() == []

    async def test_v1_task_artifacts_omit_unreadable_file(
        self,
        custom_artifact_facade,
    ) -> None:
        client, _paths, task_id, task_folder = custom_artifact_facade
        readable = task_folder / "readable.txt"
        readable.write_text("public metadata", encoding="utf-8")
        unreadable = task_folder / "unreadable.bin"
        unreadable.write_bytes(b"private metadata")
        unreadable.chmod(0)
        try:
            resp = await client.get(
                f"/api/v1/tasks/{task_id}/artifacts",
                headers={"Authorization": "Bearer test-token"},
            )
        finally:
            unreadable.chmod(0o600)

        assert resp.status == 200
        relative_paths = {item["relative_path"] for item in await resp.json()}
        assert "readable.txt" in relative_paths
        assert "unreadable.bin" not in relative_paths

    async def test_v1_task_artifacts_omit_file_missing_during_metadata_read(
        self,
        custom_artifact_facade,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, _paths, task_id, task_folder = custom_artifact_facade
        vanishing = task_folder / "vanishing.txt"
        vanishing.write_text("short lived", encoding="utf-8")

        from controlmesh.api import protocol_adapters

        real_guess_mime = protocol_adapters.guess_mime

        def remove_before_mime(path: Path) -> str:
            if path == vanishing:
                path.unlink()
                raise FileNotFoundError(path)
            return real_guess_mime(path)

        monkeypatch.setattr(protocol_adapters, "guess_mime", remove_before_mime)
        resp = await client.get(
            f"/api/v1/tasks/{task_id}/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        relative_paths = {item["relative_path"] for item in await resp.json()}
        assert "vanishing.txt" not in relative_paths

    async def test_v1_task_artifacts_returns_protocol_404(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/tasks/missing-task/artifacts",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 404
        body = await resp.json()
        assert body["schema_version"] == "controlmesh.error.v1"
        assert body["code"] == "TASK_NOT_FOUND"

    async def test_v1_providers_returns_protocol_capabilities(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/providers",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["total"] == 2
        first = body["items"][0]
        assert first["schema_version"] == "controlmesh.provider_capability.v1"
        assert first["name"] == "codex"
        assert first["health"] == "ok"
        assert first["capabilities"]["supports_streaming"] is True

    async def test_v1_topologies_project_team_ownership_in_python(self, v1_client) -> None:
        resp = await v1_client.get(
            "/api/v1/topologies",
            headers={"Authorization": "Bearer test-token"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["total"] == 2
        topology = next(item for item in body["items"] if item["topology_id"] == "alpha-team")
        assert topology["schema_version"] == "controlmesh.topology.v1"
        nodes = {node["id"]: node for node in topology["nodes"]}
        assert nodes["agent:main"]["role"] == "leader"
        assert nodes["agent:worker-1"]["role"] == "executor"
        assert nodes["task:alpha-team-task"]["owner"] == "worker-1"
        assert {
            (edge["source"], edge["target"], edge["kind"])
            for edge in topology["edges"]
        } >= {
            ("agent:main", "agent:worker-1", "supervises"),
            ("agent:worker-1", "task:alpha-team-task", "owns"),
        }
