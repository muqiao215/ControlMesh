"""Tests for shared service log helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from controlmesh.infra.service_logs import print_journal_service_logs
from tests.infra.conftest import make_completed


class TestPrintJournalServiceLogs:
    @patch("controlmesh.infra.service_logs.subprocess.run")
    def test_falls_back_to_recent_file_logs_when_user_journal_missing(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        (logs_dir / "agent.log").write_text("line1\nline2\n", encoding="utf-8")
        mock_run.return_value = make_completed(0, stdout="No journal files were found.\n")

        console = MagicMock()
        print_journal_service_logs(
            console,
            installed=True,
            service_name="controlmesh",
            fallback_logs_dir=logs_dir,
        )

        assert mock_run.call_count == 1
        console.print.assert_any_call("line1")
        console.print.assert_any_call("line2")

    @patch("controlmesh.infra.service_logs.subprocess.run")
    def test_uses_journalctl_follow_when_probe_succeeds(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        mock_run.side_effect = [
            make_completed(0, stdout="Apr 11 00:00:00 test entry\n"),
            make_completed(0),
        ]

        console = MagicMock()
        print_journal_service_logs(
            console,
            installed=True,
            service_name="controlmesh",
            fallback_logs_dir=logs_dir,
        )

        assert mock_run.call_count == 2
        follow_call = mock_run.call_args_list[1]
        assert follow_call.args[0] == ["journalctl", "--user", "-u", "controlmesh", "-f", "--no-hostname"]
