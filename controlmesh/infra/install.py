"""Detect how controlmesh was installed and which source it tracks."""

from __future__ import annotations

import json
import contextlib
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import distribution
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import controlmesh

from controlmesh.infra.json_store import atomic_json_save, load_json
from controlmesh.workspace.paths import resolve_paths

logger = logging.getLogger(__name__)

InstallMode = Literal["pipx", "pip", "uv_tool", "dev"]
InstallSource = Literal["pypi", "github", "other", "dev"]
RuntimeKind = Literal[
    "official-package",
    "hotfix-package",
    "source-direct",
    "editable-install",
    "unknown",
]

_PACKAGE_NAME = "controlmesh"
_HOTFIX_MANIFEST_NAME = "hotfix-manifest.json"


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


@dataclass(frozen=True, slots=True)
class HotfixManifest:
    """Describe a packaged hotfix built from a local source checkout."""

    kind: str
    base_version: str
    hotfix_version: str
    source_path: str
    git_sha: str | None = None
    dirty: bool = False
    patch_file: str | None = None
    installed_by: str | None = None
    installed_at: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeClassification:
    """Resolved runtime packaging state for status and upgrade logic."""

    kind: RuntimeKind
    install_info: InstallInfo
    provenance: RuntimeProvenance
    manager: Literal["pipx", "pip", "uv_tool"]
    base_version: str
    source_path: str | None = None
    hotfix_version: str | None = None
    manifest: HotfixManifest | None = None


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


def _runtime_manager() -> Literal["pipx", "pip", "uv_tool"]:
    """Infer the package manager that owns the current interpreter prefix."""
    return _base_install_mode()


def _strip_local_version(version: str) -> str:
    """Drop any PEP 440 local-version suffix from *version*."""
    return version.split("+", 1)[0]


def hotfix_manifest_path() -> Path:
    """Return the canonical packaged-hotfix manifest path."""
    return resolve_paths().runtime_dir / _HOTFIX_MANIFEST_NAME


def hotfix_artifacts_dir() -> Path:
    """Return the directory used to persist hotfix artifacts."""
    return resolve_paths().runtime_dir / "hotfixes"


def load_hotfix_manifest() -> HotfixManifest | None:
    """Load the hotfix manifest if present and structurally valid."""
    raw = load_json(hotfix_manifest_path())
    if not isinstance(raw, dict):
        return None
    if raw.get("kind") != "controlmesh-hotfix":
        return None
    try:
        return HotfixManifest(
            kind=str(raw["kind"]),
            base_version=str(raw["base_version"]),
            hotfix_version=str(raw["hotfix_version"]),
            source_path=str(raw["source_path"]),
            git_sha=str(raw["git_sha"]) if raw.get("git_sha") else None,
            dirty=bool(raw.get("dirty", False)),
            patch_file=str(raw["patch_file"]) if raw.get("patch_file") else None,
            installed_by=str(raw["installed_by"]) if raw.get("installed_by") else None,
            installed_at=str(raw["installed_at"]) if raw.get("installed_at") else None,
        )
    except KeyError:
        return None


def save_hotfix_manifest(manifest: HotfixManifest) -> None:
    """Persist the hotfix manifest atomically."""
    payload = {
        "kind": manifest.kind,
        "base_version": manifest.base_version,
        "hotfix_version": manifest.hotfix_version,
        "source_path": manifest.source_path,
        "git_sha": manifest.git_sha,
        "dirty": manifest.dirty,
        "patch_file": manifest.patch_file,
        "installed_by": manifest.installed_by,
        "installed_at": manifest.installed_at or datetime.now(UTC).isoformat(),
    }
    atomic_json_save(hotfix_manifest_path(), payload)


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
    """Return True if the bot can self-upgrade or seal a source hotfix."""
    return True


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


def _path_within(parent: Path | None, child: Path | None) -> bool:
    if parent is None or child is None:
        return False
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _source_root_from_imported_file(imported_file: str) -> Path | None:
    try:
        path = Path(imported_file).resolve()
    except OSError:
        return None
    if path.name != "__init__.py":
        return None
    package_dir = path.parent
    repo_root = package_dir.parent
    if package_dir.name != "controlmesh":
        return None
    if (repo_root / ".git").exists():
        return repo_root
    return None


