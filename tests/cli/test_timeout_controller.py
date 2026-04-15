"""Tests for TimeoutController with warnings and activity-based extensions."""

from __future__ import annotations

import asyncio

import pytest

from controlmesh.cli.timeout_controller import (
    TimeoutConfig,
    TimeoutController,
    TimeoutWarning,
)


class TestTimeoutControllerBasic:
    async def test_completes_before_timeout(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=5.0,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )

        async def quick_task() -> str:
            return "done"

        result = await controller.run_with_timeout(quick_task())
        assert result == "done"

    async def test_timeout_fires(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.1,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )

        async def slow_task() -> str:
            await asyncio.sleep(10)
            return "done"

        with pytest.raises(TimeoutError):
            await controller.run_with_timeout(slow_task())


class TestTimeoutWarnings:
    async def test_warning_callback_called(self) -> None:
        warnings_received: list[TimeoutWarning] = []

        async def on_warning(w: TimeoutWarning) -> None:
            warnings_received.append(w)

        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.5,
                warning_intervals=[0.3],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
            on_warning=on_warning,
        )

        async def task() -> str:
            await asyncio.sleep(0.45)
            return "done"

        result = await controller.run_with_timeout(task())
        assert result == "done"
        assert len(warnings_received) >= 1
        assert warnings_received[0].total_seconds == 0.5

    async def test_no_warnings_when_empty_intervals(self) -> None:
        warnings_received: list[TimeoutWarning] = []

        async def on_warning(w: TimeoutWarning) -> None:
            warnings_received.append(w)

        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.3,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
            on_warning=on_warning,
        )

        async def task() -> str:
            await asyncio.sleep(0.1)
            return "done"

        await controller.run_with_timeout(task())
        assert warnings_received == []


class TestActivityExtension:
    async def test_activity_extends_deadline(self) -> None:
        """When activity is recorded, timeout should be extended."""
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.3,
                warning_intervals=[],
                extend_on_activity=True,
                activity_extension=0.3,
                max_extensions=2,
            ),
        )

        async def task_with_activity() -> str:
            await asyncio.sleep(0.2)
            controller.record_activity()
            await asyncio.sleep(0.2)
            controller.record_activity()
            await asyncio.sleep(0.2)
            return "done"

        result = await controller.run_with_timeout(task_with_activity())
        assert result == "done"

    async def test_no_extension_when_disabled(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.2,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0.3,
                max_extensions=2,
            ),
        )

        async def task_with_activity() -> str:
            await asyncio.sleep(0.1)
            controller.record_activity()
            await asyncio.sleep(0.3)
            return "done"

        with pytest.raises(TimeoutError):
            await controller.run_with_timeout(task_with_activity())

    async def test_max_extensions_respected(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=0.15,
                warning_intervals=[],
                extend_on_activity=True,
                activity_extension=0.15,
                max_extensions=1,
            ),
        )

        async def task_with_many_activities() -> str:
            for _ in range(5):
                await asyncio.sleep(0.1)
                controller.record_activity()
            return "done"

        with pytest.raises(TimeoutError):
            await controller.run_with_timeout(task_with_many_activities())

    async def test_record_activity_is_idempotent(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=1.0,
                warning_intervals=[],
                extend_on_activity=True,
                activity_extension=0.5,
                max_extensions=3,
            ),
        )
        # Multiple calls in quick succession should not cause issues.
        for _ in range(100):
            controller.record_activity()


class TestRemainingProperty:
    async def test_remaining_decreases(self) -> None:
        controller = TimeoutController(
            TimeoutConfig(
                timeout_seconds=1.0,
                warning_intervals=[],
                extend_on_activity=False,
                activity_extension=0,
                max_extensions=0,
            ),
        )

        async def check_remaining() -> float:
            await asyncio.sleep(0.1)
            return controller.remaining

        remaining = await controller.run_with_timeout(check_remaining())
        assert remaining < 1.0
