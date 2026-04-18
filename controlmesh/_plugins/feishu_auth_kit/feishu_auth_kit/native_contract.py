from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .orchestration import (
    AuthContinuation,
    build_synthetic_retry_artifact,
    load_auth_continuation,
)
from .runtime_cards import ContinuationState, FileContinuationStore

NATIVE_CONTINUATION_KIND = "native_agent_continuation"


@dataclass(frozen=True)
class NativeCardAction:
    operation_id: str
    action: str
    actor_open_id: str | None = None
    message_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.native-card-action.v1",
            "operation_id": self.operation_id,
            "action": self.action,
            "actor_open_id": self.actor_open_id,
            "message_id": self.message_id,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class NativeContinuationRecord:
    operation_id: str
    app_id: str
    continuation_kind: str
    retry_text: str
    flow_key: str | None = None
    user_open_id: str | None = None
    required_scopes: list[str] = field(default_factory=list)
    status: str = "waiting"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_auth_continuation(
        cls,
        continuation: AuthContinuation,
        *,
        retry_text: str,
        status: str = "waiting",
        metadata: dict[str, Any] | None = None,
    ) -> NativeContinuationRecord:
        return cls(
            operation_id=continuation.operation_id,
            app_id=continuation.app_id,
            continuation_kind=continuation.decision,
            retry_text=retry_text,
            flow_key=continuation.flow_key,
            user_open_id=continuation.user_open_id,
            required_scopes=list(continuation.required_scopes),
            status=status,
            metadata={**continuation.metadata, **(metadata or {})},
        )

    def to_state(self) -> ContinuationState:
        payload = {
            "flow_key": self.flow_key,
            "user_open_id": self.user_open_id,
            "required_scopes": self.required_scopes,
            "retry_text": self.retry_text,
            "continuation_kind": self.continuation_kind,
            "metadata": self.metadata,
        }
        return ContinuationState(
            operation_id=self.operation_id,
            app_id=self.app_id,
            kind=NATIVE_CONTINUATION_KIND,
            status=self.status,
            payload=payload,
        )

    @classmethod
    def from_state(cls, state: ContinuationState) -> NativeContinuationRecord:
        payload = state.payload
        return cls(
            operation_id=state.operation_id,
            app_id=state.app_id,
            continuation_kind=str(payload["continuation_kind"]),
            retry_text=str(payload["retry_text"]),
            flow_key=payload.get("flow_key"),
            user_open_id=payload.get("user_open_id"),
            required_scopes=list(payload.get("required_scopes") or []),
            status=state.status,
            metadata=payload.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.native-continuation.v1",
            "operation_id": self.operation_id,
            "app_id": self.app_id,
            "continuation_kind": self.continuation_kind,
            "retry_text": self.retry_text,
            "flow_key": self.flow_key,
            "user_open_id": self.user_open_id,
            "required_scopes": self.required_scopes,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class NativeRetryRequest:
    operation_id: str
    app_id: str
    continuation_kind: str
    action: str
    text: str
    actor_open_id: str | None = None
    user_open_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.native-retry-request.v1",
            "operation_id": self.operation_id,
            "app_id": self.app_id,
            "continuation_kind": self.continuation_kind,
            "action": self.action,
            "text": self.text,
            "actor_open_id": self.actor_open_id,
            "user_open_id": self.user_open_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ResolvedNativeAction:
    action: NativeCardAction
    continuation: NativeContinuationRecord
    retry_request: NativeRetryRequest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.native-action-resolution.v1",
            "action": self.action.to_dict(),
            "continuation": self.continuation.to_dict(),
            "retry_request": self.retry_request.to_dict(),
        }


def save_native_continuation(
    store: FileContinuationStore,
    continuation: NativeContinuationRecord,
) -> ContinuationState:
    state = continuation.to_state()
    store.save(state)
    return state


def load_native_continuation(
    store: FileContinuationStore,
    operation_id: str,
) -> NativeContinuationRecord | None:
    state = store.load(operation_id)
    if state is None or state.kind != NATIVE_CONTINUATION_KIND:
        return None
    return NativeContinuationRecord.from_state(state)


def bind_auth_continuation_to_native(
    store: FileContinuationStore,
    *,
    operation_id: str,
    retry_text: str,
    metadata: dict[str, Any] | None = None,
) -> NativeContinuationRecord:
    current = load_native_continuation(store, operation_id)
    if current is not None:
        updated = NativeContinuationRecord(
            operation_id=current.operation_id,
            app_id=current.app_id,
            continuation_kind=current.continuation_kind,
            retry_text=retry_text,
            flow_key=current.flow_key,
            user_open_id=current.user_open_id,
            required_scopes=current.required_scopes,
            status=current.status,
            metadata={**current.metadata, **(metadata or {})},
        )
        save_native_continuation(store, updated)
        return updated

    continuation = load_auth_continuation(store, operation_id)
    if continuation is None:
        raise KeyError(f"unknown continuation operation_id: {operation_id}")
    native = NativeContinuationRecord.from_auth_continuation(
        continuation,
        retry_text=retry_text,
        metadata=metadata,
    )
    save_native_continuation(store, native)
    return native


def resolve_card_action_to_retry(
    action: NativeCardAction,
    store: FileContinuationStore,
) -> ResolvedNativeAction:
    continuation = load_native_continuation(store, action.operation_id)
    if continuation is None:
        raise KeyError(f"unknown native continuation operation_id: {action.operation_id}")
    confirmed = NativeContinuationRecord(
        operation_id=continuation.operation_id,
        app_id=continuation.app_id,
        continuation_kind=continuation.continuation_kind,
        retry_text=continuation.retry_text,
        flow_key=continuation.flow_key,
        user_open_id=continuation.user_open_id,
        required_scopes=continuation.required_scopes,
        status="confirmed",
        metadata={
            **continuation.metadata,
            "last_action": action.action,
            "actor_open_id": action.actor_open_id,
            "action_payload": action.payload,
            "message_id": action.message_id,
        },
    )
    save_native_continuation(store, confirmed)
    retry_request = NativeRetryRequest(
        operation_id=confirmed.operation_id,
        app_id=confirmed.app_id,
        continuation_kind=confirmed.continuation_kind,
        action=action.action,
        text=confirmed.retry_text,
        actor_open_id=action.actor_open_id,
        user_open_id=confirmed.user_open_id,
        metadata=confirmed.metadata,
    )
    return ResolvedNativeAction(
        action=action,
        continuation=confirmed,
        retry_request=retry_request,
    )


def build_retry_artifact_from_request(request: NativeRetryRequest):
    return build_synthetic_retry_artifact(
        operation_id=request.operation_id,
        app_id=request.app_id,
        user_open_id=request.user_open_id,
        text=request.text,
        reason=request.action,
        metadata={"actor_open_id": request.actor_open_id, **request.metadata},
    )
