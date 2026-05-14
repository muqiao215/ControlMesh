from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import UTC, datetime

import pytest

from controlmesh.config import AgentConfig
from controlmesh.cli.codex_cache import CodexModelCache, _FALLBACK_CODEX_MODELS
from controlmesh.cli.gemini_cache import GeminiModelCache, _FALLBACK_GEMINI_MODELS
from controlmesh.cron.manager import CronJob, CronManager
from controlmesh.workspace.paths import ControlMeshPaths


def _make_paths(tmp_path: Path) -> ControlMeshPaths:
    fw = tmp_path / "fw"
    paths = ControlMeshPaths(
        controlmesh_home=tmp_path / "home",
        home_defaults=fw / "workspace",
        framework_root=fw,
    )
    paths.cron_tasks_dir.mkdir(parents=True, exist_ok=True)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _make_job(job_id: str = "daily", **overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": job_id,
        "title": "Daily Report",
        "description": "Generate report",
        "schedule": "0 9 * * *",
        "task_folder": job_id,
        "agent_instruction": "Do the daily work",
        "enabled": True,
    }
    defaults.update(overrides)
    return CronJob(**defaults)


def _write_job(paths: ControlMeshPaths, job: CronJob) -> None:
    manager = CronManager(jobs_path=paths.cron_jobs_path)
    manager.add_job(job)


def _config(paths: ControlMeshPaths) -> AgentConfig:
    return AgentConfig(controlmesh_home=str(paths.controlmesh_home))


class _ConsoleStub:
    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def print_json(self, text: str) -> None:
        self._sink.append(text)

    def print(self, text: object) -> None:
        self._sink.append(str(text))


def _patch_cache_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load_codex(
        cls,
        _path: Path,
        *,
        force_refresh: bool = False,
    ) -> CodexModelCache:
        del force_refresh
        return CodexModelCache(
            last_updated=datetime.now(UTC).isoformat(),
            models=list(_FALLBACK_CODEX_MODELS),
        )

    async def _load_gemini(
        cls,
        _path: Path,
        *,
        force_refresh: bool = False,
    ) -> GeminiModelCache:
        del force_refresh
        return GeminiModelCache(
            last_updated=datetime.now(UTC).isoformat(),
            models=_FALLBACK_GEMINI_MODELS,
        )

    monkeypatch.setattr(
        CodexModelCache,
        "load_or_refresh",
        classmethod(_load_codex),
    )
    monkeypatch.setattr(
        GeminiModelCache,
        "load_or_refresh",
        classmethod(_load_gemini),
    )


def test_main_routes_cron_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[list[str]] = []

    monkeypatch.setattr(sys, "argv", ["controlmesh", "cron", "list", "--json"])
    monkeypatch.setattr(main_mod, "_cmd_cron", lambda args: calls.append(list(args)), raising=False)

    main_mod.main()

    assert calls == [["cron", "list", "--json"]]


def test_cmd_cron_get_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from controlmesh.cli_commands import cron as cron_cli

    paths = _make_paths(tmp_path)
    _write_job(paths, _make_job("ops-maint", provider="claude", model="sonnet"))
    output: list[str] = []

    monkeypatch.setattr(cron_cli, "load_config", lambda: _config(paths), raising=False)
    _patch_cache_loaders(monkeypatch)
    monkeypatch.setattr(
        cron_cli,
        "_console",
        _ConsoleStub(output),
        raising=False,
    )

    cron_cli.cmd_cron(["cron", "get", "ops-maint", "--json"])

    payload = json.loads(output[0])
    assert payload["id"] == "ops-maint"
    assert payload["provider"] == "claude"
    assert payload["model"] == "sonnet"


def test_cmd_cron_run_dry_run_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from controlmesh.cli_commands import cron as cron_cli

    paths = _make_paths(tmp_path)
    task_dir = paths.cron_tasks_dir / "ops-maint"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "TASK_DESCRIPTION.md").write_text("# Task\n", encoding="utf-8")
    _write_job(paths, _make_job("ops-maint", provider="claude", model="sonnet"))
    output: list[str] = []

    monkeypatch.setattr(cron_cli, "load_config", lambda: _config(paths), raising=False)
    _patch_cache_loaders(monkeypatch)
    monkeypatch.setattr(
        cron_cli,
        "_console",
        _ConsoleStub(output),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc:
        cron_cli.cmd_cron(["cron", "run", "ops-maint", "--dry-run", "--json"])

    assert exc.value.code == 0
    payload = json.loads(output[0])
    assert payload["job_id"] == "ops-maint"
    assert payload["status"] == "dry_run"
    assert payload["manual"] is True
    assert payload["dry_run"] is True


def test_cmd_cron_validate_reports_missing_script(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands import cron as cron_cli

    paths = _make_paths(tmp_path)
    task_dir = paths.cron_tasks_dir / "ops-maint"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "TASK_DESCRIPTION.md").write_text(
        "# Task\n\nRun `scripts/check.sh` before continuing.\n",
        encoding="utf-8",
    )
    _write_job(paths, _make_job("ops-maint"))
    output: list[str] = []

    monkeypatch.setattr(cron_cli, "load_config", lambda: _config(paths), raising=False)
    _patch_cache_loaders(monkeypatch)
    monkeypatch.setattr(
        cron_cli,
        "_console",
        _ConsoleStub(output),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc:
        cron_cli.cmd_cron(["cron", "validate", "ops-maint"])

    assert exc.value.code == 1
    assert "Missing referenced script" in output[0]


def test_cmd_cron_help_mentions_monitor_entry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands import cron as cron_cli

    output: list[str] = []
    paths = _make_paths(tmp_path)
    monkeypatch.setattr(cron_cli, "load_config", lambda: _config(paths), raising=False)
    monkeypatch.setattr(
        cron_cli,
        "_console",
        _ConsoleStub(output),
        raising=False,
    )

    cron_cli.cmd_cron(["cron", "--help"])

    assert "cron_monitor.py" in output[0]
    assert "recurring cron" in output[0]
