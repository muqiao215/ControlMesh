"""Real observer ownership with fake execution; never starts a provider."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from controlmesh.cron.observer import _ScheduledJob
from tests.cron.test_observer import (
    _make_job,
    _make_manager,
    _make_observer,
    _make_paths,
    _write_jobs,
)


@pytest.mark.asyncio
async def test_repeated_reschedule_keeps_executing_handle_and_stop_cancels_it(tmp_path):
    paths = _make_paths(tmp_path)
    manager = _make_manager(paths)
    manager.add_job(_make_job("running"))
    observer = _make_observer(paths, manager)
    # Isolate timer ownership from the independently tested filesystem poller.
    with patch.object(observer._watcher, "update_mtime", new_callable=AsyncMock):
        await observer.start()
    original = observer._scheduled["running"]
    observer._executing.add("running")
    with patch.object(observer._watcher, "update_mtime", new_callable=AsyncMock):
        for _ in range(3):
            await observer._reschedule_all()
            assert observer._scheduled["running"] is original
    await observer.stop()
    assert original.cancelled()


@pytest.mark.asyncio
async def test_completion_uses_latest_config_not_timer_snapshot(tmp_path):
    paths = _make_paths(tmp_path)
    manager = _make_manager(paths)
    manager.add_job(_make_job("job"))
    observer = _make_observer(paths, manager)
    observer._running = True
    old = _ScheduledJob("job", "0 9 * * *", "old", "old-folder", "UTC")

    async def execute(*args):
        _write_jobs(
            paths,
            [
                _make_job(
                    "job",
                    schedule="0 12 * * *",
                    agent_instruction="latest",
                    task_folder="new",
                    timezone="Asia/Shanghai",
                )
            ],
        )

    with (
        patch.object(observer, "_execute_job", side_effect=execute),
        patch.object(observer, "_schedule_job") as schedule,
    ):
        task = asyncio.create_task(observer._run_at(0, old))
        observer._scheduled["job"] = task
        await task
    schedule.assert_called_once_with("job", "0 12 * * *", "latest", "new", "Asia/Shanghai")
    await observer.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pause", "remove"])
async def test_wakeup_rechecks_disk_before_provider_dispatch(tmp_path, change):
    paths = _make_paths(tmp_path)
    manager = _make_manager(paths)
    manager.add_job(_make_job("job"))
    observer = _make_observer(paths, manager)
    observer._running = True
    _write_jobs(paths, [] if change == "remove" else [_make_job("job", enabled=False)])
    with patch.object(observer, "_execute_job", new_callable=AsyncMock) as execute:
        task = asyncio.create_task(
            observer._run_at(0, _ScheduledJob("job", "0 9 * * *", "old", "old", "UTC"))
        )
        observer._scheduled["job"] = task
        await task
        execute.assert_not_awaited()
    await observer.stop()
