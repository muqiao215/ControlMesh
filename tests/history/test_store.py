"""Tests for frontstage transcript storage."""

from __future__ import annotations

from pathlib import Path

from controlmesh.history import TranscriptStore, TranscriptTurn
from controlmesh.session import SessionKey
from controlmesh.workspace.paths import ControlMeshPaths


def _paths(tmp_path: Path) -> ControlMeshPaths:
    return ControlMeshPaths(
        controlmesh_home=tmp_path / ".controlmesh",
        home_defaults=Path("/opt/controlmesh/workspace"),
        framework_root=Path("/opt/controlmesh"),
    )


def test_transcript_store_path_for_root_session(tmp_path: Path) -> None:
    store = TranscriptStore(_paths(tmp_path))
    assert store.path_for(SessionKey.telegram(123)) == tmp_path / ".controlmesh" / "transcripts" / "tg" / "123" / "root.jsonl"


def test_transcript_store_append_and_read_recent(tmp_path: Path) -> None:
    store = TranscriptStore(_paths(tmp_path))
    key = SessionKey.telegram(123, 9)
    store.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="user",
            visible_content="hello",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )
    store.append_turn(
        TranscriptTurn(
            session_key=key.storage_key,
            surface_session_id=key.storage_key,
            role="assistant",
            visible_content="world",
            source="normal_chat",
            transport=key.transport,
            chat_id=key.chat_id,
            topic_id=key.topic_id,
        )
    )

    turns = store.read_recent(key, limit=10)
    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert [turn.visible_content for turn in turns] == ["hello", "world"]


def test_transcript_store_read_recent_limits_tail(tmp_path: Path) -> None:
    store = TranscriptStore(_paths(tmp_path))
    key = SessionKey.telegram(123)
    for idx in range(3):
        store.append_turn(
            TranscriptTurn(
                session_key=key.storage_key,
                surface_session_id=key.storage_key,
                role="assistant",
                visible_content=f"m{idx}",
                source="normal_chat",
                transport=key.transport,
                chat_id=key.chat_id,
                topic_id=key.topic_id,
            )
        )

    turns = store.read_recent(key, limit=2)
    assert [turn.visible_content for turn in turns] == ["m1", "m2"]
