from __future__ import annotations

import pytest

from controlmesh.messenger.weixin.api import WeixinIlinkApiError, _parse_json_response


class _FakeResponse:
    def __init__(self, *, status: int, body: str, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def text(self) -> str:
        return self._body


async def test_parse_json_response_surfaces_html_context_for_invalid_json() -> None:
    response = _FakeResponse(
        status=502,
        body="<html><body>proxy timeout</body></html>",
        headers={"Content-Type": "text/html; charset=utf-8"},
    )

    with pytest.raises(WeixinIlinkApiError) as excinfo:
        await _parse_json_response(response, "/ilink/bot/get_bot_qrcode?bot_type=3")

    exc = excinfo.value
    assert exc.status == 502
    assert exc.endpoint == "/ilink/bot/get_bot_qrcode?bot_type=3"
    assert exc.content_type == "text/html; charset=utf-8"
    assert exc.body_snippet == "<html><body>proxy timeout</body></html>"
    assert "returned invalid JSON" in str(exc)
    assert "HTTP 502" in str(exc)
    assert "content-type=text/html; charset=utf-8" in str(exc)
    assert "proxy timeout" in str(exc)


async def test_parse_json_response_rejects_non_object_json_payloads() -> None:
    response = _FakeResponse(
        status=200,
        body='["not", "an", "object"]',
        headers={"Content-Type": "application/json"},
    )

    with pytest.raises(WeixinIlinkApiError) as excinfo:
        await _parse_json_response(response, "/ilink/bot/get_qrcode_status?qrcode=test")

    exc = excinfo.value
    assert exc.status == 200
    assert exc.endpoint == "/ilink/bot/get_qrcode_status?qrcode=test"
    assert exc.content_type == "application/json"
    assert exc.body_snippet == '["not", "an", "object"]'
    assert "returned malformed JSON payload (list)" in str(exc)
