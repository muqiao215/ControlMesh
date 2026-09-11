"""Regression coverage for independent cron writers, including manual execution."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from controlmesh.cron.guarded_store import CorruptRegistryError
from controlmesh.cron.manager import CronManager
from tests.cron.test_manager import _make_job


@pytest.mark.parametrize("method", ["update_run_status", "update_manual_run_status"])
def test_stale_status_writer_preserves_pause_and_metadata(tmp_path, method):
    path = tmp_path / "jobs.json"
    first = CronManager(jobs_path=path)
    first.add_job(_make_job())
    data = json.loads(path.read_text())
    data["owner"] = "external metadata"
    data["jobs"][0]["pause_reason"] = "user"
    path.write_text(json.dumps(data))
    stale = CronManager(jobs_path=path)
    first.set_enabled("daily", enabled=False)
    getattr(stale, method)("daily", status="success")
    saved = json.loads(path.read_text())
    assert saved["jobs"][0]["enabled"] is False
    assert saved["jobs"][0]["pause_reason"] == "user"
    assert saved["owner"] == "external metadata"


def test_independent_concurrent_adds_do_not_drop_jobs(tmp_path):
    path = tmp_path / "jobs.json"
    managers = [CronManager(jobs_path=path) for _ in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda pair: pair[1].add_job(_make_job(str(pair[0]))), enumerate(managers)))
    assert {row["id"] for row in json.loads(path.read_text())["jobs"]} == {
        str(i) for i in range(20)
    }


def test_stale_writer_does_not_recreate_deleted_job(tmp_path):
    path = tmp_path / "jobs.json"
    a = CronManager(jobs_path=path)
    a.add_job(_make_job())
    b = CronManager(jobs_path=path)
    a.remove_job("daily")
    b.update_manual_run_status("daily", status="success")
    assert json.loads(path.read_text())["jobs"] == []


def test_corrupt_registry_is_never_replaced_by_mutation(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("not json")
    manager = CronManager(jobs_path=path)
    with pytest.raises(CorruptRegistryError):
        manager.add_job(_make_job())
    assert path.read_text() == "not json"


def test_invalid_existing_job_is_not_partially_committed(tmp_path):
    path = tmp_path / "jobs.json"
    original = '{"jobs":[{"id":"broken"}]}'
    path.write_text(original)
    manager = CronManager(jobs_path=path)
    with pytest.raises(KeyError):
        manager.add_job(_make_job())
    assert path.read_text() == original


def test_cron_tool_edit_merges_without_reviving_pause(tmp_path):
    from controlmesh._home_defaults.workspace.tools.cron_tools._shared import (
        load_jobs_strict,
        save_jobs,
    )

    path = tmp_path / "jobs.json"
    manager = CronManager(jobs_path=path)
    manager.add_job(_make_job())
    pending = load_jobs_strict(path)
    pending["jobs"][0]["title"] = "Updated title"
    manager.set_enabled("daily", enabled=False)
    manager.update_manual_run_status("daily", status="success")
    save_jobs(path, pending)
    actual = json.loads(path.read_text())["jobs"][0]
    assert actual["title"] == "Updated title"
    assert actual["enabled"] is False
    assert actual["manual_run_status"] == "success"


def test_cron_tool_conflict_does_not_clobber_newer_edit(tmp_path):
    from controlmesh._home_defaults.workspace.tools.cron_tools._shared import (
        load_jobs_strict,
        save_jobs,
    )

    path = tmp_path / "jobs.json"
    manager = CronManager(jobs_path=path)
    manager.add_job(_make_job())
    first, second = load_jobs_strict(path), load_jobs_strict(path)
    first["jobs"][0]["title"] = "First"
    second["jobs"][0]["title"] = "Second"
    save_jobs(path, first)
    with pytest.raises(ValueError, match="concurrently"):
        save_jobs(path, second)
    assert json.loads(path.read_text())["jobs"][0]["title"] == "First"
