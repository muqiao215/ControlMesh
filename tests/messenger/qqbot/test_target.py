"""Tests for QQ Bot target parsing and normalization."""

from __future__ import annotations

import pytest

from controlmesh.messenger.qqbot.target import (
    looks_like_qqbot_target,
    normalize_target,
    parse_target,
)


def test_parse_c2c_target() -> None:
    parsed = parse_target("qqbot:c2c:OPENID")
    assert parsed.type == "c2c"
    assert parsed.id == "OPENID"


def test_parse_group_target_without_prefix() -> None:
    parsed = parse_target("group:GROUP_OPENID")
    assert parsed.type == "group"
    assert parsed.id == "GROUP_OPENID"


def test_parse_dm_target() -> None:
    parsed = parse_target("qqbot:dm:GUILD_DM_A")
    assert parsed.type == "dm"
    assert parsed.id == "GUILD_DM_A"


def test_parse_bare_target_defaults_to_c2c() -> None:
    parsed = parse_target("0123456789abcdef0123456789abcdef")
    assert parsed.type == "c2c"
    assert parsed.id == "0123456789abcdef0123456789abcdef"


def test_normalize_bare_openid() -> None:
    normalized = normalize_target("0123456789abcdef0123456789abcdef")
    assert normalized == "qqbot:c2c:0123456789abcdef0123456789abcdef"


def test_looks_like_qqbot_target() -> None:
    assert looks_like_qqbot_target("qqbot:group:GROUP_OPENID") is True
    assert looks_like_qqbot_target("qqbot:dm:GUILD_DM_A") is True
    assert looks_like_qqbot_target("group:GROUP_OPENID") is True
    assert looks_like_qqbot_target("not-a-target") is False


def test_parse_invalid_group_target() -> None:
    with pytest.raises(ValueError, match="missing group ID"):
        parse_target("qqbot:group:")
