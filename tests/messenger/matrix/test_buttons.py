"""Tests for matrix/buttons.py: reaction-based button replacement."""

from __future__ import annotations

from controlmesh.messenger.matrix.buttons import REACTION_DIGITS, ButtonTracker


class TestButtonTracker:
    def test_extract_single_button(self) -> None:
        bt = ButtonTracker()
        result = bt.extract_and_format("!room:s", "Pick one [button:Yes] [button:No]")
        assert "Yes" in result
        assert "No" in result
        assert REACTION_DIGITS[0] in result
        assert REACTION_DIGITS[1] in result
        assert "[button:" not in result

    def test_no_buttons_returns_unchanged(self) -> None:
        bt = ButtonTracker()
        text = "Just regular text"
        assert bt.extract_and_format("!room:s", text) == text

    def test_match_input_returns_callback_data(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:Alpha] [button:Beta]")
        # For [button:] markers, callback_data == label
        assert bt.match_input("!room:s", "1") == "Alpha"

    def test_match_input_second_option(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:A] [button:B] [button:C]")
        assert bt.match_input("!room:s", "3") == "C"

    def test_match_consumes_buttons(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:A] [button:B]")
        bt.match_input("!room:s", "1")
        # After consumption, no match
        assert bt.match_input("!room:s", "2") is None

    def test_match_invalid_number(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:A]")
        assert bt.match_input("!room:s", "5") is None

    def test_match_non_numeric(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:A]")
        assert bt.match_input("!room:s", "hello") is None

    def test_match_no_active_buttons(self) -> None:
        bt = ButtonTracker()
        assert bt.match_input("!room:s", "1") is None

    def test_clear_removes_buttons(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!room:s", "Choose [button:A]")
        bt.clear("!room:s")
        assert bt.match_input("!room:s", "1") is None

    def test_different_rooms_isolated(self) -> None:
        bt = ButtonTracker()
        bt.extract_and_format("!r1:s", "Q [button:X]")
        bt.extract_and_format("!r2:s", "Q [button:Y]")
        assert bt.match_input("!r1:s", "1") == "X"
        assert bt.match_input("!r2:s", "1") == "Y"


class TestRegisterButtons:
    def test_register_and_match_reaction(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["CLAUDE", "CODEX"],
            callback_data=["ms:p:claude", "ms:p:codex"],
        )
        assert bt.match_reaction("!room:s", "$evt1", REACTION_DIGITS[0]) == "ms:p:claude"

    def test_reaction_second_option(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["CLAUDE", "CODEX", "GEMINI"],
            callback_data=["ms:p:claude", "ms:p:codex", "ms:p:gemini"],
        )
        assert bt.match_reaction("!room:s", "$evt1", REACTION_DIGITS[2]) == "ms:p:gemini"

    def test_reaction_wrong_event_id(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["A"],
            callback_data=["cb:a"],
        )
        assert bt.match_reaction("!room:s", "$wrong", REACTION_DIGITS[0]) is None

    def test_reaction_wrong_emoji(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["A"],
            callback_data=["cb:a"],
        )
        assert bt.match_reaction("!room:s", "$evt1", "👍") is None

    def test_reaction_consumes_buttons(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["A", "B"],
            callback_data=["cb:a", "cb:b"],
        )
        bt.match_reaction("!room:s", "$evt1", REACTION_DIGITS[0])
        assert bt.match_reaction("!room:s", "$evt1", REACTION_DIGITS[1]) is None

    def test_reaction_wrong_room(self) -> None:
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["A"],
            callback_data=["cb:a"],
        )
        assert bt.match_reaction("!other:s", "$evt1", REACTION_DIGITS[0]) is None

    def test_text_input_fallback_with_registered_buttons(self) -> None:
        """Typed number still works for registered buttons."""
        bt = ButtonTracker()
        bt.register_buttons(
            "!room:s",
            "$evt1",
            labels=["CLAUDE", "CODEX"],
            callback_data=["ms:p:claude", "ms:p:codex"],
        )
        assert bt.match_input("!room:s", "2") == "ms:p:codex"
