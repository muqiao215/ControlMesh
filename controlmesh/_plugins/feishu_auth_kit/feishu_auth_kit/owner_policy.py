from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .models import AppInfo


class OwnerPolicyMode(str, Enum):
    STRICT_OWNER = "strict_owner"
    PERMISSIVE_IF_UNKNOWN = "permissive_if_unknown"


class OwnerPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnerPolicyResult:
    allowed: bool
    mode: OwnerPolicyMode
    owner_open_id: str | None
    current_user_open_id: str | None
    reason: str
    app_info: AppInfo


def _resolve_app_info(source: AppInfo | Any, *, app_id: str = "me") -> AppInfo:
    if isinstance(source, AppInfo):
        return source
    getter = getattr(source, "get_app_info", None)
    if callable(getter):
        return getter(app_id)
    raise TypeError("source must be AppInfo or expose get_app_info(app_id)")


def check_owner_policy(
    source: AppInfo | Any,
    *,
    current_user_open_id: str | None,
    mode: OwnerPolicyMode = OwnerPolicyMode.STRICT_OWNER,
    app_id: str = "me",
) -> OwnerPolicyResult:
    app_info = _resolve_app_info(source, app_id=app_id)
    owner_open_id = (
        app_info.effective_owner_open_id or app_info.owner_open_id or app_info.creator_id
    )

    if not owner_open_id:
        allowed = mode == OwnerPolicyMode.PERMISSIVE_IF_UNKNOWN
        reason = (
            "owner metadata unavailable; permissive mode allowed continuation"
            if allowed
            else "owner metadata unavailable; strict owner mode blocks continuation"
        )
        return OwnerPolicyResult(
            allowed=allowed,
            mode=mode,
            owner_open_id=None,
            current_user_open_id=current_user_open_id,
            reason=reason,
            app_info=app_info,
        )

    if not current_user_open_id:
        return OwnerPolicyResult(
            allowed=False,
            mode=mode,
            owner_open_id=owner_open_id,
            current_user_open_id=None,
            reason="current user open_id is required for owner policy enforcement",
            app_info=app_info,
        )

    if current_user_open_id == owner_open_id:
        return OwnerPolicyResult(
            allowed=True,
            mode=mode,
            owner_open_id=owner_open_id,
            current_user_open_id=current_user_open_id,
            reason="current user matches app owner",
            app_info=app_info,
        )

    return OwnerPolicyResult(
        allowed=False,
        mode=mode,
        owner_open_id=owner_open_id,
        current_user_open_id=current_user_open_id,
        reason=f"owner policy rejected user {current_user_open_id}; app owner is {owner_open_id}",
        app_info=app_info,
    )


def assert_owner_policy(
    source: AppInfo | Any,
    *,
    current_user_open_id: str | None,
    mode: OwnerPolicyMode = OwnerPolicyMode.STRICT_OWNER,
    app_id: str = "me",
) -> OwnerPolicyResult:
    result = check_owner_policy(
        source,
        current_user_open_id=current_user_open_id,
        mode=mode,
        app_id=app_id,
    )
    if not result.allowed:
        raise OwnerPolicyError(result.reason)
    return result
