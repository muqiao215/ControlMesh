"""Tool grant snapshots: issued authorization carried with execution identity.

A :class:`ToolGrantSnapshot` is the persisted, minimal-privilege authorization for
one task.  Trusted Python ingress issues it; provider adapters map it onto their
natively enforceable surface before any provider process is created, or fail
closed with :class:`ToolGrantDenied` when the restriction cannot be enforced.

Grants are authorization state, distinct from :class:`~controlmesh.bus.envelope.
ExecutionContext` provenance: provenance says where a task came from, a grant
says what it may do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from controlmesh.errors import CLIError

TOOL_GRANT_SCHEMA_VERSION = "controlmesh.tool_grant.v1"

_NETWORK_POLICIES = frozenset({"sandbox_default", "no_network"})
_CONFIRMATION_POLICIES = frozenset({"provider_runtime", "controller_required"})
_TOOL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_:\.\-]{0,63}$")
_BOUNDED_TOKEN_RE = re.compile(r"^[^\r\n\x00]{0,128}$")
_ROOT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\.\-/]{1,256}$")

_GRANT_SURFACES = frozenset(
    {
        "",
        "claude_tool_flags",
        "codex_sandbox",
        "gemini_policy",
        "opencode_config",
    }
)


@dataclass(frozen=True, slots=True)
class ToolGrantSnapshot:
    """Minimal-privilege authorization bound to one task and its episodes.

    ``provider_surface`` records the surface the issuing ingress validated for
    the initial execution.  It is metadata, never authorization: an adapter
    always re-derives whether it can honor the restrictions on its own surface.
    """

    tool_allow: tuple[str, ...] = ()
    tool_deny: tuple[str, ...] = ()
    network_policy: str = "sandbox_default"
    writable_roots: tuple[str, ...] = ()
    confirmation_policy: str = "provider_runtime"
    provider_surface: str = ""
    reply_transport: str = ""
    reply_chat: str = ""
    reply_topic: str = ""
    reply_thread: str = ""

    @property
    def restrictive(self) -> bool:
        """Whether the grant carries a restriction an adapter must enforce."""
        return bool(
            self.tool_allow
            or self.tool_deny
            or self.writable_roots
            or self.network_policy == "no_network"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TOOL_GRANT_SCHEMA_VERSION,
            "tool_allow": list(self.tool_allow),
            "tool_deny": list(self.tool_deny),
            "network_policy": self.network_policy,
            "writable_roots": list(self.writable_roots),
            "confirmation_policy": self.confirmation_policy,
            "provider_surface": self.provider_surface,
            "reply_transport": self.reply_transport,
            "reply_chat": self.reply_chat,
            "reply_topic": self.reply_topic,
            "reply_thread": self.reply_thread,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ToolGrantSnapshot:
        if not isinstance(raw, dict):
            raise ValueError("tool grant must be an object")
        if raw.get("schema_version") != TOOL_GRANT_SCHEMA_VERSION:
            raise ValueError("unsupported persisted tool grant schema_version")
        return cls(
            tool_allow=_tool_tuple(raw.get("tool_allow")),
            tool_deny=_tool_tuple(raw.get("tool_deny")),
            network_policy=_bounded_enum(raw.get("network_policy"), _NETWORK_POLICIES, "network_policy"),
            writable_roots=_root_tuple(raw.get("writable_roots")),
            confirmation_policy=_bounded_enum(
                raw.get("confirmation_policy"), _CONFIRMATION_POLICIES, "confirmation_policy"
            ),
            provider_surface=_bounded_token(raw.get("provider_surface", ""), "provider_surface"),
            reply_transport=_bounded_token(raw.get("reply_transport", ""), "reply_transport"),
            reply_chat=_bounded_token(raw.get("reply_chat", ""), "reply_chat"),
            reply_topic=_bounded_token(raw.get("reply_topic", ""), "reply_topic"),
            reply_thread=_bounded_token(raw.get("reply_thread", ""), "reply_thread"),
        )


def _tool_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("tool grant tool list must be an array")
    items: list[str] = []
    for item in raw:
        token = str(item)
        if not _TOOL_TOKEN_RE.fullmatch(token):
            raise ValueError(f"invalid persisted tool grant tool token: {token!r}")
        if token not in items:
            items.append(token)
    return tuple(items)


def _root_tuple(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("tool grant writable_roots must be an array")
    items: list[str] = []
    for item in raw:
        token = str(item)
        if not _ROOT_TOKEN_RE.fullmatch(token) or ".." in token.split("/"):
            raise ValueError(f"invalid persisted tool grant writable root: {token!r}")
        if token not in items:
            items.append(token)
    return tuple(items)


def _bounded_token(raw: object, name: str) -> str:
    token = str(raw or "")
    if not _BOUNDED_TOKEN_RE.fullmatch(token):
        raise ValueError(f"invalid persisted tool grant {name}")
    return token


def _bounded_enum(raw: object, allowed: frozenset[str], name: str) -> str:
    token = str(raw or "")
    if token not in allowed:
        raise ValueError(f"invalid persisted tool grant {name}: {token!r}")
    return token


@dataclass(frozen=True, slots=True)
class ToolGrantMapping:
    """The natively enforceable translation of one grant for one provider."""

    provider: str
    surface: str
    flags: tuple[str, ...] = ()


class ToolGrantDenied(CLIError):  # noqa: N818
    """Raised before provider construction when a grant cannot be enforced."""

    def __init__(self, provider: str, reason_code: str) -> None:
        self.provider = provider
        self.reason_code = reason_code
        super().__init__(f"tool_grant_denied:{provider}:{reason_code}")

    @property
    def user_message(self) -> str:
        return (
            "This task carries a tool grant that this provider cannot enforce "
            "natively, so no provider process was started. "
            f"provider={self.provider} reason={self.reason_code}"
        )


def issue_tool_grant(
    *,
    tool_allow: tuple[str, ...] | list[str] = (),
    tool_deny: tuple[str, ...] | list[str] = (),
    network_policy: str = "sandbox_default",
    writable_roots: tuple[str, ...] | list[str] = (),
    confirmation_policy: str = "provider_runtime",
    provider_surface: str = "",
    reply_transport: str = "",
    reply_chat: object = "",
    reply_topic: object = "",
    reply_thread: object = "",
) -> ToolGrantSnapshot:
    """Issue a grant from trusted ingress, validating and normalizing input."""
    snapshot = ToolGrantSnapshot.from_dict(
        {
            "schema_version": TOOL_GRANT_SCHEMA_VERSION,
            "tool_allow": list(tool_allow),
            "tool_deny": list(tool_deny),
            "network_policy": network_policy,
            "writable_roots": list(writable_roots),
            "confirmation_policy": confirmation_policy,
            "provider_surface": provider_surface,
            "reply_transport": reply_transport,
            "reply_chat": str(reply_chat or ""),
            "reply_topic": str(reply_topic or ""),
            "reply_thread": str(reply_thread or ""),
        }
    )
    if snapshot.provider_surface and snapshot.provider_surface not in _GRANT_SURFACES:
        raise ValueError(f"unknown tool grant provider_surface: {snapshot.provider_surface!r}")
    return snapshot


@dataclass(frozen=True, slots=True)
class _GrantInput:
    provider: str
    grant: ToolGrantSnapshot
    config_allowed: tuple[str, ...]
    config_disallowed: tuple[str, ...]
    config_permission_mode: str
    config_sandbox_mode: str
    config_cli_parameters: tuple[str, ...] = ()


def map_tool_grant(
    provider: str,
    grant: ToolGrantSnapshot | None,
    *,
    config_allowed: tuple[str, ...] | list[str] = (),
    config_disallowed: tuple[str, ...] | list[str] = (),
    config_permission_mode: str = "",
    config_sandbox_mode: str = "",
    config_cli_parameters: tuple[str, ...] | list[str] = (),
) -> ToolGrantMapping:
    """Translate a grant onto *provider*'s natively enforceable surface.

    Raises :class:`ToolGrantDenied` before any provider process is created when
    the restriction cannot be enforced natively.  A grant never widens static
    configuration: denies are unioned, allows are intersected, and a grant
    combined with bypass/full-access configuration is rejected.
    """
    normalized = _GrantInput(
        provider=provider,
        grant=grant if grant is not None else _FLOOR_GRANT,
        config_allowed=tuple(config_allowed),
        config_disallowed=tuple(config_disallowed),
        config_permission_mode=str(config_permission_mode or ""),
        config_sandbox_mode=str(config_sandbox_mode or ""),
        config_cli_parameters=tuple(config_cli_parameters),
    )
    if grant is None or not grant.restrictive:
        return ToolGrantMapping(provider=provider, surface=f"{provider}_floor")
    if grant.confirmation_policy == "controller_required":
        # A restrictive task claiming controller approval requires real
        # approval evidence, which no reusable mechanism provides yet.
        raise ToolGrantDenied(provider, "controller_approval_unavailable")
    handler = _MAPPERS.get(provider)
    if handler is None:
        raise ToolGrantDenied(provider, "surface_unproven")
    _reject_override_conflicts(normalized)
    return handler(normalized)


def _reject_override_conflicts(data: _GrantInput) -> None:
    """Reject CLI parameter overrides that would defeat the grant's limits."""
    lowered = tuple(item.lower() for item in data.config_cli_parameters)
    if data.provider == "codex":
        joined = " ".join(lowered)
        if "sandbox" in joined or "network_access" in joined:
            raise ToolGrantDenied("codex", "override_conflicts_grant")
    if data.provider == "claude":
        for item in lowered:
            if item.startswith("--dangerously") or item.startswith("--permission-mode"):
                raise ToolGrantDenied("claude", "override_conflicts_grant")


