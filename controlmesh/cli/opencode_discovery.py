"""Dynamic OpenCode model discovery via ``opencode models``."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from shutil import which

from controlmesh.cli.auth import read_opencode_default_model, read_opencode_primary_provider
from controlmesh.infra.platform import CREATION_FLAGS as _CREATION_FLAGS

logger = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 10.0
_SYNC_DISCOVERY_ENV = "CONTROLMESH_ENABLE_OPENCODE_SYNC_DISCOVERY"


async def discover_opencode_models(*, deadline: float = DISCOVERY_TIMEOUT) -> tuple[str, ...]:
    """Discover OpenCode models for the active runtime provider.

    Returns an empty tuple on missing CLI, parse failure, or timeout.
    Never raises.
    """
    opencode_path = which("opencode")
    if not opencode_path:
        logger.debug("opencode CLI not found, skipping model discovery")
        return ()

    provider = read_opencode_primary_provider().strip()
    cmd = [opencode_path, "models"]
    if provider:
        cmd.append(provider)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=deadline)
    except TimeoutError:
        logger.warning("OpenCode discovery timeout after %.0fs", deadline)
        return ()
    except OSError:
        logger.warning("Failed to spawn opencode models discovery", exc_info=True)
        return ()

    if process.returncode not in (0, None):
        detail = stderr.decode(errors="replace").strip()[:500]
        logger.warning(
            "OpenCode discovery failed rc=%s provider=%s detail=%s",
            process.returncode,
            provider or "<auto>",
            detail,
        )
        return ()

    models = _parse_models(stdout.decode(errors="replace"))
    logger.info(
        "OpenCode discovery found %d models provider=%s",
        len(models),
        provider or "<auto>",
    )
    return models


def discover_opencode_models_sync(*, deadline: float = DISCOVERY_TIMEOUT) -> tuple[str, ...]:
    """Synchronously discover OpenCode models for the active runtime provider.

    Returns an empty tuple on missing CLI, parse failure, or timeout.
    Never raises.
    """
    opencode_path = which("opencode")
    if not opencode_path:
        logger.debug("opencode CLI not found, skipping sync model discovery")
        return ()

    provider = read_opencode_primary_provider().strip()
    cmd = [opencode_path, "models"]
    if provider:
        cmd.append(provider)

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=deadline,
            creationflags=_CREATION_FLAGS,
        )
    except subprocess.TimeoutExpired:
        logger.warning("OpenCode sync discovery timeout after %.0fs", deadline)
        return ()
    except OSError:
        logger.warning("Failed to spawn sync opencode models discovery", exc_info=True)
        return ()

    if result.returncode not in (0, None):
        detail = (result.stderr or "").strip()[:500]
        logger.warning(
            "OpenCode sync discovery failed rc=%s provider=%s detail=%s",
            result.returncode,
            provider or "<auto>",
            detail,
        )
        return ()

    models = _parse_models(result.stdout or "")
    logger.info(
        "OpenCode sync discovery found %d models provider=%s",
        len(models),
        provider or "<auto>",
    )
    return models


def pick_opencode_runtime_model_sync(*, deadline: float = DISCOVERY_TIMEOUT) -> str:
    """Pick a usable OpenCode model from live runtime state.

    Priority:
    1. explicit/default model declared in local runtime config
    2. first live-discovered model from ``opencode models <provider>`` when
       ``CONTROLMESH_ENABLE_OPENCODE_SYNC_DISCOVERY=1`` is explicitly enabled
    """
    configured = read_opencode_default_model().strip()
    if configured:
        return configured

    if os.environ.get(_SYNC_DISCOVERY_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.info(
            "OpenCode sync discovery skipped because no default model is configured "
            "and %s is not enabled",
            _SYNC_DISCOVERY_ENV,
        )
        return ""

    discovered = discover_opencode_models_sync(deadline=deadline)
    return discovered[0] if discovered else ""


def resolve_opencode_runnable_model_sync(*, deadline: float = DISCOVERY_TIMEOUT) -> str:
    """Compatibility alias for callers that still expect a sync resolver.

    This must preserve the safer default behavior used by
    :func:`pick_opencode_runtime_model_sync`: prefer the configured default
    model and avoid synchronous runtime discovery unless explicitly enabled.
    """
    return pick_opencode_runtime_model_sync(deadline=deadline)


def _parse_models(raw: str) -> tuple[str, ...]:
    seen: set[str] = set()
    models: list[str] = []
    for line in raw.splitlines():
        model = line.strip()
        if not model or "/" not in model or model in seen:
            continue
        seen.add(model)
        models.append(model)
    return tuple(models)
