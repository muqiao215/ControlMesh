"""Tests for Feishu device-flow card payload builders."""

from __future__ import annotations

from controlmesh.messenger.feishu.auth.auth_cards import build_auth_card


def test_build_auth_card_uses_complete_verification_url_for_all_multi_url_targets() -> None:
    card = build_auth_card(
        verification_uri_complete="https://verify.test/device?code=abc",
        expires_in=600,
        scope="offline_access im:message",
        user_code="USER-123",
    )

    button = card["elements"][1]["actions"][0]
    multi_url = button["multi_url"]
    content = card["elements"][0]["content"]

    assert multi_url["url"] == "https://verify.test/device?code=abc"
    assert multi_url["pc_url"] == "https://verify.test/device?code=abc"
    assert multi_url["android_url"] == "https://verify.test/device?code=abc"
    assert multi_url["ios_url"] == "https://verify.test/device?code=abc"
    assert "offline_access im:message" in content
    assert "10 minutes" in content
    assert "USER-123" in content
