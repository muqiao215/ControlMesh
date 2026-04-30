"""Tests for frontstage delivery packaging helpers."""

from __future__ import annotations

from pathlib import Path

from controlmesh.text.frontstage_delivery import prepare_frontstage_text


def test_prepare_frontstage_text_keeps_short_reply_unchanged(tmp_path: Path) -> None:
    text = "Short answer."

    result = prepare_frontstage_text(text, output_dir=tmp_path)

    assert result == text
    assert list(tmp_path.iterdir()) == []


def test_prepare_frontstage_text_keeps_long_telegram_reply_unchanged(tmp_path: Path) -> None:
    text = ("line\n" * 80).strip()

    result = prepare_frontstage_text(text, output_dir=tmp_path, transport="tg")

    assert result == text
    assert list(tmp_path.iterdir()) == []


def test_prepare_frontstage_text_converts_long_reply_to_preview_and_attachment(
    tmp_path: Path,
) -> None:
    text = ("line\n" * 80).strip()

    result = prepare_frontstage_text(text, output_dir=tmp_path, transport="fs")

    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".md"
    assert files[0].read_text(encoding="utf-8") == text
    assert "<file:" in result
    assert "Full output attached" in result
    assert "line" in result
    assert str(files[0]) in result


def test_prepare_frontstage_text_without_attachment_support_returns_preview_only(
    tmp_path: Path,
) -> None:
    text = ("line\n" * 80).strip()

    result = prepare_frontstage_text(
        text,
        output_dir=tmp_path,
        transport="fs",
        supports_attachments=False,
    )

    assert "<file:" not in result
    assert "Output trimmed for chat view" in result
    assert list(tmp_path.iterdir()) == []


def test_prepare_frontstage_text_preserves_existing_file_tags(tmp_path: Path) -> None:
    text = "See attached <file:/tmp/report.md>"

    result = prepare_frontstage_text(text, output_dir=tmp_path)

    assert result == text
    assert list(tmp_path.iterdir()) == []
