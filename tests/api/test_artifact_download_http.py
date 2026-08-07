"""HTTP security cases for the artifact handler before production route exposure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web

from controlmesh.api.admin_read import AdminHistoryCatalogReader
from controlmesh.api.v1_facade import V1FacadeHttpHandlers
from controlmesh.tasks.models import TaskSubmit
from controlmesh.tasks.registry import TaskRegistry
from controlmesh.workspace.paths import ControlMeshPaths

HTTP_SECURITY_CASE_TESTS = {
    "AD-AUTH-001": "test_download_rejects_missing_token",
    "AD-AUTH-002": "test_download_rejects_wrong_token",
    "AD-AUTH-003": "test_download_accepts_correct_token",
    "AD-AUTH-004": "test_download_auth_precedes_invalid_path_resolution",
    "AD-PATH-006": "test_download_never_discloses_absolute_paths",
    "AD-MIME-002": "test_download_sets_safe_response_headers",
}


@pytest.fixture
async def download_facade(tmp_path: Path, aiohttp_client):
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )
    registry = TaskRegistry(paths.tasks_registry_path, paths.tasks_dir)
    entry = registry.create(
        TaskSubmit(
            chat_id=1,
            prompt="download handler test",
            message_id=1,
            thread_id=None,
            parent_agent="main",
            name="Download Handler",
        ),
        "codex",
        "gpt-5.2",
    )
    task_folder = registry.task_folder(entry.task_id)
    handlers = V1FacadeHttpHandlers(token="test-token")
    handlers.set_reader(AdminHistoryCatalogReader(paths))
    app = web.Application()
    app.router.add_get(
        "/api/v1/tasks/{task_id}/artifacts/content",
        handlers.handle_task_artifact_content,
        allow_head=False,
    )
    client = await aiohttp_client(app)
    return client, entry.task_id, task_folder


def test_http_security_case_links_resolve_to_tests() -> None:
    assert all(callable(globals().get(test_name)) for test_name in HTTP_SECURITY_CASE_TESTS.values())


async def test_download_rejects_missing_token(download_facade) -> None:
    client, task_id, _task_folder = download_facade

    response = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": "RESULT.md"},
    )

    assert response.status == 401
    assert (await response.json())["code"] == "PERMISSION_DENIED"


async def test_download_rejects_wrong_token(download_facade) -> None:
    client, task_id, _task_folder = download_facade

    response = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": "RESULT.md"},
        headers={"Authorization": "Bearer wrong"},
    )

    assert response.status == 401
    assert (await response.json())["code"] == "PERMISSION_DENIED"


async def test_download_accepts_correct_token(download_facade) -> None:
    client, task_id, task_folder = download_facade
    (task_folder / "download.txt").write_text("download body", encoding="utf-8")

    response = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": "download.txt"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status == 200
    assert await response.read() == b"download body"


async def test_download_auth_precedes_invalid_path_resolution(download_facade, tmp_path: Path) -> None:
    client, task_id, _task_folder = download_facade
    secret_path = str(tmp_path / "outside-secret.txt")

    response = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": secret_path},
    )

    assert response.status == 401
    body = await response.json()
    assert body["code"] == "PERMISSION_DENIED"
    assert str(tmp_path) not in json.dumps(body)


async def test_download_never_discloses_absolute_paths(download_facade, tmp_path: Path) -> None:
    client, task_id, task_folder = download_facade
    artifact = task_folder / "nested" / "report.txt"
    artifact.parent.mkdir()
    artifact.write_text("report", encoding="utf-8")
    headers = {"Authorization": "Bearer test-token"}

    success = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": "nested/report.txt"},
        headers=headers,
    )
    invalid = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": str(tmp_path / "outside.txt")},
        headers=headers,
    )

    assert success.status == 200
    assert str(tmp_path) not in json.dumps(dict(success.headers))
    assert invalid.status == 400
    assert str(tmp_path) not in json.dumps(await invalid.json())


async def test_download_sets_safe_response_headers(download_facade) -> None:
    client, task_id, task_folder = download_facade
    artifact = task_folder / 'resume "final".txt'
    artifact.write_text("header-safe", encoding="utf-8")

    response = await client.get(
        f"/api/v1/tasks/{task_id}/artifacts/content",
        params={"relative_path": artifact.name},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Type"].startswith("text/plain")
    disposition = response.headers["Content-Disposition"]
    assert disposition == "attachment; filename*=UTF-8''resume%20%22final%22.txt"
    assert "\r" not in disposition
    assert "\n" not in disposition
