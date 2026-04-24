"""Self-update observer: periodic version check + upgrade execution."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from controlmesh.infra.install import InstallInfo, detect_install_info
from controlmesh.infra.version import (
    VersionInfo,
    _parse_version,
    check_github_release,
    check_latest_version,
    check_pypi,
)

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_S = 3600  # 60 minutes
_INITIAL_DELAY_S = 60  # 1 minute after startup
_VERIFY_DELAYS_S: tuple[float, ...] = (0.15, 0.35, 0.75, 1.5)

VersionCallback = Callable[[VersionInfo], Awaitable[None]]

_UPGRADE_SENTINEL_NAME = "upgrade-sentinel.json"


@dataclass(frozen=True, slots=True)
class InstalledState:
    """Freshly observed installed package state."""

    version: str
    commit_id: str | None = None


@dataclass(frozen=True, slots=True)
class SourceUpgradeStatus:
    """Preflight status for editable/source upgrades."""

    current_version: str
    repo_root: Path | None = None
    current_commit: str | None = None
    branch: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    actionable: bool = False
    message: str = ""
    output: str = ""


class UpdateObserver:
    """Background task that checks the latest public release periodically."""

    def __init__(self, *, notify: VersionCallback) -> None:
        self._notify = notify
        self._task: asyncio.Task[None] | None = None
        self._last_notified: str = ""

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        await asyncio.sleep(_INITIAL_DELAY_S)
        while True:
            try:
                info = await check_latest_version()
                if info and info.update_available and info.latest != self._last_notified:
                    self._last_notified = info.latest
                    await self._notify(info)
            except Exception:
                logger.debug("Update check failed", exc_info=True)
            await asyncio.sleep(_CHECK_INTERVAL_S)


# ---------------------------------------------------------------------------
# Upgrade execution
# ---------------------------------------------------------------------------


def _normalize_target_version(target_version: str | None) -> str | None:
    """Normalize optional target version value for upgrade commands."""
    if target_version is None:
        return None
    normalized = target_version.strip()
    if not normalized or normalized.lower() == "latest":
        return None
    return normalized


def _is_newer_version(candidate: str, current: str) -> bool:
    """Return True when *candidate* is strictly newer than *current*."""
    return _parse_version(candidate) > _parse_version(current)


def _github_ref_for_target(info: InstallInfo, target_version: str | None) -> str:
    """Resolve the Git ref that a GitHub direct install should track."""
    if info.requested_revision:
        return info.requested_revision
    if target_version:
        return f"v{target_version}"
    return "main"


def _build_package_spec(info: InstallInfo, target_version: str | None) -> str:
    """Build the package spec for the active installation source."""
    if info.source == "github" and info.url:
        if info.vcs == "git":
            url = info.url if info.url.startswith("git+") else f"git+{info.url}"
            return f"controlmesh @ {url}@{_github_ref_for_target(info, target_version)}"
        return info.url

    return f"controlmesh=={target_version}" if target_version else "controlmesh"


def _build_upgrade_command(
    *,
    mode: str,
    package_spec: str,
    target_version: str | None,
    force_reinstall: bool,
) -> list[str]:
    """Build provider-specific upgrade command."""
    if mode == "pipx":
        # On non-Windows, prefer `pipx upgrade` for plain upgrades (no pin).
        if (
            package_spec == "controlmesh"
            and target_version is None
            and not force_reinstall
            and sys.platform != "win32"
        ):
            return ["pipx", "upgrade", "--force", "controlmesh"]
        # `pipx runpip` upgrades inside the venv.  On Windows this is
        # required because `pipx upgrade` tries to overwrite the global
        # controlmesh.exe which the running process holds locked.
        cmd = ["pipx", "runpip", "controlmesh", "install", "--upgrade", "--no-cache-dir"]
        if force_reinstall:
            cmd.append("--force-reinstall")
        cmd.append(package_spec)
        return cmd

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir"]
    if force_reinstall:
        cmd.append("--force-reinstall")
    cmd.append(package_spec)
    return cmd


async def _run_upgrade_command(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: str | None = None,
) -> tuple[bool, str]:
    """Execute one upgrade command and return ``(success, output)``."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace") if stdout else ""
    return (proc.returncode or 0) == 0, output


