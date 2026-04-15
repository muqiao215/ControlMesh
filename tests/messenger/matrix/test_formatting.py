"""Tests for matrix/formatting.py: Markdown → Matrix HTML conversion."""

from __future__ import annotations

from controlmesh.messenger.matrix.formatting import markdown_to_matrix_html, strip_button_markers


class TestStripButtonMarkers:
    def test_removes_buttons(self) -> None:
        assert strip_button_markers("text [button:OK]") == "text"

    def test_multiple_buttons(self) -> None:
        result = strip_button_markers("[button:A] mid [button:B]")
        assert "[button:" not in result
        assert "mid" in result

    def test_no_buttons_unchanged(self) -> None:
        assert strip_button_markers("plain text") == "plain text"


class TestMarkdownToMatrixHtml:
    def test_bold(self) -> None:
        plain, html = markdown_to_matrix_html("**bold**")
        assert "<strong>bold</strong>" in html
        assert "bold" in plain
        assert "<" not in plain

    def test_italic(self) -> None:
        _, html = markdown_to_matrix_html("*italic*")
        assert "<em>italic</em>" in html

    def test_inline_code(self) -> None:
        _, html = markdown_to_matrix_html("use `func()`")
        assert "<code>func()</code>" in html

    def test_code_block(self) -> None:
        text = "```python\nprint('hi')\n```"
        _, html = markdown_to_matrix_html(text)
        assert '<pre><code class="language-python">' in html
        assert "print(&#x27;hi&#x27;)" in html or "print('hi')" in html

    def test_code_block_no_language(self) -> None:
        text = "```\ncode\n```"
        _, html = markdown_to_matrix_html(text)
        assert "<pre><code>" in html

    def test_heading(self) -> None:
        _, html = markdown_to_matrix_html("## Title")
        assert "<h2>Title</h2>" in html

    def test_heading_h1(self) -> None:
        _, html = markdown_to_matrix_html("# Big")
        assert "<h1>Big</h1>" in html

    def test_horizontal_rule(self) -> None:
        _, html = markdown_to_matrix_html("---")
        assert "<hr>" in html

    def test_strikethrough(self) -> None:
        _, html = markdown_to_matrix_html("~~deleted~~")
        assert "<del>deleted</del>" in html

    def test_link(self) -> None:
        _, html = markdown_to_matrix_html("[click](https://example.com)")
        assert '<a href="https://example.com">click</a>' in html

    def test_html_escaping(self) -> None:
        _, html = markdown_to_matrix_html("<script>alert('xss')</script>")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_plain_text_strips_html(self) -> None:
        plain, _ = markdown_to_matrix_html("**bold** and *italic*")
        assert "<" not in plain
        assert "bold" in plain
        assert "italic" in plain

    def test_buttons_stripped(self) -> None:
        plain, html = markdown_to_matrix_html("Choose: [button:OK]")
        assert "[button:" not in html
        assert "[button:" not in plain

    def test_unclosed_code_block(self) -> None:
        text = "```\ncode without closing"
        _, html = markdown_to_matrix_html(text)
        assert "</code></pre>" in html

    def test_empty_input(self) -> None:
        plain, html = markdown_to_matrix_html("")
        assert plain == ""
        assert html == ""
