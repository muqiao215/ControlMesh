"""Brand-aware Feishu/Lark domain helpers for auth flows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeAlias
from urllib.parse import urlencode, urlsplit

FeishuBrand: TypeAlias = str


def open_platform_domain(brand: FeishuBrand = "feishu") -> str:
    """Return the Open Platform base URL for the configured brand."""
    if not brand or brand == "feishu":
        return "https://open.feishu.cn"
    if brand == "lark":
        return "https://open.larksuite.com"
    return brand.rstrip("/")


def build_permission_url(
    *,
    app_id: str,
    scopes: Iterable[str],
    brand: FeishuBrand = "feishu",
    token_type: str = "user",
    op_from: str = "controlmesh-feishu",
) -> str:
    """Build a shortcut auth URL with the missing scopes preselected."""
    query = {
        "q": ",".join(scope.strip() for scope in scopes if scope.strip()),
        "op_from": op_from,
        "token_type": token_type,
    }
    return f"{open_platform_domain(brand)}/app/{app_id}/auth?{urlencode(query)}"


def accounts_domain(brand: FeishuBrand = "feishu") -> str:
    """Return the account base URL used by OAuth device authorization."""
    if not brand or brand == "feishu":
        return "https://accounts.feishu.cn"
    if brand == "lark":
        return "https://accounts.larksuite.com"

    base = open_platform_domain(brand)
    parsed = urlsplit(base)
    host = parsed.netloc
    if host.startswith("open."):
        host = host.replace("open.", "accounts.", 1)
    return f"{parsed.scheme}://{host}".rstrip("/")


def applink_domain(brand: FeishuBrand = "feishu") -> str:
    if not brand or brand == "feishu":
        return "https://applink.feishu.cn"
    if brand == "lark":
        return "https://applink.larksuite.com"

    base = open_platform_domain(brand)
    parsed = urlsplit(base)
    host = parsed.netloc
    if host.startswith("open."):
        host = host.replace("open.", "applink.", 1)
    return f"{parsed.scheme}://{host}".rstrip("/")


def www_domain(brand: FeishuBrand = "feishu") -> str:
    if not brand or brand == "feishu":
        return "https://www.feishu.cn"
    if brand == "lark":
        return "https://www.larksuite.com"

    base = open_platform_domain(brand)
    parsed = urlsplit(base)
    host = parsed.netloc
    if host.startswith("open."):
        host = host.replace("open.", "www.", 1)
    return f"{parsed.scheme}://{host}".rstrip("/")


@dataclass(frozen=True, slots=True)
class OAuthEndpoints:
    device_authorization: str
    token: str


def resolve_oauth_endpoints(brand: FeishuBrand = "feishu") -> OAuthEndpoints:
    """Resolve OAuth endpoints from the chosen Feishu brand or custom base."""
    return OAuthEndpoints(
        device_authorization=f"{accounts_domain(brand)}/oauth/v1/device_authorization",
        token=f"{open_platform_domain(brand)}/open-apis/authen/v2/oauth/token",
    )