def _source_repo_hint(install_info: InstallInfo) -> Path | None:
    """Return the editable/source checkout path hint from install metadata."""
    if install_info.local_path:
        return Path(install_info.local_path).expanduser()
    return None


async def _resolve_source_repo_root(repo_hint: Path) -> tuple[Path | None, str]:
    """Resolve the canonical git toplevel for a source checkout."""
    if shutil.which("git") is None:
        return None, "Source upgrade requires `git` in PATH."

    env = dict(os.environ)
    ok, output = await _run_upgrade_command(
        ["git", "-C", str(repo_hint), "rev-parse", "--show-toplevel"],
        env=env,
    )
    if not ok:
        message = output.strip() or f"No git repository found at `{repo_hint}`."
        return None, message
    root_text = output.strip().splitlines()[-1].strip()
    if not root_text:
        return None, f"Could not resolve git repository root from `{repo_hint}`."
    return Path(root_text), output


async def _git_output(repo_root: Path, *args: str) -> tuple[bool, str]:
    """Run a git command inside *repo_root* and capture combined output."""
    env = dict(os.environ)
    return await _run_upgrade_command(["git", "-C", str(repo_root), *args], env=env)


async def _get_git_head(repo_root: Path) -> str | None:
    """Read the current HEAD commit for the source checkout."""
    ok, output = await _git_output(repo_root, "rev-parse", "HEAD")
    if not ok:
        return None
    head = output.strip().splitlines()[-1].strip()
    return head or None


async def _read_source_state(current_version: str, repo_root: Path) -> InstalledState:
    """Read installed version and source commit for editable installs."""
    version = await get_installed_version()
    commit_id = await _get_git_head(repo_root)
    return InstalledState(version=version or current_version, commit_id=commit_id)


async def _wait_for_source_state_change(
    previous: InstalledState,
    repo_root: Path,
) -> InstalledState:
    """Wait briefly for source checkout state to settle after an editable refresh."""
    installed = await _read_source_state(previous.version, repo_root)
    if _state_changed(installed, previous):
        return installed
    for delay in _VERIFY_DELAYS_S:
        await asyncio.sleep(delay)
        installed = await _read_source_state(previous.version, repo_root)
        if _state_changed(installed, previous):
            return installed
    return installed


def _short_commit(commit_id: str | None) -> str:
    """Return a compact commit id for user-facing status text."""
    if not commit_id:
        return "unknown"
    return commit_id[:7]


