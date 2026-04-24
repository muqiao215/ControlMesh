"""Transport-native address helpers shared across messengers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias
from urllib.parse import quote, unquote

ChatRef: TypeAlias = int | str
TopicRef: TypeAlias = int | str | None
LockKey: TypeAlias = tuple[ChatRef, TopicRef]

_REF_KIND_INT = "i"
_REF_KIND_STR = "s"


@dataclass(frozen=True, slots=True)
class TransportAddress:
    """Canonical transport-native address."""

    transport: str
    chat_ref: ChatRef
    topic_ref: TopicRef = None


def has_string_ref(chat_ref: ChatRef, topic_ref: TopicRef = None) -> bool:
    """Return True when any ref requires string-safe serialization."""
    return isinstance(chat_ref, str) or isinstance(topic_ref, str)


def encode_storage_ref(ref: ChatRef | TopicRef) -> str:
    """Encode one address ref into a storage-safe tagged token."""
    if ref is None:
        msg = "Cannot encode None as a storage ref token"
        raise ValueError(msg)
    if isinstance(ref, int):
        return f"{_REF_KIND_INT}:{ref}"
    return f"{_REF_KIND_STR}:{quote(ref, safe='')}"


def decode_storage_ref(kind: str, value: str) -> ChatRef:
    """Decode one tagged storage token back into the original ref type."""
    if kind == _REF_KIND_INT:
        return int(value)
    if kind == _REF_KIND_STR:
        return unquote(value)
    msg = f"Unknown storage ref kind: {kind!r}"
    raise ValueError(msg)


def require_string_chat_ref(chat_ref: ChatRef, *, field_name: str = "chat_id") -> str:
    """Require a string-backed target reference."""
    if not isinstance(chat_ref, str):
        msg = f"{field_name} must be a string chat_id for this transport"
        raise TypeError(msg)
    return chat_ref
