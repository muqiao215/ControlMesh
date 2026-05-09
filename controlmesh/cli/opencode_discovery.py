"""Dynamic OpenCode model discovery via ``opencode models``."""

from __future__ import annotations

import asyncio
import logging
from shutil import which

from controlmesh.cli.auth import read_opencode_primary_provider
from controlmesh.infra.platform import CREATION_FLAGS as _CREATION_FLAGS

logger = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 10.0


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