async def check_source_upgrade_status(
    *,
    current_version: str,
    install_info: InstallInfo | None = None,
    fetch: bool = True,
) -> SourceUpgradeStatus:
    """Inspect whether an editable/source install has a safe fast-forward path."""
    active_install = install_info or detect_install_info()
    repo_hint = _source_repo_hint(active_install)
    if repo_hint is None:
        message = "Could not determine the source checkout for this editable install."
        return SourceUpgradeStatus(
            current_version=current_version,
            message=message,
            output=message,
        )

    repo_root, repo_output = await _resolve_source_repo_root(repo_hint)
    if repo_root is None:
        message = repo_output.strip() or "Could not resolve source checkout."
        return SourceUpgradeStatus(
            current_version=current_version,
            message=message,
            output=message,
        )

    current_state = await _read_source_state(current_version, repo_root)
    current_commit = current_state.commit_id
    if current_commit is None:
        message = "Could not determine current git commit."
        output = _combine_outputs([repo_output, message])
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            message=message,
            output=output,
        )

    outputs = [repo_output]

    ok, branch_output = await _git_output(repo_root, "symbolic-ref", "--short", "HEAD")
    outputs.append(branch_output)
    if not ok:
        message = "Refusing source upgrade: repository is in detached HEAD state."
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )
    branch = branch_output.strip().splitlines()[-1].strip()

    ok, status_output = await _git_output(repo_root, "status", "--porcelain")
    outputs.append(status_output)
    if not ok:
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            message="Failed to read git worktree status.",
            output=_combine_outputs(outputs),
        )
    dirty = [line for line in status_output.splitlines() if line.strip()]
    if dirty:
        message = "Refusing source upgrade: worktree has uncommitted or untracked changes."
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            message=message,
            output=_combine_outputs([*outputs, message, "\n".join(dirty)]),
        )

    if fetch:
        ok, fetch_output = await _git_output(repo_root, "fetch", "--prune", "--tags")
        outputs.append(fetch_output)
        if not ok:
            return SourceUpgradeStatus(
                current_version=current_version,
                repo_root=repo_root,
                current_commit=current_commit,
                branch=branch,
                message="Failed to fetch upstream updates.",
                output=_combine_outputs(outputs),
            )

    ok, upstream_output = await _git_output(
        repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
    )
    outputs.append(upstream_output)
    if not ok:
        message = (
            f"Refusing source upgrade: branch `{branch or 'HEAD'}` has no upstream tracking branch."
        )
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )
    upstream = upstream_output.strip().splitlines()[-1].strip()

    ok, count_output = await _git_output(repo_root, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    outputs.append(count_output)
    if not ok:
        message = "Could not determine local/upstream commit distance."
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            upstream=upstream,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )

    try:
        ahead_text, behind_text = count_output.strip().split()
        ahead = int(ahead_text)
        behind = int(behind_text)
    except (TypeError, ValueError):
        message = "Could not determine local/upstream commit distance."
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            upstream=upstream,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )

    if ahead > 0 and behind > 0:
        message = (
            "Refusing source upgrade: local branch has diverged from upstream "
            f"(`{branch}` vs `{upstream}`, ahead {ahead}, behind {behind})."
        )
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )

    if ahead > 0:
        message = (
            "Refusing source upgrade: local branch is ahead of upstream "
            f"(`{branch}` vs `{upstream}`, ahead {ahead})."
        )
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )

    if behind == 0:
        message = f"Source checkout already matches upstream (`{branch}` -> `{upstream}`)."
        return SourceUpgradeStatus(
            current_version=current_version,
            repo_root=repo_root,
            current_commit=current_commit,
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            message=message,
            output=_combine_outputs([*outputs, message]),
        )

    message = (
        f"Source checkout can fast-forward `{branch}` -> `{upstream}` "
        f"({behind} commit{'s' if behind != 1 else ''} behind)."
    )
    return SourceUpgradeStatus(
        current_version=current_version,
        repo_root=repo_root,
        current_commit=current_commit,
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        actionable=True,
        message=message,
        output=_combine_outputs([*outputs, message]),
    )


async def _perform_source_upgrade_pipeline(
    *,
    current_version: str,
    install_info: InstallInfo,
) -> tuple[bool, str, str]:
    """Update an editable/source install via git + editable reinstall."""
    status = await check_source_upgrade_status(current_version=current_version, install_info=install_info)
    if not status.actionable or status.repo_root is None or status.current_commit is None:
        return False, current_version, status.output or status.message

    previous_state = InstalledState(version=current_version, commit_id=status.current_commit)
    outputs = [status.output]

    repo_root = status.repo_root
    ok, pull_output = await _git_output(repo_root, "pull", "--ff-only")
    outputs.append(pull_output)
    if not ok:
        return False, current_version, _combine_outputs(outputs)

    env = {**os.environ, "PIP_NO_CACHE_DIR": "1"}
    ok, reinstall_output = await _run_upgrade_command(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            "-e",
            str(repo_root),
        ],
        env=env,
        cwd=str(repo_root),
    )
    outputs.append(reinstall_output)
    if not ok:
        return (
            False,
            current_version,
            _combine_outputs(
                [
                    *outputs,
                    (
                        "Git fast-forward succeeded, but editable dependency refresh failed. "
                        f"Review the pip output and rerun `python -m pip install -e {repo_root}`."
                    ),
                ]
            ),
        )

    installed_state = await _wait_for_source_state_change(previous_state, repo_root)
    if _state_changed(installed_state, previous_state):
        return True, installed_state.version, _combine_outputs(outputs)

    return (
        False,
        current_version,
        _combine_outputs(
            [
                *outputs,
                "Source upgrade completed commands but no new commit or installed state could be verified.",
            ]
        ),
    )


