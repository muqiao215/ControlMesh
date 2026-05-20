"""Detect how controlmesh was installed and which source it tracks."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from importlib.metadata import distribution
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import controlmesh

logger = logging.getLogger(__name__)

InstallMode = Literal["pipx", "pip", "uv_tool", "dev"]
InstallSource = Literal["pypi", "github", "other", "dev"]

_PACKAGE_NAME = "controlmesh"


@dataclass(frozen=True, slots=True)
class InstallInfo:
    """Describe the current installation mode and source details."""

    mode: InstallMode
    source: InstallSource
    url: str | None = None
    local_path: str | None = None
    vcs: str | None = None
    requested_revision: str | None = None
    commit_id: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeProvenance:
    """Describe where the live runtime imported controlmesh from."""

    install_info: InstallInfo
    imported_version: str
    installed_version: str
    imported_file: str
    executable: str
    sys_prefix: str
    cwd: str
    pythonpath: str
    matches_expected: bool
    path_matches_expected: bool
    version_matches_expected: bool
    reason: str = ""


def _base_install_mode() -> Literal["pipx", "pip", "uv_tool"]:
    """Return the non-dev runtime mode based on the current interpreter prefix."""
    if "/uv/tools/" in sys.prefix or "\\uv\\tools\\" in sys.prefix:
        return "uv_tool"
    return "pipx" if "pipx" in sys.prefix else "pip"


def _is_github_url(url: str) -> bool:
    return "github.com" in url.lower()


def _local_path_from_url(url: str | None) -> str | None:
    """Convert a ``file://`` URL to a filesystem path when possible."""
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None

    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc != "localhost":
        path = f"//{parsed.netloc}{path}"
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path or None


def _source_checkout_hint() -> str | None:
    """Best-effort source checkout path for source/dev runs without metadata."""
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists():
        return str(root)
    return None


def _fallback_install_info(base_mode: Literal["pipx", "pip", "uv_tool"]) -> InstallInfo:
    if base_mode == "pipx":
        return InstallInfo(mode="pipx", source="pypi")
    if base_mode == "uv_tool":
        return InstallInfo(mode="uv_tool", source="pypi")
    return InstallInfo(mode="dev", source="dev", local_path=_source_checkout_hint())


def _install_info_from_direct_url(
    base_mode: Literal["pipx", "pip", "uv_tool"],
    direct_url_text: str,
) -> InstallInfo:
    url_info = json.loads(direct_url_text)
    if url_info.get("dir_info", {}).get("editable", False):
        url = url_info.get("url")
        local_path = _local_path_from_url(url) if isinstance(url, str) else None
        return InstallInfo(
            mode="dev",
            source="dev",
            url=url if isinstance(url, str) else None,
            local_path=local_path,
        )

    url = url_info.get("url")
    vcs_info = url_info.get("vcs_info", {})
    requested_revision = vcs_info.get("requested_revision")
    commit_id = vcs_info.get("commit_id")
    vcs = vcs_info.get("vcs")
    if isinstance(url, str) and _is_github_url(url):
        return InstallInfo(
            mode=base_mode,
            source="github",
            url=url,
            local_path=_local_path_from_url(url),
            vcs=vcs if isinstance(vcs, str) else None,
            requested_revision=requested_revision if isinstance(requested_revision, str) else None,
            commit_id=commit_id if isinstance(commit_id, str) else None,
        )
    return InstallInfo(
        mode=base_mode,
        source="other",
        url=url if isinstance(url, str) else None,
        local_path=_local_path_from_url(url) if isinstance(url, str) else None,
    )


def detect_install_info() -> InstallInfo:
    """Detect installation method and upstream source at runtime."""
    base_mode = _base_install_mode()

    try:
        dist = distribution(_PACKAGE_NAME)
        direct_url_text = dist.read_text("direct_url.json")
        if not direct_url_text:
            return InstallInfo(mode=base_mode, source="pypi")
        return _install_info_from_direct_url(base_mode, direct_url_text)
    except Exception:
        return _fallback_install_info(base_mode)


def detect_install_mode() -> InstallMode:
    """Detect installation method at runtime.

    Returns:
        ``"pipx"`` -- installed via ``pipx install controlmesh``
        ``"pip"``  -- installed via ``pip install controlmesh`` (from PyPI)
        ``"dev"``  -- editable install (``pip install -e .``) or running from source
    """
    return detect_install_info().mode


def is_upgradeable() -> bool:
    """Return True if the bot can self-upgrade (pipx or pip, not dev)."""
    return detect_install_mode() != "dev"


def _normalize_path(value: str | None) -> Path | None:
    if not value:
        return None
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return None


def _installed_distribution_root() -> Path | None:
    """Return the installed distribution root for packaged installs."""
    try:
        dist = distribution(_PACKAGE_NAME)
        return Path(dist.locate_file("")).resolve()
    except Exception:
        return None


def detect_runtime_provenance() -> RuntimeProvenance:
    """Inspect the active runtime import location against install expectations."""
    info = detect_install_info()
    imported_file = str(Path(controlmesh.__file__).resolve())
    imported_version = getattr(controlmesh, "__version__", "0.0.0")
    installed_version = sys.modules.get("controlmesh.infra.version")
    del installed_version  # avoid circular helper import at module import time

    from controlmesh.infra.version import get_current_version

    current_version = get_current_version()
    executable = str(Path(sys.executable).resolve())
    sys_prefix = str(Path(sys.prefix).resolve())
    cwd = str(Path.cwd().resolve())
    pythonpath = os.environ.get("PYTHONPATH", "")

    matches_expected = True
    path_matches_expected = True
    version_matches_expected = True
    reasons: list[str] = []

    if info.mode != "dev":
        expected_root = _installed_distribution_root()
        imported_path = Path(imported_file)
        if expected_root is not None and expected_root not in imported_path.parents:
            matches_expected = False
            path_matches_expected = False
            reasons.append(f"imported module is outside expected runtime root {expected_root}")
        if imported_version != current_version:
            matches_expected = False
            version_matches_expected = False
            reasons.append(
                f"imported version {imported_version} does not match installed package version {current_version}"
            )

    return RuntimeProvenance(
        install_info=info,
        imported_version=imported_version,
        installed_version=current_version,
        imported_file=imported_file,
        executable=executable,
        sys_prefix=sys_prefix,
        cwd=cwd,
        pythonpath=pythonpath,
        matches_expected=matches_expected,
        path_matches_expected=path_matches_expected,
        version_matches_expected=version_matches_expected,
        reason="; ".join(reasons),
    )
