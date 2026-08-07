"""Tests for the bundled local read-only dashboard."""

from __future__ import annotations

from aiohttp import web

from controlmesh.api.server import ApiServer
from controlmesh.config import ApiConfig


def _make_app() -> web.Application:
    server = ApiServer(
        ApiConfig(host="127.0.0.1", port=0, token="test-token", allow_public=True)
    )
    app = web.Application()
    app.router.add_get("/dashboard", server._handle_dashboard_redirect)
    app.router.add_get("/dashboard/", server._handle_dashboard_index)
    app.router.add_get("/dashboard/assets/{name}", server._handle_dashboard_asset)
    return app


async def test_dashboard_redirects_to_slash_terminated_path(aiohttp_client) -> None:
    client = await aiohttp_client(_make_app())

    response = await client.get("/dashboard", allow_redirects=False)

    assert response.status == 308
    assert response.headers["Location"] == "/dashboard/"


async def test_dashboard_serves_packaged_index_and_assets(aiohttp_client) -> None:
    client = await aiohttp_client(_make_app())

    index_response = await client.get("/dashboard/")
    script_response = await client.get("/dashboard/assets/main.js")

    assert index_response.status == 200
    assert "<title>ControlMesh</title>" in await index_response.text()
    assert script_response.status == 200
    assert "/api/v1/tasks" in await script_response.text()


async def test_dashboard_rejects_non_allowlisted_assets(aiohttp_client) -> None:
    client = await aiohttp_client(_make_app())

    response = await client.get("/dashboard/assets/secret.txt")

    assert response.status == 404
