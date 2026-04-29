"""Matrix-specific startup sequence.

Reuses orchestrator creation from the core but skips Telegram-specific
parts (bot username lookup, command registration, group audit).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from controlmesh.i18n import t
from controlmesh.infra.restart import consume_restart_marker

if TYPE_CHECKING:
    from controlmesh.messenger.matrix.bot import MatrixBot

logger = logging.getLogger(__name__)


async def run_matrix_startup(bot: MatrixBot) -> None:
    """Matrix-specific startup: orchestrator and recovery.

    When ``bot._orchestrator`` is already set (secondary transport mode),
    orchestrator creation and all primary-only steps are skipped.
    """
    primary = bot._orchestrator is None

    if primary:
        from controlmesh.orchestrator.core import Orchestrator

        bot._orchestrator = await Orchestrator.create(bot._config, agent_name=bot._agent_name)

        # Wire all observers + injector to bus in one call
        bot._orchestrator.wire_observers_to_bus(bot._bus)

        # Handle restart sentinel
        restart_reason = _consume_restart_sentinel(bot)

        # Notify restart
        if restart_reason:
            await bot.notification_service.notify_all(
                t("startup.matrix_restart", reason=restart_reason)
            )

    logger.info(
        "Matrix bot online: %s on %s",
        bot._config.matrix.user_id,
        bot._config.matrix.homeserver,
    )

    # Run registered startup hooks (supervisor injection)
    for hook in bot._startup_hooks:
        await hook()


def _consume_restart_sentinel(bot: MatrixBot) -> str:
    """Check and consume restart marker."""
    paths_obj = bot._orchestrator.paths if bot._orchestrator else None
    if paths_obj is None:
        return ""
    marker_path = paths_obj.controlmesh_home / "restart-requested"
    if consume_restart_marker(marker_path=marker_path):
        return "restart marker"
    return ""
