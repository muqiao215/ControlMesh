from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class DomainSet:
    open_base: str
    accounts_base: str
    applink_base: str
    www_base: str
    mcp_base: str

    @property
    def tenant_token_url(self) -> str:
        return f"{self.open_base}/open-apis/auth/v3/tenant_access_token/internal"

    @property
    def app_info_base(self) -> str:
        return f"{self.open_base}/open-apis/application/v6/applications"

    @property
    def device_authorization_url(self) -> str:
        return f"{self.accounts_base}/oauth/v1/device_authorization"

    @property
    def oauth_token_url(self) -> str:
        return f"{self.open_base}/open-apis/authen/v2/oauth/token"


def _normalize_base(value: str) -> str:
    return value.rstrip("/")


def resolve_domains(brand: str = "feishu") -> DomainSet:
    normalized = (brand or "feishu").strip().lower()
    if normalized == "feishu":
        return DomainSet(
            open_base="https://open.feishu.cn",
            accounts_base="https://accounts.feishu.cn",
            applink_base="https://applink.feishu.cn",
            www_base="https://www.feishu.cn",
            mcp_base="https://mcp.feishu.cn",
        )
    if normalized == "lark":
        return DomainSet(
            open_base="https://open.larksuite.com",
            accounts_base="https://accounts.larksuite.com",
            applink_base="https://applink.larksuite.com",
            www_base="https://www.larksuite.com",
            mcp_base="https://mcp.larksuite.com",
        )

    open_base = _normalize_base(brand)
    parsed = urlparse(open_base)
    if parsed.scheme and parsed.netloc and parsed.hostname and parsed.hostname.startswith("open."):
        accounts_base = f"{parsed.scheme}://{parsed.netloc.replace('open.', 'accounts.', 1)}"
    else:
        accounts_base = open_base
    return DomainSet(
        open_base=open_base,
        accounts_base=accounts_base,
        applink_base=open_base,
        www_base=open_base,
        mcp_base=open_base,
    )


def open_platform_domain(brand: str = "feishu") -> str:
    return resolve_domains(brand).open_base


def applink_domain(brand: str = "feishu") -> str:
    return resolve_domains(brand).applink_base


def www_domain(brand: str = "feishu") -> str:
    return resolve_domains(brand).www_base


def mcp_domain(brand: str = "feishu") -> str:
    return resolve_domains(brand).mcp_base
