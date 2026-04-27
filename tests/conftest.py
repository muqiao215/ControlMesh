"""Shared test fixtures."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from controlmesh.i18n import init as init_i18n


@pytest.fixture(autouse=True)
def _reset_i18n_language() -> object:
    """Keep global i18n state from leaking between tests."""
    init_i18n("en")
    yield
    init_i18n("en")


@pytest.fixture(autouse=True)
def _no_real_process_signals() -> object:
    """Globally prevent tests from sending real signals to system processes.

    Multiple modules import process_tree helpers that send real OS signals.
    Mock processes carry arbitrary PIDs (e.g. 1, 10) that correspond to real
    system processes — sending signals to them crashes the desktop session.
    """
    with (
        patch(
            "controlmesh.cli.process_registry.terminate_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.cli.process_registry.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.cli.process_registry.interrupt_process",
            return_value=None,
        ),
        patch(
            "controlmesh.cli.executor.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.cli.gemini_provider.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.cron.execution.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.infra.pidlock.terminate_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.infra.pidlock.force_kill_process_tree",
            return_value=None,
        ),
        patch(
            "controlmesh.infra.pidlock.list_process_descendants",
            return_value=[],
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_real_service_management() -> object:
    """Prevent tests from stopping/starting the real systemd service.

    ``lifecycle.stop_bot()`` calls ``_stop_service_if_running()`` which runs
    ``systemctl --user stop controlmesh.service`` — killing the live service on any
    machine where controlmesh is installed and running.
    """
    with patch(
        "controlmesh.cli_commands.lifecycle._stop_service_if_running",
    ):
        yield
