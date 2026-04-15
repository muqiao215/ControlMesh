"""Tests for multiagent/health.py: AgentHealth state machine."""

from __future__ import annotations

import time

from controlmesh.multiagent.health import AgentHealth


class TestAgentHealthStates:
    """Test state transitions on AgentHealth."""

    def test_initial_state_is_stopped(self) -> None:
        h = AgentHealth(name="test")
        assert h.status == "stopped"
        assert h.started_at == 0.0
        assert h.restart_count == 0

    def test_mark_starting(self) -> None:
        h = AgentHealth(name="test")
        h.mark_starting()
        assert h.status == "starting"

    def test_mark_running_sets_started_at_and_resets_restarts(self) -> None:
        h = AgentHealth(name="test")
        h.restart_count = 3
        h.mark_running()
        assert h.status == "running"
        assert h.started_at > 0.0
        assert h.restart_count == 0

    def test_mark_crashed_increments_restart_count(self) -> None:
        h = AgentHealth(name="test")
        h.mark_crashed("boom")
        assert h.status == "crashed"
        assert h.restart_count == 1
        assert h.last_crash_error == "boom"
        assert h.last_crash_time > 0.0

    def test_mark_crashed_accumulates(self) -> None:
        h = AgentHealth(name="test")
        h.mark_crashed("first")
        h.mark_crashed("second")
        h.mark_crashed("third")
        assert h.restart_count == 3
        assert h.last_crash_error == "third"

    def test_mark_stopped_resets_started_at(self) -> None:
        h = AgentHealth(name="test")
        h.mark_running()
        assert h.started_at > 0.0
        h.mark_stopped()
        assert h.status == "stopped"
        assert h.started_at == 0.0

    def test_full_lifecycle(self) -> None:
        """stopped -> starting -> running -> crashed -> running -> stopped."""
        h = AgentHealth(name="lifecycle")
        assert h.status == "stopped"

        h.mark_starting()
        assert h.status == "starting"

        h.mark_running()
        assert h.status == "running"

        h.mark_crashed("error")
        assert h.status == "crashed"
        assert h.restart_count == 1

        h.mark_running()
        assert h.status == "running"
        assert h.restart_count == 0  # reset on mark_running

        h.mark_stopped()
        assert h.status == "stopped"


class TestAgentHealthUptime:
    """Test uptime calculation and formatting."""

    def test_uptime_zero_when_not_running(self) -> None:
        h = AgentHealth(name="test")
        assert h.uptime_seconds == 0.0

    def test_uptime_zero_when_started_at_is_zero(self) -> None:
        h = AgentHealth(name="test", status="running", started_at=0.0)
        assert h.uptime_seconds == 0.0

    def test_uptime_positive_when_running(self) -> None:
        h = AgentHealth(name="test")
        h.mark_running()
        # Should be > 0 (even if tiny)
        assert h.uptime_seconds >= 0.0

    def test_uptime_human_seconds(self) -> None:
        h = AgentHealth(name="test", status="running")
        h.started_at = time.monotonic() - 30
        assert h.uptime_human == "30s"

    def test_uptime_human_minutes(self) -> None:
        h = AgentHealth(name="test", status="running")
        h.started_at = time.monotonic() - 300
        assert h.uptime_human == "5m"

    def test_uptime_human_hours(self) -> None:
        h = AgentHealth(name="test", status="running")
        h.started_at = time.monotonic() - 7200
        assert h.uptime_human == "2.0h"

    def test_uptime_human_days(self) -> None:
        h = AgentHealth(name="test", status="running")
        h.started_at = time.monotonic() - 172800
        assert h.uptime_human == "2.0d"

    def test_uptime_uses_monotonic(self) -> None:
        """Verify uptime is based on time.monotonic(), not wall clock."""
        h = AgentHealth(name="test")
        before = time.monotonic()
        h.mark_running()
        after = time.monotonic()
        assert before <= h.started_at <= after
