from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from controlmesh_runtime.contracts import ReviewOutcome
from controlmesh_runtime.worker_state import WorkerStatus

if TYPE_CHECKING:
    import pytest


def test_main_routes_runtime_ingress_to_runtime_command(monkeypatch: pytest.MonkeyPatch) -> None:
    import controlmesh.__main__ as main_mod

    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(sys, "argv", ["controlmesh", "runtime", "run", "--packet-id", "packet-1"])
    monkeypatch.setattr(
        main_mod,
        "_cmd_runtime",
        lambda args: calls.append(("runtime", list(args))),
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "_default_action",
        lambda verbose: calls.append(("default", verbose)),
    )

    main_mod.main()

    assert calls == [("runtime", ["runtime", "run", "--packet-id", "packet-1"])]


def test_runtime_cli_runs_autonomous_loop_from_external_args(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands.runtime import cmd_runtime

    cmd_runtime(
        [
            "runtime",
            "run",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "harness-runtime-cli-ingress-pack",
            "--worker-id",
            "worker-1",
            "--recovery-reason",
            "degraded_runtime",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_id"] == "packet-1"
    assert payload["task_id"] == "task-1"
    assert payload["line"] == "harness-runtime-cli-ingress-pack"
    assert payload["status"] == "completed"
    assert payload["runtime_runnable"] is True
    assert payload["persisted_event_count"] > 0
    assert payload["summary_materialized"] is True
    assert payload["promotion_receipt_id"] is None
    assert payload["final_worker_status"] == WorkerStatus.READY.value
    assert (tmp_path / "controlmesh_state" / "execution_evidence" / "packet-1.jsonl").exists()
    assert (tmp_path / "controlmesh_state" / "summaries" / "task" / "task-1.json").exists()


def test_runtime_cli_runs_controlled_promotion_from_external_args(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands.runtime import cmd_runtime

    _write_line_files(tmp_path, "harness-runtime-cli-ingress-pack")

    cmd_runtime(
        [
            "runtime",
            "run",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "harness-runtime-cli-ingress-pack",
            "--worker-id",
            "worker-1",
            "--recovery-reason",
            "degraded_runtime",
            "--review-outcome",
            ReviewOutcome.PASS_WITH_NOTES.value,
            "--review-reason",
            "controller-approved",
            "--latest-completed",
            "CLI ingress completed one autonomous runtime loop.",
            "--next-action",
            "Hold until the next external packet arrives.",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    progress = (tmp_path / "plans" / "harness-runtime-cli-ingress-pack" / "progress.md").read_text(
        encoding="utf-8"
    )
    assert payload["promotion_receipt_id"]
    assert payload["applied_triggers"] == ["checkpoint", "summary", "promotion"]
    assert "CLI ingress completed one autonomous runtime loop." in progress
    assert "Hold until the next external packet arrives." in progress


def test_runtime_cli_signal_request_summary_appends_control_event(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands.runtime import cmd_runtime

    cmd_runtime(
        [
            "runtime",
            "signal",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "demo-line",
            "--plan-id",
            "plan-1",
            "--action",
            "request_summary",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["action"] == "request_summary"


def test_runtime_cli_query_latest_summary_reads_current_snapshots(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands.runtime import cmd_runtime

    cmd_runtime(
        [
            "runtime",
            "run",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "demo-line",
            "--worker-id",
            "worker-1",
            "--recovery-reason",
            "degraded_runtime",
        ]
    )
    run_payload = json.loads(capsys.readouterr().out)

    cmd_runtime(
        [
            "runtime",
            "query",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "demo-line",
            "--plan-id",
            run_payload["plan_id"],
            "--action",
            "latest_summary",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_summary_id"]
    assert payload["line_summary_id"]


def test_runtime_cli_update_promote_runs_controller_reconcile(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from controlmesh.cli_commands.runtime import cmd_runtime

    _write_line_files(tmp_path, "demo-line")
    cmd_runtime(
        [
            "runtime",
            "run",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "demo-line",
            "--worker-id",
            "worker-1",
            "--recovery-reason",
            "degraded_runtime",
        ]
    )
    run_payload = json.loads(capsys.readouterr().out)

    cmd_runtime(
        [
            "runtime",
            "update",
            "--root",
            str(tmp_path),
            "--packet-id",
            "packet-1",
            "--task-id",
            "task-1",
            "--line",
            "demo-line",
            "--plan-id",
            run_payload["plan_id"],
            "--action",
            "promote",
            "--review-outcome",
            ReviewOutcome.PASS_WITH_NOTES.value,
            "--review-reason",
            "controller-approved",
            "--latest-completed",
            "Update promote completed.",
            "--next-action",
            "Hold line closed.",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    progress = (tmp_path / "plans" / "demo-line" / "progress.md").read_text(encoding="utf-8")
    assert payload["ok"] is True
    assert payload["reason"] == "written"
    assert payload["receipt_id"]
    assert "Update promote completed." in progress


def _write_line_files(root: Path, line: str) -> None:
    line_dir = root / "plans" / line
    line_dir.mkdir(parents=True)
    (line_dir / "task_plan.md").write_text(
        "# Current Goal\nInitial goal\n\n# Current Status\nactive\n\n# Ready Queue\n1. continue\n",
        encoding="utf-8",
    )
    (line_dir / "progress.md").write_text(
        "# Latest Completed\nNone\n\n"
        "# Current State\nactive\n\n"
        "# Next Action\nContinue\n\n"
        "# Latest Checkpoint\ncheckpoint-initial\n\n"
        "# Notes\nHuman note stays.\n",
        encoding="utf-8",
    )
