"""Weixin iLink transport scaffolding."""

from controlmesh.messenger.weixin.auth_state import WeixinAuthStateStore
from controlmesh.messenger.weixin.auth_store import StoredWeixinCredentials, WeixinCredentialStore
from controlmesh.messenger.weixin.inbound_spool import (
    WeixinInboundClaim,
    WeixinInboundSpool,
    WeixinInboundSpoolEntry,
    WeixinInboundSpoolStats,
)
from controlmesh.messenger.weixin.runtime import (
    WeixinContextTokenRequiredError,
    WeixinIncomingText,
    WeixinLongPollRuntime,
    WeixinPollResult,
    WeixinReauthRequiredError,
    WeixinUpdateBatch,
)
from controlmesh.messenger.weixin.runtime_state import WeixinRuntimeState, WeixinRuntimeStateStore

__all__ = [
    "StoredWeixinCredentials",
    "WeixinAuthStateStore",
    "WeixinContextTokenRequiredError",
    "WeixinCredentialStore",
    "WeixinInboundClaim",
    "WeixinInboundSpool",
    "WeixinInboundSpoolEntry",
    "WeixinInboundSpoolStats",
    "WeixinIncomingText",
    "WeixinLongPollRuntime",
    "WeixinPollResult",
    "WeixinReauthRequiredError",
    "WeixinRuntimeState",
    "WeixinRuntimeStateStore",
    "WeixinUpdateBatch",
]
