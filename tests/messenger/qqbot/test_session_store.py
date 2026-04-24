from __future__ import annotations

from controlmesh.messenger.qqbot.session_store import QQBotSessionState, QQBotSessionStore


def test_session_store_round_trip(tmp_path) -> None:
    store = QQBotSessionStore(tmp_path)
    state = QQBotSessionState(session_id="sess-1", last_seq=7, gateway_url="wss://gateway")

    store.save_state("1903891442", state)
    restored = store.load_state("1903891442")

    assert restored == state


def test_session_store_clear_removes_state(tmp_path) -> None:
    store = QQBotSessionStore(tmp_path)
    store.save_state("1903891442", QQBotSessionState(session_id="sess-1", last_seq=7))

    store.clear("1903891442")

    assert store.load_state("1903891442") == QQBotSessionState()


def test_session_store_ignores_invalid_payload(tmp_path) -> None:
    store = QQBotSessionStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"accounts":{"1903891442":{"session_id":123}}}', encoding="utf-8")

    assert store.load_state("1903891442") == QQBotSessionState()
