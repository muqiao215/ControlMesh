from __future__ import annotations

from controlmesh.messenger.qqbot.known_targets import QQBotKnownTargetsStore


def test_known_targets_store_round_trip_and_filtering(tmp_path) -> None:
    store = QQBotKnownTargetsStore(tmp_path)

    store.record_target("1903891442", "qqbot:c2c:USER_A")
    store.record_target("1903891442", "qqbot:group:GROUP_A")
    store.record_target("1903891442", "qqbot:dm:GUILD_DM_A")
    store.record_target("1903891442", "qqbot:channel:CHANNEL_A")

    assert store.list_targets("1903891442") == (
        "qqbot:c2c:USER_A",
        "qqbot:group:GROUP_A",
        "qqbot:dm:GUILD_DM_A",
    )
    assert store.list_targets("1903891442", kinds=("group",)) == ("qqbot:group:GROUP_A",)
    assert store.list_targets("1903891442", kinds=("c2c", "dm")) == (
        "qqbot:c2c:USER_A",
        "qqbot:dm:GUILD_DM_A",
    )


def test_known_targets_store_ignores_invalid_payload(tmp_path) -> None:
    store = QQBotKnownTargetsStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text('{"accounts":{"1903891442":{"targets":[123,"qqbot:c2c:USER_A"]}}}', encoding="utf-8")

    assert store.list_targets("1903891442") == ("qqbot:c2c:USER_A",)