_FLOOR_GRANT = ToolGrantSnapshot()


def _map_claude(data: _GrantInput) -> ToolGrantMapping:
    grant = data.grant
    if data.config_permission_mode == "bypassPermissions":
        raise ToolGrantDenied("claude", "bypass_conflicts_grant")
    if grant.network_policy == "no_network":
        # Claude flags cannot isolate workload network access; denying two
        # built-in tools is not network isolation (R3).
        raise ToolGrantDenied("claude", "no_network_unenforceable")
    if grant.tool_allow:
        raise ToolGrantDenied("claude", "allowlist_not_enforceable_flags")
    if grant.writable_roots:
        raise ToolGrantDenied("claude", "writable_roots_needs_container_mounts")
    denies: list[str] = []
    for token in (*data.config_disallowed, *grant.tool_deny):
        if token not in denies:
            denies.append(token)
    flags: list[str] = []
    if denies:
        flags += ["--disallowedTools", *denies]
    return ToolGrantMapping(provider="claude", surface="claude_tool_flags", flags=tuple(flags))


def _map_codex(data: _GrantInput) -> ToolGrantMapping:
    grant = data.grant
    if grant.tool_allow or grant.tool_deny:
        raise ToolGrantDenied("codex", "tool_granularity_unsupported")
    if grant.writable_roots:
        raise ToolGrantDenied("codex", "writable_roots_unverified")
    if data.config_permission_mode == "bypassPermissions":
        raise ToolGrantDenied("codex", "bypass_conflicts_grant")
    if grant.network_policy == "no_network":
        if data.config_sandbox_mode == "full-access":
            raise ToolGrantDenied("codex", "no_network_conflicts_full_access")
        if data.config_sandbox_mode == "workspace-write":
            return ToolGrantMapping(
                provider="codex",
                surface="codex_sandbox",
                flags=("-c", 'sandbox_workspace_write={"network_access": false}'),
            )
        if data.config_sandbox_mode != "read-only":
            raise ToolGrantDenied("codex", "no_network_unproven_sandbox")
    return ToolGrantMapping(provider="codex", surface="codex_sandbox")


