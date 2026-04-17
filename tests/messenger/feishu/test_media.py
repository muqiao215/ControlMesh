"""Tests for Feishu media parsing and inbound download helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

from controlmesh.config import AgentConfig
from controlmesh.messenger.feishu.media import ResolveMediaRequest


def _feishu_config(tmp_path: Path):
    return AgentConfig(
        transport="feishu",
        transports=["feishu"],
        controlmesh_home=str(tmp_path),
        feishu={
            "mode": "bot_only",
            "brand": "feishu",
            "app_id": "cli_123",
            "app_secret": "sec_456",
        },
    ).feishu


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def read(self) -> bytes:
        return self._body

    async def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


@pytest.mark.parametrize(
    ("message_type", "raw_content", "expected_text", "expected_kind"),
    [
        ("image", '{"image_key":"img_123"}', "![image](img_123)", "image"),
        (
            "file",
            '{"file_key":"file_123","file_name":"report.pdf"}',
            '<file key="file_123" name="report.pdf"/>',
            "file",
        ),
        ("audio", '{"file_key":"file_123","duration":3000}', '<audio key="file_123"', "audio"),
        (
            "media",
            '{"file_key":"file_123","file_name":"clip.mp4","duration":5000}',
            '<video key="file_123" name="clip.mp4"',
            "video",
        ),
        (
            "video",
            '{"file_key":"file_123","file_name":"clip.mp4","duration":5000}',
            '<video key="file_123" name="clip.mp4"',
            "video",
        ),
    ],
)
def test_parse_message_content_extracts_resource_descriptors(
    message_type: str,
    raw_content: str,
    expected_text: str,
    expected_kind: str,
) -> None:
    from controlmesh.messenger.feishu.media import parse_message_content

    parsed = parse_message_content(message_type, raw_content)

    assert expected_text in parsed.text
    assert len(parsed.resources) == 1
    assert parsed.resources[0].kind == expected_kind


@pytest.mark.asyncio
async def test_resolve_media_text_downloads_resource_and_builds_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from controlmesh.messenger.feishu.media import resolve_media_text

    workspace = tmp_path / "workspace"
    files_dir = workspace / "feishu_files"
    session = _FakeSession(
        _FakeResponse(
            body=b"fake-image-bytes",
            headers={
                "Content-Type": "image/png",
                "Content-Disposition": 'attachment; filename="diagram.png"',
            },
        )
    )
    monkeypatch.setattr(
        "controlmesh.messenger.feishu.media.process_image",
        lambda path: path,
    )

    prompt = await resolve_media_text(
        ResolveMediaRequest(
            session=session,
            config=_feishu_config(tmp_path),
            message_id="om_123",
            message_type="image",
            raw_content='{"image_key":"img_123"}',
            files_dir=files_dir,
            workspace=workspace,
            tenant_access_token="tenant-token",
        )
    )

    assert prompt is not None
    assert "via Feishu" in prompt
    assert "Type: image/png" in prompt
    assert "Path: feishu_files/" in prompt
    saved_files = list(files_dir.rglob("diagram.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"fake-image-bytes"
    assert session.calls[0]["url"] == (
        "https://open.feishu.cn/open-apis/im/v1/messages/om_123/resources/img_123"
    )
    assert session.calls[0]["params"] == {"type": "image"}
    assert session.calls[0]["headers"] == {"Authorization": "Bearer tenant-token"}
