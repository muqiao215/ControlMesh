"""Tests for multiagent/internal_api.py: InternalAgentAPI HTTP endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient

from controlmesh.multiagent.bus import InterAgentBus
from controlmesh.multiagent.health import AgentHealth
from controlmesh.multiagent.internal_api import InternalAgentAPI
from controlmesh.team.models import (
    TeamDispatchRequest,
    TeamLeader,
    TeamManifest,
    TeamPhaseState,
    TeamRuntimeContext,
    TeamSessionRef,
    TeamTask,
    TeamTaskClaim,
    TeamWorker,
)
from controlmesh.team.state import TeamStateStore


def _seed_team_store(state_root: Path) -> TeamStateStore:
    store = TeamStateStore(state_root, "alpha-team")
    store.write_manifest(
        TeamManifest(
            team_name="alpha-team",
            task_description="Coordinate Cut 3-5",
            leader=TeamLeader(
                agent_name="main",
                session=TeamSessionRef(transport="tg", chat_id=7),
                runtime=TeamRuntimeContext(cwd="/repo"),
            ),
            workers=[
                TeamWorker(
                    name="worker-1",
                    role="executor",
                    provider="codex",
                    runtime=TeamRuntimeContext(
                        provider_session_id="codex-sess-1",
                        session_name="ia-worker-1",
                        routable_session=TeamSessionRef(transport="tg", chat_id=9, topic_id=3),
                    ),
                )
            ],
        )
    )
    store.write_phase(TeamPhaseState(current_phase="execute", active=True))
    store.upsert_task(
        TeamTask(
            task_id="task-1",
            subject="Implement state store",
            status="in_progress",
            owner="worker-1",
            claim=TeamTaskClaim(
                worker="worker-1",
                token="lease-1",
                claimed_at=datetime.now(UTC).isoformat(),
                lease_expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            ),
        )
    )
    store.create_dispatch_request(
        TeamDispatchRequest(
            request_id="dispatch-1",
            team_name="alpha-team",
            task_id="task-1",
            to_worker="worker-1",
            kind="task",
            status="pending",
        )
    )
    store.transition_dispatch_request(
        "dispatch-1",
        "notified",
        metadata={"live_route": "worker_session", "live_target_session": "tg:9:3"},
    )
    store.transition_dispatch_request(
        "dispatch-1",
        "delivered",
        metadata={"live_route": "worker_session", "live_target_session": "tg:9:3"},
    )
    return store


@pytest.fixture
def bus() -> InterAgentBus:
    return InterAgentBus()


@pytest.fixture
def api(bus: InterAgentBus, tmp_path: Path) -> InternalAgentAPI:
    return InternalAgentAPI(bus, port=0, team_state_root=tmp_path / "team-state")


@pytest.fixture
async def client(api: InternalAgentAPI) -> AsyncGenerator[TestClient[Any, Any], None]:
    """Create aiohttp test client for the internal API."""
    from aiohttp.test_utils import TestServer

    server = TestServer(api._app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


class TestHandleSend:
    """Test POST /interagent/send."""

    async def test_send_success(self, client: TestClient[Any, Any], bus: InterAgentBus) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert data["text"] == "OK"

    async def test_send_missing_fields(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/interagent/send",
            json={"from": "sender"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["success"] is False
        assert "Missing" in data["error"]

    async def test_send_invalid_json(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/interagent/send",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

    async def test_send_unknown_recipient(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "nonexistent", "message": "Hello"},
        )
        data = await resp.json()
        assert data["success"] is False
        assert "not found" in data["error"]


class TestHandleSendAsync:
    """Test POST /interagent/send_async."""

    async def test_send_async_success(
        self, client: TestClient[Any, Any], bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True
        assert "task_id" in data

    async def test_send_async_unknown_recipient(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender", "to": "nonexistent", "message": "Hello"},
        )
        data = await resp.json()
        assert data["success"] is False
        assert "not found" in data["error"]

    async def test_send_async_missing_fields(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/interagent/send_async",
            json={"from": "sender"},
        )
        assert resp.status == 400


class TestNewSessionFlag:
    """Test new_session flag in /interagent/send and /interagent/send_async."""

    async def test_send_passes_new_session_true(
        self, client: TestClient[Any, Any], bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={
                "from": "sender",
                "to": "target",
                "message": "Hello",
                "new_session": True,
            },
        )
        assert resp.status == 200
        stack.bot.orchestrator.handle_interagent_message.assert_awaited_once_with(
            "sender",
            "Hello",
            new_session=True,
        )

    async def test_send_defaults_new_session_false(
        self, client: TestClient[Any, Any], bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send",
            json={"from": "sender", "to": "target", "message": "Hello"},
        )
        assert resp.status == 200
        stack.bot.orchestrator.handle_interagent_message.assert_awaited_once_with(
            "sender",
            "Hello",
            new_session=False,
        )

    async def test_send_async_passes_new_session(
        self, client: TestClient[Any, Any], bus: InterAgentBus
    ) -> None:
        stack = MagicMock()
        stack.bot.orchestrator = MagicMock()
        stack.bot.orchestrator.handle_interagent_message = AsyncMock(
            return_value=("OK", "ia-sender", "")
        )
        bus.register("target", stack)

        resp = await client.post(
            "/interagent/send_async",
            json={
                "from": "sender",
                "to": "target",
                "message": "Hello",
                "new_session": True,
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True


class TestHandleList:
    """Test GET /interagent/agents."""

    async def test_list_empty(self, client: TestClient[Any, Any]) -> None:
        resp = await client.get("/interagent/agents")
        assert resp.status == 200
        data = await resp.json()
        assert data["agents"] == []

    async def test_list_with_agents(
        self, client: TestClient[Any, Any], bus: InterAgentBus
    ) -> None:
        bus.register("main", MagicMock())
        bus.register("sub1", MagicMock())

        resp = await client.get("/interagent/agents")
        data = await resp.json()
        assert set(data["agents"]) == {"main", "sub1"}


class TestHandleHealth:
    """Test GET /interagent/health."""

    async def test_health_no_ref(self, client: TestClient[Any, Any]) -> None:
        resp = await client.get("/interagent/health")
        data = await resp.json()
        assert data["agents"] == {}

    async def test_health_with_agents(
        self, client: TestClient[Any, Any], api: InternalAgentAPI
    ) -> None:
        h = AgentHealth(name="main")
        h.mark_running()
        api.set_health_ref({"main": h})

        resp = await client.get("/interagent/health")
        data = await resp.json()
        assert "main" in data["agents"]
        assert data["agents"]["main"]["status"] == "running"
        assert data["agents"]["main"]["restart_count"] == 0

    async def test_health_crashed_agent(
        self, client: TestClient[Any, Any], api: InternalAgentAPI
    ) -> None:
        h = AgentHealth(name="sub1")
        h.mark_crashed("OOM")
        api.set_health_ref({"sub1": h})

        resp = await client.get("/interagent/health")
        data = await resp.json()
        assert data["agents"]["sub1"]["status"] == "crashed"
        assert data["agents"]["sub1"]["last_crash_error"] == "OOM"
        assert data["agents"]["sub1"]["restart_count"] == 1


class TestLifecycle:
    """Test InternalAgentAPI lifecycle return values."""

    async def test_start_returns_false_on_bind_error(self, api: InternalAgentAPI) -> None:
        from unittest.mock import patch

        with patch(
            "aiohttp.web.TCPSite.start",
            new_callable=AsyncMock,
            side_effect=OSError("bind failed"),
        ):
            started = await api.start()

        assert started is False


class TestTeamOperate:
    async def test_read_manifest(self, client: TestClient[Any, Any], tmp_path: Path) -> None:
        _seed_team_store(tmp_path / "team-state")

        resp = await client.post(
            "/teams/operate",
            json={"operation": "read-manifest", "request": {"team_name": "alpha-team"}},
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["operation"] == "read-manifest"
        assert data["data"]["manifest"]["team_name"] == "alpha-team"

    async def test_record_dispatch_result(
        self, client: TestClient[Any, Any], tmp_path: Path
    ) -> None:
        store = _seed_team_store(tmp_path / "team-state")

        resp = await client.post(
            "/teams/operate",
            json={
                "operation": "record-dispatch-result",
                "request": {
                    "team_name": "alpha-team",
                    "request_id": "dispatch-1",
                    "result": {
                        "outcome": "completed",
                        "summary": "Done",
                        "reported_by": "worker-1",
                        "task_status": "completed",
                    },
                },
            },
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert data["data"]["dispatch_request"]["result"]["outcome"] == "completed"
        assert store.get_task("task-1").status == "completed"

    async def test_missing_operation_field(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post("/teams/operate", json={"request": {"team_name": "alpha-team"}})

        assert resp.status == 400
        data = await resp.json()
        assert data["success"] is False

    async def test_invalid_json(self, client: TestClient[Any, Any]) -> None:
        resp = await client.post(
            "/teams/operate",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )

        assert resp.status == 400

    async def test_start_worker_runtime_routes_to_runtime_controller(
        self, client: TestClient[Any, Any], api: InternalAgentAPI
    ) -> None:
        controller: Any = SimpleNamespace(
            operations=frozenset({"start-worker-runtime", "heartbeat-worker-runtime"}),
            execute=AsyncMock(
                return_value={
                    "schema_version": 1,
                    "ok": True,
                    "operation": "start-worker-runtime",
                    "data": {"runtime": {"worker": "worker-1", "status": "ready"}},
                }
            )
        )
        api.set_team_runtime_controller(controller)

        resp = await client.post(
            "/teams/operate",
            json={
                "operation": "start-worker-runtime",
                "request": {"team_name": "alpha-team", "worker": "worker-1"},
            },
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        controller.execute.assert_awaited_once_with(
            "start-worker-runtime",
            {"team_name": "alpha-team", "worker": "worker-1"},
        )

    async def test_heartbeat_worker_runtime_routes_to_runtime_controller(
        self, client: TestClient[Any, Any], api: InternalAgentAPI
    ) -> None:
        controller: Any = SimpleNamespace(
            operations=frozenset({"heartbeat-worker-runtime"}),
            execute=AsyncMock(
                return_value={
                    "schema_version": 1,
                    "ok": True,
                    "operation": "heartbeat-worker-runtime",
                    "data": {"runtime": {"worker": "worker-1", "status": "busy"}},
                }
            ),
        )
        api.set_team_runtime_controller(controller)

        resp = await client.post(
            "/teams/operate",
            json={
                "operation": "heartbeat-worker-runtime",
                "request": {
                    "team_name": "alpha-team",
                    "worker": "worker-1",
                    "session_id": "sess-worker-1",
                },
            },
        )

        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        controller.execute.assert_awaited_once_with(
            "heartbeat-worker-runtime",
            {
                "team_name": "alpha-team",
                "worker": "worker-1",
                "session_id": "sess-worker-1",
            },
        )

    async def test_start_worker_runtime_requires_runtime_controller(
        self, client: TestClient[Any, Any]
    ) -> None:
        resp = await client.post(
            "/teams/operate",
            json={
                "operation": "start-worker-runtime",
                "request": {"team_name": "alpha-team", "worker": "worker-1"},
            },
        )

        assert resp.status == 503
        data = await resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "operation_not_allowed"

    async def test_heartbeat_worker_runtime_requires_runtime_controller(
        self, client: TestClient[Any, Any]
    ) -> None:
        resp = await client.post(
            "/teams/operate",
            json={
                "operation": "heartbeat-worker-runtime",
                "request": {
                    "team_name": "alpha-team",
                    "worker": "worker-1",
                    "session_id": "sess-worker-1",
                },
            },
        )

        assert resp.status == 503
        data = await resp.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "operation_not_allowed"
