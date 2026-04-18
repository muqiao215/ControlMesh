from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import requests

from .models import DeviceAuthorization
from .runtime_cards import (
    ContinuationState,
    FileContinuationStore,
    RuntimeCard,
    build_device_flow_card,
    build_permission_missing_card,
)
from .scopes import batch_scopes, filter_sensitive_scopes

AuthErrorKind = Literal["app_scope_missing", "user_auth_required", "user_scope_insufficient"]
AuthDecision = Literal["permission_card", "device_flow", "authorized"]
ScopeNeedType = Literal["one", "all"]
TokenType = Literal["tenant", "user"]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _default_pending_flow_store_path() -> Path:
    configured = os.getenv("FEISHU_AUTH_KIT_PENDING_FLOW_STORE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.getenv("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home).expanduser()
    else:
        base = Path.home() / ".local" / "state"
    return base / "feishu-auth-kit" / "pending_flows.json"


@dataclass(frozen=True)
class PendingAuthFlow:
    flow_key: str
    operation_id: str
    app_id: str
    user_open_id: str | None
    decision: AuthDecision
    required_scopes: list[str] = field(default_factory=list)
    token_type: TokenType = "user"
    scope_need_type: ScopeNeedType = "all"
    status: str = "pending"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PendingFlowUpsertResult:
    flow: PendingAuthFlow
    reused: bool
    merged_scopes: list[str] = field(default_factory=list)


