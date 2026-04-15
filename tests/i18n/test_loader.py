"""Tests for the i18n translation loader."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from controlmesh.i18n import LANGUAGES, get_language, get_store, init, t, t_cmd, t_plural, t_rich
from controlmesh.i18n.loader import TranslationStore, _flatten, _load_toml

# -- _flatten ------------------------------------------------------------------


def test_flatten_simple() -> None:
    assert _flatten({"a": "hello"}) == {"a": "hello"}


def test_flatten_nested() -> None:
    assert _flatten({"a": {"b": "hello", "c": "world"}}) == {
        "a.b": "hello",
        "a.c": "world",
    }


def test_flatten_deep() -> None:
    result = _flatten({"a": {"b": {"c": "deep"}}})
    assert result == {"a.b.c": "deep"}


# -- _load_toml ----------------------------------------------------------------


def test_load_toml_missing(tmp_path: Path) -> None:
    result = _load_toml(tmp_path / "nonexistent.toml")
    assert result == {}


def test_load_toml_invalid(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("this is not [valid toml", encoding="utf-8")
    result = _load_toml(bad)
    assert result == {}


def test_load_toml_valid(tmp_path: Path) -> None:
    good = tmp_path / "good.toml"
    good.write_text('[section]\nkey = "value"', encoding="utf-8")
    result = _load_toml(good)
    assert result == {"section.key": "value"}


# -- TranslationStore ---------------------------------------------------------


def test_store_english() -> None:
    store = TranslationStore("en")
    # chat.toml must have at least some keys.
    assert len(store.all_chat_keys()) > 0
    assert len(store.all_cmd_keys()) > 0


def test_store_fallback_missing_key() -> None:
    store = TranslationStore("en")
    result = store.chat("this.key.does.not.exist")
    assert result == "[MISSING: this.key.does.not.exist]"


def test_store_variable_substitution() -> None:
    store = TranslationStore("en")
    result = store.chat("session.error_body", model="opus")
    assert "opus" in result
    assert "{model}" not in result


def test_store_missing_placeholder_graceful() -> None:
    store = TranslationStore("en")
    # Call with a key that has placeholders but don't provide them.
    result = store.chat("session.error_body")
    # Should return raw string (not crash), since format_map raises KeyError.
    assert "{model}" in result


# -- Public API ----------------------------------------------------------------


def test_init_default() -> None:
    init()
    assert get_language() == "en"


def test_init_english() -> None:
    init("en")
    assert get_language() == "en"


def test_init_unknown_falls_back_to_english() -> None:
    init("xx_unknown")
    assert get_language() == "en"


def test_t_returns_string() -> None:
    init("en")
    result = t("session.error_header")
    assert isinstance(result, str)
    assert "Session Error" in result


def test_t_with_kwargs() -> None:
    init("en")
    result = t("stop.killed", provider="Claude")
    assert "Claude" in result


def test_t_rich_returns_string() -> None:
    init("en")
    result = t_rich("wizard.common.cancelled")
    assert isinstance(result, str)
    assert "cancelled" in result.lower()


def test_t_cmd_returns_string() -> None:
    init("en")
    result = t_cmd("bot.new")
    assert isinstance(result, str)
    assert len(result) > 0


def test_t_plural_one() -> None:
    init("en")
    result = t_plural("tasks.cancelled", 1)
    assert "1 task." in result


def test_t_plural_many() -> None:
    init("en")
    result = t_plural("tasks.cancelled", 5)
    assert "5 tasks." in result


# -- TOML file integrity -------------------------------------------------------


@pytest.fixture
def en_store() -> TranslationStore:
    init("en")
    return get_store()


def test_all_chat_keys_resolvable(en_store: TranslationStore) -> None:
    """Every English chat key should resolve without error."""
    for key in en_store.all_chat_keys():
        result = en_store.chat(key)
        assert "[MISSING:" not in result, f"Key {key!r} is missing"


def test_all_cmd_keys_resolvable(en_store: TranslationStore) -> None:
    for key in en_store.all_cmd_keys():
        result = en_store.cmd(key)
        assert "[MISSING:" not in result, f"Key {key!r} is missing"


def test_no_empty_values(en_store: TranslationStore) -> None:
    """No chat key should have an empty string value."""
    for key in en_store.all_chat_keys():
        result = en_store.chat(key)
        # Skip keys that are legitimately short.
        assert result.strip(), f"Key {key!r} has empty value"


def test_command_descriptions_short() -> None:
    """Bot command descriptions must fit Telegram's ≤256 char limit."""
    init("en")
    store = get_store()
    for key in store.all_cmd_keys():
        val = store.cmd(key)
        assert len(val) <= 256, f"Command {key!r} too long: {len(val)} chars"


# -- Placeholder consistency ---------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _extract_placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text))


def test_chat_placeholders_are_valid(en_store: TranslationStore) -> None:
    """All placeholders in chat strings should be simple {word} format."""
    for key in en_store.all_chat_keys():
        val = en_store.chat(key)
        placeholders = _extract_placeholders(val)
        for ph in placeholders:
            assert ph.isidentifier(), f"Bad placeholder {{{ph}}} in {key}"


# -- LANGUAGES dict consistency ------------------------------------------------


def test_languages_has_en() -> None:
    assert "en" in LANGUAGES


def test_all_language_dirs_exist() -> None:
    i18n_dir = Path(__file__).resolve().parent.parent.parent / "controlmesh" / "i18n"
    for lang_code in LANGUAGES:
        lang_dir = i18n_dir / lang_code
        assert lang_dir.is_dir(), f"Language dir missing: {lang_dir}"
