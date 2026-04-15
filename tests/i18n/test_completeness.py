"""Tests for translation completeness between languages."""

from __future__ import annotations

import re

import pytest

from controlmesh.i18n import LANGUAGES, init
from controlmesh.i18n.loader import TranslationStore

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text))


@pytest.fixture(params=[lang for lang in LANGUAGES if lang != "en"])
def lang_store(request: pytest.FixtureRequest) -> tuple[str, TranslationStore]:
    """Parametrized fixture: one run per non-English language."""
    lang: str = request.param
    return lang, TranslationStore(lang)


def test_chat_key_completeness(lang_store: tuple[str, TranslationStore]) -> None:
    """Every English chat key must exist in the translated language."""
    lang, store = lang_store
    en_keys = store.all_chat_keys()
    lang_keys = store.lang_chat_keys()
    missing = en_keys - lang_keys
    assert not missing, f"[{lang}] chat.toml missing keys: {sorted(missing)}"


def test_cli_key_completeness(lang_store: tuple[str, TranslationStore]) -> None:
    """Every English CLI key must exist in the translated language."""
    lang, store = lang_store
    en_keys = store.all_cli_keys()
    lang_keys = store.lang_cli_keys()
    missing = en_keys - lang_keys
    assert not missing, f"[{lang}] cli.toml/wizard.toml missing keys: {sorted(missing)}"


def test_cmd_key_completeness(lang_store: tuple[str, TranslationStore]) -> None:
    """Every English command key must exist in the translated language."""
    lang, store = lang_store
    en_keys = store.all_cmd_keys()
    lang_keys = store.lang_cmd_keys()
    missing = en_keys - lang_keys
    assert not missing, f"[{lang}] commands.toml missing keys: {sorted(missing)}"


def test_chat_placeholder_match(lang_store: tuple[str, TranslationStore]) -> None:
    """Translated chat strings must use the same {placeholders} as English."""
    lang, store = lang_store
    for key in store.all_chat_keys():
        en_val = store._en_chat.get(key, "")
        lang_val = store._chat.get(key, "")
        if not lang_val:
            continue  # Missing key caught by completeness test.
        en_ph = _placeholders(en_val)
        lang_ph = _placeholders(lang_val)
        assert en_ph == lang_ph, (
            f"[{lang}] chat key '{key}': "
            f"EN placeholders {en_ph} != {lang.upper()} placeholders {lang_ph}"
        )


def test_cli_placeholder_match(lang_store: tuple[str, TranslationStore]) -> None:
    """Translated CLI strings must use the same {placeholders} as English."""
    lang, store = lang_store
    for key in store.all_cli_keys():
        en_val = store._en_cli.get(key, "")
        lang_val = store._cli.get(key, "")
        if not lang_val:
            continue
        en_ph = _placeholders(en_val)
        lang_ph = _placeholders(lang_val)
        assert en_ph == lang_ph, (
            f"[{lang}] cli key '{key}': "
            f"EN placeholders {en_ph} != {lang.upper()} placeholders {lang_ph}"
        )


def test_german_loads_without_error() -> None:
    """German translations should load cleanly."""
    init("de")
    store = TranslationStore("de")
    assert store.language == "de"
    assert len(store.lang_chat_keys()) > 0
    assert len(store.lang_cli_keys()) > 0
    assert len(store.lang_cmd_keys()) > 0
