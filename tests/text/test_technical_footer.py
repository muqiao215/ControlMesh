"""Tests for format_technical_footer."""

from __future__ import annotations

from controlmesh.text.response_format import format_technical_footer


class TestFormatTechnicalFooter:
    def test_basic_output(self) -> None:
        result = format_technical_footer("opus", 1000, 800, 0.05, 5000.0)
        assert result.startswith("\n---\n")
        assert "Model: opus" in result
        assert "Tokens: 1000 (in: 800, out: 200)" in result
        assert "Cost: $0.0500" in result
        assert "Time: 5.0s" in result

    def test_zero_cost_omitted(self) -> None:
        result = format_technical_footer("sonnet", 500, 400, 0.0, 3000.0)
        assert "Cost" not in result
        assert "Model: sonnet" in result

    def test_no_duration(self) -> None:
        result = format_technical_footer("haiku", 200, 100, 0.01, None)
        assert "Time" not in result
        assert "Model: haiku" in result
        assert "Cost: $0.0100" in result

    def test_zero_tokens(self) -> None:
        result = format_technical_footer("opus", 0, 0, 0.0, None)
        assert "Tokens: 0 (in: 0, out: 0)" in result

    def test_pipe_separator(self) -> None:
        result = format_technical_footer("opus", 100, 50, 0.01, 1000.0)
        assert " | " in result
