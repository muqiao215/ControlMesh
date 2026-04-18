from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import DeviceAuthorization


def default_continuation_store_path() -> Path:
    configured = os.getenv("FEISHU_AUTH_KIT_CONTINUATION_STORE")
    if configured:
        return Path(configured).expanduser()
    state_home = os.getenv("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home).expanduser()
    else:
        base = Path.home() / ".local" / "state"
    return base / "feishu-auth-kit" / "continuations.json"


def new_operation_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class CardAction:
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        body = {"action": self.action, "payload": self.payload}
        if self.label:
            body["label"] = self.label
        return body


@dataclass(frozen=True)
class CardLink:
    label: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "url": self.url}


@dataclass(frozen=True)
class RuntimeCard:
    type: str
    operation_id: str
    title: str
    message: str
    app_id: str
    actions: list[CardAction] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)
    links: list[CardLink] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "feishu-auth-kit.card.v1",
            "type": self.type,
            "operation_id": self.operation_id,
            "app_id": self.app_id,
            "title": self.title,
            "message": self.message,
            "fields": self.fields,
            "actions": [item.to_dict() for item in self.actions],
            "links": [item.to_dict() for item in self.links],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ContinuationState:
    operation_id: str
    app_id: str
    kind: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)


class FileContinuationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_continuation_store_path()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        states = payload.get("continuations", payload)
        if not isinstance(states, dict):
            return {}
        return {str(key): value for key, value in states.items() if isinstance(value, dict)}

    def _write_all(self, items: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps({"continuations": items}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def save(self, state: ContinuationState) -> ContinuationState:
        items = self._read_all()
        items[state.operation_id] = asdict(state)
        self._write_all(items)
        return state

    def load(self, operation_id: str) -> ContinuationState | None:
        item = self._read_all().get(operation_id)
        if not item:
            return None
        return ContinuationState(
            operation_id=str(item["operation_id"]),
            app_id=str(item["app_id"]),
            kind=str(item["kind"]),
            status=str(item["status"]),
            payload=item.get("payload") or {},
        )

    def remove(self, operation_id: str) -> bool:
        items = self._read_all()
        removed = items.pop(operation_id, None)
        if removed is None:
            return False
        self._write_all(items)
        return True


def build_permission_missing_card(
    *,
    app_id: str,
    operation_id: str,
    missing_scopes: list[str],
    permission_url: str,
    user_open_id: str | None = None,
) -> RuntimeCard:
    return RuntimeCard(
        type="permission_missing",
        operation_id=operation_id,
        app_id=app_id,
        title="App permissions required",
        message="Grant the missing Feishu/Lark permissions, then continue the authorization flow.",
        fields={"missing_scopes": missing_scopes, "user_open_id": user_open_id},
        actions=[
            CardAction(
                action="permissions_granted_continue",
                label="I have granted permissions",
                payload={"operation_id": operation_id},
            )
        ],
        links=[CardLink(label="Open permission page", url=permission_url)],
    )


def build_device_flow_card(
    *,
    app_id: str,
    operation_id: str,
    authorization: DeviceAuthorization,
) -> RuntimeCard:
    return RuntimeCard(
        type="device_flow_authorization",
        operation_id=operation_id,
        app_id=app_id,
        title="User authorization required",
        message="Open the verification URL, complete device authorization, then continue.",
        fields={
            "device_code": authorization.device_code,
            "user_code": authorization.user_code,
            "verification_uri": authorization.verification_uri,
            "verification_uri_complete": authorization.verification_uri_complete,
            "expires_in": authorization.expires_in,
            "interval": authorization.interval,
        },
        actions=[
            CardAction(
                action="device_authorized_continue",
                label="I have completed authorization",
                payload={"operation_id": operation_id},
            )
        ],
        links=[
            CardLink(
                label="Open verification URL",
                url=authorization.verification_uri_complete,
            )
        ],
    )


def process_card_action(
    action: CardAction,
    store: FileContinuationStore,
) -> ContinuationState:
    operation_id = str(action.payload.get("operation_id") or "").strip()
    if not operation_id:
        raise ValueError("operation_id is required in action payload")
    current = store.load(operation_id)
    if not current:
        raise KeyError(f"unknown continuation operation_id: {operation_id}")
    updated = ContinuationState(
        operation_id=current.operation_id,
        app_id=current.app_id,
        kind=current.kind,
        status="confirmed",
        payload={**current.payload, **action.payload, "last_action": action.action},
    )
    store.save(updated)
    return updated

