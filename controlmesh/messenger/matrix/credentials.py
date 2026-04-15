"""Matrix login and credential persistence.

Supports three modes:
1. Restore from saved credentials file (previous session)
2. Restore from config access_token + device_id
3. Initial login with password (saves credentials for future use)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nio import AsyncClient

    from controlmesh.config import MatrixConfig

logger = logging.getLogger(__name__)


async def login_or_restore(
    client: AsyncClient,
    config: MatrixConfig,
    store_path: Path,
) -> None:
    """Login with password or restore saved access_token."""
    creds_file = store_path / "credentials.json"

    # 1. Try saved credentials from previous session
    if creds_file.exists():
        try:
            creds = json.loads(creds_file.read_text(encoding="utf-8"))
            client.restore_login(
                user_id=creds["user_id"],
                device_id=creds["device_id"],
                access_token=creds["access_token"],
            )
            logger.info("Restored Matrix login from saved credentials")
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to restore saved credentials, trying config/password")
        else:
            return

    # 2. Try config access_token + device_id
    if config.access_token and config.device_id:
        client.restore_login(
            user_id=config.user_id,
            device_id=config.device_id,
            access_token=config.access_token,
        )
        _save_credentials(creds_file, config.user_id, config.device_id, config.access_token)
        logger.info("Restored Matrix login from config token")
        return

    # 3. First login with password
    if not config.password:
        msg = (
            f"Matrix AUTH FAILED for {config.user_id}\n"
            f"  No access_token, device_id, or password configured.\n"
            f"  Set 'password' in the matrix section of config.json."
        )
        raise RuntimeError(msg)

    resp = await client.login(config.password, device_name="controlmesh")
    if hasattr(resp, "access_token"):
        _save_credentials(creds_file, resp.user_id, resp.device_id, resp.access_token)
        logger.info("Matrix login successful, credentials saved")
    else:
        logger.error(
            "Matrix login failed for %s on %s: %s",
            config.user_id,
            config.homeserver,
            resp,
        )
        msg = (
            f"Matrix AUTH FAILED for {config.user_id}\n"
            f"  Homeserver: {config.homeserver}\n"
            f"  Error: {resp}\n"
            f"  Check your credentials in config.json (matrix section)."
        )
        raise RuntimeError(msg)


def _save_credentials(
    path: Path,
    user_id: str,
    device_id: str,
    access_token: str,
) -> None:
    """Save credentials to disk for future sessions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "user_id": user_id,
        "device_id": device_id,
        "access_token": access_token,
    }
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