class FilePendingFlowRegistry:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else _default_pending_flow_store_path()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        items = payload.get("pending_flows", payload)
        if not isinstance(items, dict):
            return {}
        return {str(key): value for key, value in items.items() if isinstance(value, dict)}

    def _write_all(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps({"pending_flows": items}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def load(self, flow_key: str) -> PendingAuthFlow | None:
        item = self._read_all().get(flow_key)
        if not item:
            return None
        return PendingAuthFlow(
            flow_key=str(item["flow_key"]),
            operation_id=str(item["operation_id"]),
            app_id=str(item["app_id"]),
            user_open_id=item.get("user_open_id"),
            decision=item["decision"],
            required_scopes=list(item.get("required_scopes") or []),
            token_type=item.get("token_type", "user"),
            scope_need_type=item.get("scope_need_type", "all"),
            status=str(item.get("status", "pending")),
            metadata=item.get("metadata") or {},
        )

    def remove(self, flow_key: str) -> bool:
        items = self._read_all()
        removed = items.pop(flow_key, None)
        if removed is None:
            return False
        self._write_all(items)
        return True

    def upsert(self, flow: PendingAuthFlow) -> PendingFlowUpsertResult:
        items = self._read_all()
        existing = self.load(flow.flow_key)
        if existing is None:
            items[flow.flow_key] = asdict(flow)
            self._write_all(items)
            return PendingFlowUpsertResult(
                flow=flow,
                reused=False,
                merged_scopes=list(flow.required_scopes),
            )

        merged_scopes = _dedupe_preserve_order(
            [*existing.required_scopes, *flow.required_scopes]
        )
        merged_flow = PendingAuthFlow(
            flow_key=existing.flow_key,
            operation_id=existing.operation_id,
            app_id=existing.app_id,
            user_open_id=flow.user_open_id or existing.user_open_id,
            decision=flow.decision,
            required_scopes=merged_scopes,
            token_type=flow.token_type,
            scope_need_type=flow.scope_need_type,
            status=flow.status,
            metadata={**existing.metadata, **flow.metadata},
        )
        items[flow.flow_key] = asdict(merged_flow)
        self._write_all(items)
        return PendingFlowUpsertResult(
            flow=merged_flow,
            reused=True,
            merged_scopes=merged_scopes,
        )


@dataclass(frozen=True)
class ScopeAuthorizationPlan:
    requested_scopes: list[str]
    app_granted_scopes: list[str]
    user_granted_scopes: list[str]
    already_granted_scopes: list[str]
    missing_user_scopes: list[str]
    unavailable_scopes: list[str]
    batches: list[list[str]]


def plan_scope_authorization(
    *,
    requested_scopes: list[str],
    app_granted_scopes: list[str],
    user_granted_scopes: list[str],
    batch_size: int = 100,
    filter_sensitive: bool = True,
) -> ScopeAuthorizationPlan:
    requested = _dedupe_preserve_order(requested_scopes)
    app_granted = _dedupe_preserve_order(app_granted_scopes)
    user_granted = _dedupe_preserve_order(user_granted_scopes)
    if filter_sensitive:
        requested = filter_sensitive_scopes(requested)
        app_granted = filter_sensitive_scopes(app_granted)
        user_granted = filter_sensitive_scopes(user_granted)
    app_granted_set = set(app_granted)
    user_granted_set = set(user_granted)
    unavailable = [scope for scope in requested if scope not in app_granted_set]
    available = [scope for scope in requested if scope in app_granted_set]
    already = [scope for scope in available if scope in user_granted_set]
    missing = [scope for scope in available if scope not in user_granted_set]
    return ScopeAuthorizationPlan(
        requested_scopes=requested,
        app_granted_scopes=app_granted,
        user_granted_scopes=user_granted,
        already_granted_scopes=already,
        missing_user_scopes=missing,
        unavailable_scopes=unavailable,
        batches=batch_scopes(missing, batch_size=batch_size),
    )


@dataclass(frozen=True)
class AuthRequirement:
    error_kind: AuthErrorKind
    required_scopes: list[str]
    token_type: TokenType = "user"
    scope_need_type: ScopeNeedType = "all"
    user_open_id: str | None = None
    flow_key: str | None = None
    operation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthContinuation:
    operation_id: str
    flow_key: str
    app_id: str
    decision: AuthDecision
    user_open_id: str | None
    required_scopes: list[str]
    token_type: TokenType
    scope_need_type: ScopeNeedType
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_state(self) -> ContinuationState:
        return ContinuationState(
            operation_id=self.operation_id,
            app_id=self.app_id,
            kind=self.decision,
            status="waiting",
            payload={
                "flow_key": self.flow_key,
                "user_open_id": self.user_open_id,
                "required_scopes": self.required_scopes,
                "token_type": self.token_type,
                "scope_need_type": self.scope_need_type,
                "metadata": self.metadata,
            },
        )

    @classmethod
    def from_state(cls, state: ContinuationState) -> AuthContinuation:
        payload = state.payload
        return cls(
            operation_id=state.operation_id,
            flow_key=str(payload["flow_key"]),
            app_id=state.app_id,
            decision=state.kind,  # type: ignore[arg-type]
            user_open_id=payload.get("user_open_id"),
            required_scopes=list(payload.get("required_scopes") or []),
            token_type=payload.get("token_type", "user"),
            scope_need_type=payload.get("scope_need_type", "all"),
            metadata=payload.get("metadata") or {},
        )


def save_auth_continuation(
    store: FileContinuationStore,
    continuation: AuthContinuation,
) -> ContinuationState:
    state = continuation.to_state()
    store.save(state)
    return state


def load_auth_continuation(
    store: FileContinuationStore,
    operation_id: str,
) -> AuthContinuation | None:
    state = store.load(operation_id)
    if state is None:
        return None
    return AuthContinuation.from_state(state)


@dataclass(frozen=True)
class RoutedAuthAction:
    decision: AuthDecision
    flow: PendingAuthFlow
    reused_existing_flow: bool
    continuation: AuthContinuation
    card: RuntimeCard | None = None
    unavailable_scopes: list[str] = field(default_factory=list)
    batches: list[list[str]] = field(default_factory=list)


def route_auth_requirement(
    *,
    app_id: str,
    requirement: AuthRequirement,
    pending_flows: FilePendingFlowRegistry,
    continuation_store: FileContinuationStore,
    permission_url: str | None = None,
    authorization: DeviceAuthorization | None = None,
) -> RoutedAuthAction:
    decision: AuthDecision
    if requirement.error_kind == "app_scope_missing":
        decision = "permission_card"
    else:
        decision = "device_flow"

    flow_key = (
        requirement.flow_key
        or f"{app_id}:{requirement.user_open_id or 'unknown'}:{decision}"
    )
    operation_id = requirement.operation_id or uuid.uuid4().hex
    upsert = pending_flows.upsert(
        PendingAuthFlow(
            flow_key=flow_key,
            operation_id=operation_id,
            app_id=app_id,
            user_open_id=requirement.user_open_id,
            decision=decision,
            required_scopes=list(requirement.required_scopes),
            token_type=requirement.token_type,
            scope_need_type=requirement.scope_need_type,
            metadata=requirement.metadata,
        )
    )
    continuation = AuthContinuation(
        operation_id=upsert.flow.operation_id,
        flow_key=upsert.flow.flow_key,
        app_id=app_id,
        decision=decision,
        user_open_id=upsert.flow.user_open_id,
        required_scopes=upsert.merged_scopes,
        token_type=upsert.flow.token_type,
        scope_need_type=upsert.flow.scope_need_type,
        metadata=upsert.flow.metadata,
    )
    save_auth_continuation(continuation_store, continuation)

    if decision == "permission_card":
        if not permission_url:
            raise ValueError("permission_url is required for app_scope_missing routing")
        card = build_permission_missing_card(
            app_id=app_id,
            operation_id=upsert.flow.operation_id,
            missing_scopes=upsert.merged_scopes,
            permission_url=permission_url,
            user_open_id=upsert.flow.user_open_id,
        )
        return RoutedAuthAction(
            decision=decision,
            flow=upsert.flow,
            reused_existing_flow=upsert.reused,
            continuation=continuation,
            card=card,
        )

    if authorization is None:
        raise ValueError("authorization is required for user auth routing")
    card = build_device_flow_card(
        app_id=app_id,
        operation_id=upsert.flow.operation_id,
        authorization=authorization,
    )
    return RoutedAuthAction(
        decision=decision,
        flow=upsert.flow,
        reused_existing_flow=upsert.reused,
        continuation=continuation,
        card=card,
    )


@dataclass(frozen=True)
class SyntheticRetryArtifact:
    schema: str
    kind: str
    operation_id: str
    app_id: str
    user_open_id: str | None
    text: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_synthetic_retry_artifact(
    *,
    operation_id: str,
    app_id: str,
    user_open_id: str | None,
    text: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> SyntheticRetryArtifact:
    return SyntheticRetryArtifact(
        schema="feishu-auth-kit.synthetic-retry.v1",
        kind="synthetic_retry",
        operation_id=operation_id,
        app_id=app_id,
        user_open_id=user_open_id,
        text=text,
        reason=reason,
        metadata=metadata or {},
    )


@dataclass(frozen=True)
class IdentityVerificationResult:
    valid: bool
    expected_open_id: str
    actual_open_id: str | None = None


def verify_access_token_identity(
    *,
    access_token: str,
    expected_open_id: str,
    brand: str = "feishu",
    session: Any | None = None,
    timeout: int = 30,
) -> IdentityVerificationResult:
    from .domains import resolve_domains

    current_session = session or requests.Session()
    domains = resolve_domains(brand)
    response = current_session.request(
        "GET",
        f"{domains.open_base}/open-apis/authen/v1/user_info",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=timeout,
    )
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("code", 0) not in (0, None):
        actual = (
            payload.get("data", {}).get("open_id")
            if isinstance(payload.get("data"), dict)
            else None
        )
        return IdentityVerificationResult(
            valid=False,
            expected_open_id=expected_open_id,
            actual_open_id=actual,
        )
    data = payload.get("data") or payload
    actual_open_id = data.get("open_id") if isinstance(data, dict) else None
    return IdentityVerificationResult(
        valid=actual_open_id == expected_open_id,
        expected_open_id=expected_open_id,
        actual_open_id=actual_open_id,
    )
