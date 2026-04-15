"""Tests for the read-only admin catalog HTTP surface."""

from __future__ import annotations

import asyncio
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


def _seed_catalog_sources(paths: ControlMeshPaths) -> None:
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

    runtime_store.append_event(
        RuntimeEvent(
            event_id="runtime-a1",
            session_key=session_a.storage_key,
            event_type="worker.started",
            payload={"worker": "alpha"},
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

    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    registry.create(
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


@pytest.fixture
async def api_client(tmp_path: Path, aiohttp_client):
    return await aiohttp_client(_make_app(tmp_path))


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
