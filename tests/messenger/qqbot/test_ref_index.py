from __future__ import annotations

from controlmesh.messenger.qqbot.ref_index import QQBotRefIndexEntry, QQBotRefIndexStore


def test_ref_index_store_round_trip(tmp_path) -> None:
    store = QQBotRefIndexStore(tmp_path)

    store.record_ref(
        "1903891442",
        "REFIDX_bot_1",
        QQBotRefIndexEntry(
            target="qqbot:group:GROUP_A",
            content="hello group",
            timestamp_ms=1_713_956_400_000,
            is_bot=True,
        ),
    )

    assert store.get_ref("1903891442", "REFIDX_bot_1") == QQBotRefIndexEntry(
        target="qqbot:group:GROUP_A",
        content="hello group",
        timestamp_ms=1_713_956_400_000,
        is_bot=True,
    )


def test_ref_index_store_ignores_invalid_payload(tmp_path) -> None:
    store = QQBotRefIndexStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        (
            '{"accounts":{"1903891442":{"refs":{"REFIDX_bad":123,'
            '"REFIDX_ok":{"target":"qqbot:group:GROUP_A","content":"ok","timestamp_ms":1,"is_bot":true}}}}}'
        ),
        encoding="utf-8",
    )

    assert store.get_ref("1903891442", "REFIDX_bad") is None
    assert store.get_ref("1903891442", "REFIDX_ok") == QQBotRefIndexEntry(
        target="qqbot:group:GROUP_A",
        content="ok",
        timestamp_ms=1,
        is_bot=True,
    )
