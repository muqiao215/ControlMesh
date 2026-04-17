"""Feishu-native tool auth contracts and inbound context."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Literal

from controlmesh.config import AgentConfig

if TYPE_CHECKING:
    from controlmesh.messenger.feishu.auth.runtime_continuation import (
        FeishuAuthContinuationEntry,
    )
    from controlmesh.messenger.feishu.bot import FeishuIncomingText

FeishuToolAuthErrorKind = Literal[
    "app_scope_missing",
    "user_auth_required",
    "user_scope_insufficient",
]
FeishuScopeNeedType = Literal["one", "all"]
FeishuTokenType = Literal["tenant", "user"]

_SUPPORTED_ERROR_KINDS = {
    "app_scope_missing",
    "user_auth_required",
    "user_scope_insufficient",
}


@dataclass(frozen=True, slots=True)
class FeishuInboundContextV1:
    """Stable Feishu message context passed to native tool/auth seams."""

    app_id: str
    brand: str
    runtime_mode: str
    sender_open_id: str
    chat_id: str
    message_id: str
    thread_id: str | None = None
    schema: str = "controlmesh.feishu.inbound_context.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FeishuNativeToolAuthContract:
    """Structured auth failure contract emitted by Feishu-native tools."""

    error_kind: FeishuToolAuthErrorKind
    required_scopes: tuple[str, ...]
    retry_text: str = ""
    permission_url: str = ""
    user_open_id: str = ""
    operation_id: str = ""
    flow_key: str = ""
    token_type: FeishuTokenType = "user"  # noqa: S105 - Feishu token class label.
    scope_need_type: FeishuScopeNeedType = "all"
    source: str = "controlmesh-feishu-native-tool"
    schema: str = "controlmesh.feishu.tool_auth.v1"

    def __post_init__(self) -> None:
        if self.error_kind not in _SUPPORTED_ERROR_KINDS:
            msg = f"Unsupported Feishu tool auth error kind: {self.error_kind}"
            raise ValueError(msg)
        scopes = tuple(str(scope).strip() for scope in self.required_scopes if str(scope).strip())
        if not scopes:
            msg = "Feishu tool auth contract requires at least one required scope"
            raise ValueError(msg)
        object.__setattr__(self, "required_scopes", scopes)

    def with_runtime_defaults(
        self,
        *,
        context: FeishuInboundContextV1,
        original_text: str,
    ) -> FeishuNativeToolAuthContract:
        return FeishuNativeToolAuthContract(
            error_kind=self.error_kind,
            required_scopes=self.required_scopes,
            retry_text=self.retry_text or original_text,
            permission_url=self.permission_url,
            user_open_id=self.user_open_id or context.sender_open_id,
            operation_id=self.operation_id,
            flow_key=self.flow_key,
            token_type=self.token_type,
            scope_need_type=self.scope_need_type,
            source=self.source,
        )


class FeishuNativeToolAuthRequiredError(RuntimeError):
    """Raised by Feishu-native tools when chat UX should handle auth."""

    def __init__(self, contract: FeishuNativeToolAuthContract) -> None:
        super().__init__(contract.error_kind)
        self.contract = contract


def build_feishu_inbound_context(
    config: AgentConfig,
    message: FeishuIncomingText,
) -> FeishuInboundContextV1:
    return FeishuInboundContextV1(
        app_id=config.feishu.app_id,
        brand=config.feishu.brand,
        runtime_mode=config.feishu.runtime_mode,
        sender_open_id=message.sender_id,
        chat_id=message.chat_id,
        message_id=message.message_id,
        thread_id=message.thread_id,
    )


def build_native_synthetic_retry_artifact(
    entry: FeishuAuthContinuationEntry,
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema": "controlmesh.feishu.synthetic-retry.v1",
        "kind": "synthetic_retry",
        "operation_id": entry.operation_id,
        "text": entry.retry_text,
        "reason": reason,
        "metadata": {
            "chat_id": entry.chat_id,
            "sender_open_id": entry.sender_open_id,
            "thread_id": entry.thread_id,
            "trigger_message_id": entry.trigger_message_id,
        },
    }


def new_feishu_operation_id() -> str:
    return uuid.uuid4().hex