def _map_gemini(data: _GrantInput) -> ToolGrantMapping:
    grant = data.grant
    if grant.tool_allow or grant.tool_deny:
        raise ToolGrantDenied("gemini", "policy_engine_config_unverified")
    if grant.network_policy == "no_network" or grant.writable_roots:
        raise ToolGrantDenied("gemini", "policy_engine_config_unverified")
    return ToolGrantMapping(provider="gemini", surface="gemini_policy")


def _map_opencode(_data: _GrantInput) -> ToolGrantMapping:
    raise ToolGrantDenied("opencode", "config_overlay_unverified")


_MAPPERS = {
    "claude": _map_claude,
    "codex": _map_codex,
    "gemini": _map_gemini,
    "opencode": _map_opencode,
}


class ReplyTargetMismatch(CLIError):  # noqa: N818
    """Raised before delivery when the target diverges from the granted one."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"reply_target_mismatch:{field}")

    @property
    def user_message(self) -> str:
        return (
            "Result delivery was blocked because the delivery target does not "
            "match the task's trusted reply identity. "
            f"field={self.field}"
        )


def validate_reply_target(
    grant: ToolGrantSnapshot | None,
    *,
    transport: str,
    chat_id: object,
    topic_id: object = "",
    thread_id: object = "",
) -> None:
    """Verify delivery identity matches the grant's trusted reply identity.

    Only fields the grant actually pins are checked; a grant without reply
    identity (legacy records) accepts the trusted delivery target unchanged.
    """
    if grant is None:
        return
    checks = (
        ("reply_transport", transport),
        ("reply_chat", str(chat_id or "")),
        ("reply_topic", str(topic_id or "")),
        ("reply_thread", str(thread_id or "")),
    )
    for field_name, granted_value in checks:
        expected = getattr(grant, field_name)
        if expected and str(granted_value or "") != expected:
            raise ReplyTargetMismatch(field_name)


def issue_task_grant_for_submit(
    *,
    source_scope: str,
    requested_tool_deny: tuple[str, ...] | list[str] = (),
    requested_no_network: bool = False,
    transport: str,
    chat_id: object = "",
    topic_id: object = "",
    thread_id: object = "",
) -> ToolGrantSnapshot:
    """Issue the submit-time grant from the source floor plus narrowing requests.

    Trusted ingress only: restriction requests may only narrow (deny list and
    network isolation); there is no way to request widened permissions through
    this path, and message content never reaches it.
    """
    from controlmesh.execution_policy import SOURCE_SCOPES_REQUIRING_SANDBOX, SourceScope

    try:
        sandbox_required = SourceScope(str(source_scope)) in SOURCE_SCOPES_REQUIRING_SANDBOX
    except ValueError:
        sandbox_required = False
    floor_confirmation = "controller_required" if sandbox_required else "provider_runtime"
    return issue_tool_grant(
        tool_deny=tuple(requested_tool_deny),
        network_policy="no_network" if requested_no_network else "sandbox_default",
        confirmation_policy=floor_confirmation,
        reply_transport=str(transport or ""),
        reply_chat=str(chat_id or ""),
        reply_topic=str(topic_id or ""),
        reply_thread=str(thread_id or ""),
    )