def _runtime_looks_source_direct(provenance: RuntimeProvenance) -> bool:
    imported_root = _source_root_from_imported_file(provenance.imported_file)
    if imported_root is None:
        return False
    expected_root = _installed_distribution_root()
    if expected_root is not None and _path_within(expected_root, Path(provenance.imported_file)):
        return False
    return True


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


def classify_runtime(
    provenance: RuntimeProvenance | None = None,
    *,
    install_info: InstallInfo | None = None,
) -> RuntimeClassification:
    """Classify the current runtime into packaged, hotfix, or source-direct states."""
    active = provenance or detect_runtime_provenance()
    install_info = install_info or getattr(active, "install_info", None)
    if not isinstance(install_info, InstallInfo):
        install_info = detect_install_info()
    imported_version = getattr(active, "imported_version", getattr(controlmesh, "__version__", "0.0.0"))
    installed_version = getattr(active, "installed_version", imported_version)
    imported_file = getattr(active, "imported_file", str(Path(controlmesh.__file__).resolve()))
    executable = getattr(active, "executable", str(Path(sys.executable).resolve()))
    sys_prefix = getattr(active, "sys_prefix", str(Path(sys.prefix).resolve()))
    cwd = getattr(active, "cwd", str(Path.cwd().resolve()))
    pythonpath = getattr(active, "pythonpath", os.environ.get("PYTHONPATH", ""))
    matches_expected = bool(getattr(active, "matches_expected", True))
    path_matches_expected = bool(getattr(active, "path_matches_expected", matches_expected))
    version_matches_expected = bool(getattr(active, "version_matches_expected", matches_expected))
    reason = getattr(active, "reason", "")
    if isinstance(active, RuntimeProvenance):
        active_provenance = active
    else:
        active_provenance = RuntimeProvenance(
            install_info=install_info,
            imported_version=str(imported_version),
            installed_version=str(installed_version),
            imported_file=str(imported_file),
            executable=str(executable),
            sys_prefix=str(sys_prefix),
            cwd=str(cwd),
            pythonpath=str(pythonpath),
            matches_expected=matches_expected,
            path_matches_expected=path_matches_expected,
            version_matches_expected=version_matches_expected,
            reason=str(reason),
        )
    info = install_info
    manager = _runtime_manager()
    manifest = load_hotfix_manifest()
    base_version = _strip_local_version(active_provenance.installed_version)
    source_path = info.local_path or _source_checkout_hint()
    hotfix_version: str | None = None

    if info.mode == "dev":
        kind: RuntimeKind = "editable-install" if info.url else "source-direct"
        if source_path is None:
            source_root = _source_root_from_imported_file(active_provenance.imported_file)
            source_path = str(source_root) if source_root else None
        return RuntimeClassification(
            kind=kind,
            install_info=info,
            provenance=active_provenance,
            manager=manager,
            base_version=base_version,
            source_path=source_path,
            hotfix_version=None,
            manifest=manifest,
        )

    if "+" in active_provenance.installed_version:
        hotfix_version = active_provenance.installed_version
    elif manifest and manifest.hotfix_version == active_provenance.installed_version:
        hotfix_version = manifest.hotfix_version

    if hotfix_version and path_matches_expected:
        source_path = manifest.source_path if manifest else source_path
        return RuntimeClassification(
            kind="hotfix-package",
            install_info=info,
            provenance=active_provenance,
            manager=manager,
            base_version=_strip_local_version(hotfix_version),
            source_path=source_path,
            hotfix_version=hotfix_version,
            manifest=manifest,
        )

    if matches_expected:
        return RuntimeClassification(
            kind="official-package",
            install_info=info,
            provenance=active_provenance,
            manager=manager,
            base_version=base_version,
            source_path=source_path,
            hotfix_version=None,
            manifest=manifest,
        )

    return RuntimeClassification(
        kind="unknown",
        install_info=info,
        provenance=active_provenance,
        manager=manager,
        base_version=base_version,
        source_path=source_path,
        hotfix_version=hotfix_version,
        manifest=manifest,
    )
