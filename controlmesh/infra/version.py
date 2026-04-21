"""Package version checking against PyPI and GitHub Releases."""

from __future__ import annotations

import importlib.metadata
import logging
import time
from dataclasses import dataclass

import aiohttp

from controlmesh.infra.install import detect_install_info

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/controlmesh/json"
_GITHUB_RELEASES_URL = "https://api.github.com/repos/muqiao215/ControlMesh/releases"
_GITHUB_LATEST_RELEASE_URL = f"{_GITHUB_RELEASES_URL}/latest"
_PACKAGE_NAME = "controlmesh"
_TIMEOUT = aiohttp.ClientTimeout(total=10)


def get_current_version() -> str:
    """Return the installed version of controlmesh."""
    try:
        return importlib.metadata.version(_PACKAGE_NAME)
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse dotted version string into a comparable tuple."""
    parts: list[int] = []
    for segment in v.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            break
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """Result of a version check."""

    current: str
    latest: str
    update_available: bool
    summary: str
    source: str = "pypi"


async def check_pypi(*, fresh: bool = False) -> VersionInfo | None:
    """Check PyPI for the latest version. Returns None on failure.

    When ``fresh=True``, request with no-cache headers and a cache-busting
    query parameter to reduce stale CDN/cache responses.
    """
    current = get_current_version()
    headers = None
    params = None
    if fresh:
        headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
        params = {"_": str(time.time_ns())}

    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT) as session,
            session.get(_PYPI_URL, headers=headers, params=params) as resp,
        ):
            if resp.status != 200:
                return None
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.debug("PyPI version check failed", exc_info=True)
        return None

    info = data.get("info", {})
    latest = info.get("version", "")
    if not latest:
        return None

    summary = info.get("summary", "")
    update_available = _parse_version(latest) > _parse_version(current)
    return VersionInfo(
        current=current,
        latest=latest,
        update_available=update_available,
        summary=summary,
        source="pypi",
    )


def _normalize_release_version(tag: str) -> str:
    """Normalize GitHub release tags like ``v1.2.3`` to ``1.2.3``."""
    normalized = tag.strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return normalized


async def check_github_release(*, fresh: bool = False) -> VersionInfo | None:
    """Check GitHub Releases for the latest public release."""
    current = get_current_version()
    headers = {"Accept": "application/vnd.github+json"}
    params = None
    if fresh:
        headers.update({"Cache-Control": "no-cache", "Pragma": "no-cache"})
        params = {"_": str(time.time_ns())}

    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
            session.get(_GITHUB_LATEST_RELEASE_URL, params=params) as resp,
        ):
            if resp.status != 200:
                return None
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        logger.debug("GitHub latest release check failed", exc_info=True)
        return None

    tag = data.get("tag_name", "")
    latest = _normalize_release_version(tag) if isinstance(tag, str) else ""
    if not latest:
        return None

    name = data.get("name", "")
    summary = name if isinstance(name, str) else ""
    update_available = _parse_version(latest) > _parse_version(current)
    return VersionInfo(
        current=current,
        latest=latest,
        update_available=update_available,
        summary=summary,
        source="github",
    )


async def check_latest_version(*, fresh: bool = False) -> VersionInfo | None:
    """Check the latest installable version for the active installation source.

    GitHub direct installs can upgrade against GitHub Releases immediately.
    PyPI installs must only trust PyPI metadata; otherwise a freshly-tagged
    GitHub release can be announced before any installable wheel/sdist exists.
    """
    install_info = detect_install_info()
    if install_info.source == "github":
        github = await check_github_release(fresh=fresh)
        if github is not None:
            return github
        return await check_pypi(fresh=fresh)

    pypi = await check_pypi(fresh=fresh)
    if pypi is not None:
        return pypi

    if install_info.source == "pypi":
        return None

    return await check_github_release(fresh=fresh)


async def fetch_changelog(version: str) -> str | None:
    """Fetch release notes for *version* from GitHub Releases.

    Tries ``v{version}`` tag first, then ``{version}`` without prefix.
    Returns the release body (Markdown) or ``None`` on failure.
    """
    headers = {"Accept": "application/vnd.github+json"}
    for tag in (f"v{version}", version):
        url = f"{_GITHUB_RELEASES_URL}/tags/{tag}"
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT, headers=headers) as session,
                session.get(url) as resp,
            ):
                if resp.status != 200:
                    continue
                data = await resp.json()
                body: str = data.get("body", "")
                if body:
                    return body.strip()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            logger.debug("GitHub release fetch failed for tag %s", tag, exc_info=True)
    return None
