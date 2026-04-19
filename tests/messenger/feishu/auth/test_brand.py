"""Tests for Feishu auth brand/domain helpers."""

from __future__ import annotations

from controlmesh.messenger.feishu.auth.brand import (
    accounts_domain,
    applink_domain,
    build_permission_url,
    open_platform_domain,
    resolve_oauth_endpoints,
    www_domain,
)


def test_default_feishu_domains() -> None:
    assert open_platform_domain() == "https://open.feishu.cn"
    assert accounts_domain() == "https://accounts.feishu.cn"
    assert applink_domain() == "https://applink.feishu.cn"
    assert www_domain() == "https://www.feishu.cn"


def test_lark_domains() -> None:
    assert open_platform_domain("lark") == "https://open.larksuite.com"
    assert accounts_domain("lark") == "https://accounts.larksuite.com"
    assert applink_domain("lark") == "https://applink.larksuite.com"
    assert www_domain("lark") == "https://www.larksuite.com"


def test_custom_open_platform_brand_derives_accounts_domain() -> None:
    endpoints = resolve_oauth_endpoints("https://open.example.test")

    assert endpoints.device_authorization == "https://accounts.example.test/oauth/v1/device_authorization"
    assert endpoints.token == "https://open.example.test/open-apis/authen/v2/oauth/token"


def test_build_permission_url_uses_scope_shortcut_route() -> None:
    assert build_permission_url(
        app_id="cli_123",
        scopes=["contact:user:search", "im:message:readonly"],
        brand="feishu",
        token_type="user",
        op_from="controlmesh-feishu-auth-all",
    ) == (
        "https://open.feishu.cn/app/cli_123/auth?"
        "q=contact%3Auser%3Asearch%2Cim%3Amessage%3Areadonly&"
        "op_from=controlmesh-feishu-auth-all&token_type=user"
    )
