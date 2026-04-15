"""Tests for shared selector utilities."""

from __future__ import annotations

from controlmesh.orchestrator.selectors.utils import format_age


class TestFormatAge:
    def test_zero(self) -> None:
        assert format_age(0) == "0s"

    def test_seconds(self) -> None:
        assert format_age(45) == "45s"

    def test_just_under_minute(self) -> None:
        assert format_age(59) == "59s"

    def test_boundary_60s(self) -> None:
        assert format_age(60) == "1m"

    def test_minutes(self) -> None:
        assert format_age(150) == "2m"

    def test_just_under_hour(self) -> None:
        assert format_age(3599) == "59m"

    def test_boundary_3600s(self) -> None:
        assert format_age(3600) == "1h"

    def test_hours(self) -> None:
        assert format_age(7200) == "2h"

    def test_just_under_day(self) -> None:
        assert format_age(86399) == "23h"

    def test_boundary_86400s(self) -> None:
        assert format_age(86400) == "1d"

    def test_days(self) -> None:
        assert format_age(172800) == "2d"