async def _perform_upgrade_impl(
    *,
    target_version: str | None,
    force_reinstall: bool,
) -> tuple[bool, str]:
    """Run upgrade command with optional target pin and reinstall mode.

    Refuses to upgrade dev/editable installs -- those should use ``git pull``.
    Sets ``PIP_NO_CACHE_DIR=1`` to avoid stale local wheel cache.
    """
    install_info = detect_install_info()
    if install_info.mode == "dev":
        return False, "Running from source (editable install). Use `git pull` to update."

    normalized_target = _normalize_target_version(target_version)
    env = {**os.environ, "PIP_NO_CACHE_DIR": "1"}
    package_spec = _build_package_spec(install_info, normalized_target)
    cmd = _build_upgrade_command(
        mode=install_info.mode,
        package_spec=package_spec,
        target_version=normalized_target,
        force_reinstall=force_reinstall,
    )
    ok, output = await _run_upgrade_command(cmd, env=env)
    if ok:
        return True, output

    # Older pipx setups may not support/handle runpip as expected.
    # Fall back to plain pipx upgrade so we keep behavior resilient.
    # On Windows the fallback would hit the same PermissionError on the
    # locked exe, so skip it there.
    if (
        install_info.mode == "pipx"
        and install_info.source == "pypi"
        and normalized_target is not None
        and sys.platform != "win32"
    ):
        fallback_cmd = ["pipx", "upgrade", "--force", "controlmesh"]
        fb_ok, fb_output = await _run_upgrade_command(fallback_cmd, env=env)
        combined = "\n\n".join(part for part in (output.strip(), fb_output.strip()) if part)
        return fb_ok, combined

    return False, output


async def get_installed_version() -> str:
    """Read the installed package version in a fresh subprocess.

    The running process caches module metadata, so we spawn a child to
    reliably read the version that is actually on disk after an upgrade.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from importlib.metadata import version; print(version('controlmesh'))",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode().strip() if stdout else "0.0.0"


async def get_installed_state() -> InstalledState:
    """Read installed package version and VCS commit in a fresh subprocess."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        (
            "import json; "
            "from importlib.metadata import distribution, version; "
            "commit_id = None; "
            "dist = distribution('controlmesh'); "
            "direct_url = dist.read_text('direct_url.json'); "
            "data = json.loads(direct_url) if direct_url else {}; "
            "vcs = data.get('vcs_info') or {}; "
            "commit_id = vcs.get('commit_id'); "
            "print(json.dumps({'version': version('controlmesh'), 'commit_id': commit_id}))"
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if not stdout:
        return InstalledState(version="0.0.0")
    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return InstalledState(version="0.0.0")
    version = data.get("version")
    commit_id = data.get("commit_id")
    return InstalledState(
        version=version if isinstance(version, str) else "0.0.0",
        commit_id=commit_id if isinstance(commit_id, str) else None,
    )


def _state_changed(current: InstalledState, previous: InstalledState) -> bool:
    """Return True when the installed package identity changed."""
    return (
        current.version != previous.version
        or (
            previous.commit_id is not None
            and current.commit_id is not None
            and current.commit_id != previous.commit_id
        )
    )


async def _wait_for_install_change(previous: InstalledState) -> InstalledState:
    """Wait briefly for package metadata to settle, then return installed state."""
    installed = await get_installed_state()
    if _state_changed(installed, previous):
        return installed
    for delay in _VERIFY_DELAYS_S:
        await asyncio.sleep(delay)
        installed = await get_installed_state()
        if _state_changed(installed, previous):
            return installed
    return installed


def _combine_outputs(outputs: list[str]) -> str:
    """Combine command outputs into one readable block."""
    parts = [part.strip() for part in outputs if part and part.strip()]
    return "\n\n".join(parts)


async def _append_missing_distribution_guidance(
    outputs: list[str],
    *,
    current_version: str,
) -> list[str]:
    """Append missing-distribution guidance when pip cannot find a target version."""
    combined = _combine_outputs(outputs)
    if "No matching distribution found" not in combined:
        return outputs
    return [*outputs, await _missing_distribution_guidance(current_version)]


async def _missing_distribution_guidance(current_version: str) -> str:
    """Explain whether a missing distribution is propagation or a broken release."""
    pypi = await check_pypi(fresh=True)
    github = await check_github_release(fresh=True)
    if pypi is None and github is not None and _is_newer_version(github.latest, current_version):
        return (
            f"GitHub already shows release {github.latest}, but PyPI has no installable "
            "`controlmesh` distribution yet. Treat this as a failed or incomplete "
            "publish workflow, not a mirror-delay success."
        )
    return "The new version may not have propagated to all PyPI mirrors yet. Please try again in a few minutes."


