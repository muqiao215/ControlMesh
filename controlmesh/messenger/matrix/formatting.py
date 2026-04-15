"""Convert Markdown to Matrix-compatible HTML.

Matrix supports a richer subset of HTML than Telegram:
- Real headings (h1-h6)
- Code blocks with language hints
- No 4096-char limit (65KB per event)

Returns ``(plain_body, formatted_body)`` for ``m.room.message`` content.
"""

from __future__ import annotations

import html
import re

# Regex for [button:Label] markers — shared with buttons.py
BUTTON_RE = re.compile(r"\[button:([^\]]+)\]")


def strip_button_markers(text: str) -> str:
    """Remove ``[button:...]`` markers from text."""
    return BUTTON_RE.sub("", text).rstrip()


def markdown_to_matrix_html(text: str) -> tuple[str, str]:
    """Convert Markdown to Matrix HTML.

    Returns (plain_body, formatted_body).
    """
    cleaned = strip_button_markers(text)
    formatted = _convert_markdown(cleaned)
    plain = _strip_html(formatted)
    return plain, formatted


def _convert_markdown(text: str) -> str:
    """Convert a subset of Markdown to HTML."""
    if not text:
        return ""
    lines = text.split("\n")
    result: list[str] = []
    in_code_block = False
    code_lang = ""

    for line in lines:
        # Code block toggle
        if line.startswith("```"):
            if in_code_block:
                result.append("</code></pre>")
                in_code_block = False
            else:
                code_lang = line[3:].strip()
                lang_attr = f' class="language-{html.escape(code_lang)}"' if code_lang else ""
                result.append(f"<pre><code{lang_attr}>")
                in_code_block = True
            continue

        if in_code_block:
            result.append(html.escape(line))
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            content = _inline_format(m.group(2))
            result.append(f"<h{level}>{content}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^---+$", line.strip()):
            result.append("<hr>")
            continue

        # Normal line with inline formatting
        if line.strip():
            result.append(_inline_format(line) + "<br>")
        else:
            result.append("<br>")

    if in_code_block:
        result.append("</code></pre>")

    return "\n".join(result)


def _inline_format(text: str) -> str:
    """Apply inline formatting: bold, italic, strikethrough, code, links.

    Substitution order matters:

    1. Inline code first — prevents formatting inside ``code spans``.
    2. Bold (``**``) before italic (``*``) — avoids ``**x**`` matching
       as nested italic.
    3. Strikethrough and links last — no ordering conflicts.
    """
    # Escape HTML first (but preserve already-produced tags)
    text = html.escape(text)

    # 1. Inline code first — prevents formatting inside `code spans`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # 2. Bold (**) before italic (*) — avoids **x** matching as
    #    nested italic
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)

    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Word boundaries prevent matching snake_case (e.g. my_var)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)

    # 3. Strikethrough and links last — no ordering conflicts
    text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)

    # Links [text](url)
    return re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )


def _strip_html(formatted: str) -> str:
    """Strip HTML tags to produce a plain-text body."""
    text = re.sub(r"<[^>]+>", "", formatted)
    return html.unescape(text)
