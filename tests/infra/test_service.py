"""Tests for platform-dispatching service facade (infra/service.py)."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from controlmesh.infra import service

if TYPE_CHECKING:
    import pytest


def _reload_for_platform(platform: str) -> str:
    original = sys.platform
    try:
        sys.platform = platform
        mod = importlib.reload(service)
        return mod._backend.__name__
    finally:
        sys.platform = original
        importlib.reload(service)


def test_dispatch_imports_windows_backend() -> None:
    backend_name = _reload_for_platform("win32")
    assert backend_name.endswith("service_windows")


def test_dispatch_imports_macos_backend() -> None:
    backend_name = _reload_for_platform("darwin")
    assert backend_name.endswith("service_macos")


def test_dispatch_imports_linux_backend() -> None:
    backend_name = _reload_for_platform("linux")
    assert backend_name.endswith("service_linux")


def test_facade_delegates_all_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = SimpleNamespace(
        is_service_available=MagicMock(return_value=True),
        is_service_installed=MagicMock(return_value=True),
        is_service_running=MagicMock(return_value=False),
        install_service=MagicMock(return_value=True),
        uninstall_service=MagicMock(return_value=True),
        start_service=MagicMock(),
        stop_service=MagicMock(),
        print_service_status=MagicMock(),
        print_service_logs=MagicMock(),
    )
    monkeypatch.setattr(service, "_backend", backend, raising=True)

    console = MagicMock()
    assert service.is_service_available() is True
    assert service.is_service_installed() is True
    assert service.is_service_running() is False
    assert service.install_service(console) is True
    assert service.uninstall_service(console) is True
    service.start_service(console)
    service.stop_service(console)
    service.print_service_status(console)
    service.print_service_logs(console)

    backend.is_service_available.assert_called_once_with()
    backend.is_service_installed.assert_called_once_with()
    backend.is_service_running.assert_called_once_with()
    backend.install_service.assert_called_once_with(console)
    backend.uninstall_service.assert_called_once_with(console)
    backend.start_service.assert_called_once_with(console)
    backend.stop_service.assert_called_once_with(console)
    backend.print_service_status.assert_called_once_with(console)
    backend.print_service_logs.assert_called_once_with(console)