async def _resolve_retry_target(
    current_version: str,
    target_version: str | None,
    install_info: InstallInfo,
) -> str | None:
    """Resolve retry target version for forced second attempt."""
    if install_info.source == "github":
        return target_version if target_version is not None else "latest"

    normalized_target = _normalize_target_version(target_version)
    if normalized_target and _is_newer_version(normalized_target, current_version):
        return normalized_target

    info = await check_latest_version(fresh=True)
    if info and _is_newer_version(info.latest, current_version):
        return info.latest
    return None


async def perform_upgrade_pipeline(
    *,
    current_version: str,
    target_version: str | None = None,
) -> tuple[bool, str, str]:
    """Upgrade and verify with one deterministic retry path.

    Strategy:
    1. Run normal upgrade command.
    2. Verify installed version with short settle polling.
    3. If unchanged (or initial attempt fails), resolve a retry target and
       perform one forced reinstall attempt pinned to that version.

    Returns:
        ``(changed, installed_version, output)``
    """
    install_info = detect_install_info()
    if install_info.mode == "dev":
        return await _perform_source_upgrade_pipeline(
            current_version=current_version,
            install_info=install_info,
        )

    outputs: list[str] = []
    previous_state = InstalledState(
        version=current_version,
        commit_id=install_info.commit_id if install_info.source == "github" else None,
    )

    _ok, output = await _perform_upgrade_impl(target_version=None, force_reinstall=False)
    outputs.append(output)

    # Always verify version regardless of the command exit code.  On
    # Windows, pipx may report failure (exe file lock) even though the
    # package was upgraded successfully inside the venv.
    installed_state = await _wait_for_install_change(previous_state)
    if _state_changed(installed_state, previous_state):
        return True, installed_state.version, _combine_outputs(outputs)

    retry_target = await _resolve_retry_target(current_version, target_version, install_info)
    if retry_target is None:
        outputs = await _append_missing_distribution_guidance(
            outputs,
            current_version=current_version,
        )
        return False, current_version, _combine_outputs(outputs)

    _retry_ok, retry_output = await _perform_upgrade_impl(
        target_version=retry_target,
        force_reinstall=True,
    )
    outputs.append(retry_output)

    installed_state = await _wait_for_install_change(previous_state)
    if _state_changed(installed_state, previous_state):
        return True, installed_state.version, _combine_outputs(outputs)

    # Detect PyPI CDN propagation delay — the JSON API may announce a
    # version before the package index used by pip has it available.
    outputs = await _append_missing_distribution_guidance(
        outputs,
        current_version=current_version,
    )

    return False, current_version, _combine_outputs(outputs)


# ---------------------------------------------------------------------------
# Upgrade sentinel (post-restart notification)
# ---------------------------------------------------------------------------


def write_upgrade_sentinel(
    sentinel_dir: Path,
    *,
    chat_id: int,
    old_version: str,
    new_version: str,
    transport: str | None = None,
) -> None:
    """Write sentinel so the bot can notify the user after upgrade restart."""
    from controlmesh.infra.atomic_io import atomic_bytes_save

    path = sentinel_dir / _UPGRADE_SENTINEL_NAME
    payload: dict[str, str | int] = {
        "chat_id": chat_id,
        "old_version": old_version,
        "new_version": new_version,
    }
    if transport:
        payload["transport"] = transport
    content = json.dumps(payload)
    atomic_bytes_save(path, content.encode())


def consume_upgrade_sentinel(
    sentinel_dir: Path,
    *,
    transport: str | None = None,
) -> dict[str, str | int] | None:
    """Read and delete the upgrade sentinel. Returns None if absent."""
    path = sentinel_dir / _UPGRADE_SENTINEL_NAME
    if not path.exists():
        return None
    try:
        data: dict[str, str | int] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read upgrade sentinel")
        path.unlink(missing_ok=True)
        return None
    sentinel_transport = data.get("transport")
    if (
        transport
        and isinstance(sentinel_transport, str)
        and sentinel_transport
        and sentinel_transport != transport
    ):
        return None
    path.unlink(missing_ok=True)
    logger.info(
        "Upgrade sentinel consumed: %s -> %s", data.get("old_version"), data.get("new_version")
    )
    return data
