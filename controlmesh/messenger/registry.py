"""Transport registry: centralizes bot creation for all transports.

Instead of scattering ``if config.transport == "matrix"`` checks across
the codebase, all transport-specific logic is registered here.
Adding a new transport (e.g. Discord, Slack) requires only adding an
entry to ``_TRANSPORT_FACTORIES``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controlmesh.bus.bus import MessageBus
    from controlmesh.bus.lock_pool import LockPool
    from controlmesh.config import AgentConfig
    from controlmesh.messenger.protocol import BotProtocol

_Factory = Callable[..., "BotProtocol"]


def create_bot(
    config: AgentConfig,
    *,
    agent_name: str = "main",
    bus: MessageBus | None = None,
    lock_pool: LockPool | None = None,
) -> BotProtocol:
    """Create the transport-specific bot for *config*.

    When multiple transports are configured, returns a
    ``MultiBotAdapter`` that wraps them all.

    Optional *bus* and *lock_pool* are forwarded to the transport
    constructor so that multiple bots can share the same instances.

    Raises ``ValueError`` for unknown transport types.
    """
    if config.is_multi_transport:
        from controlmesh.messenger.multi import MultiBotAdapter

        return MultiBotAdapter(config, agent_name=agent_name)

    return _create_single_bot(
        config.transport,
        config,
        agent_name=agent_name,
        bus=bus,
        lock_pool=lock_pool,
    )


def _create_single_bot(
    transport: str,
    config: AgentConfig,
    *,
    agent_name: str = "main",
    bus: MessageBus | None = None,
    lock_pool: LockPool | None = None,
) -> BotProtocol:
    """Create a single transport bot by name.

    Used directly by ``create_bot`` for single-transport configs and
    internally by ``MultiBotAdapter`` when building its bot list.
    """
    factory = _TRANSPORT_FACTORIES.get(transport)
    if factory is None:
        msg = f"Unknown transport: {transport!r}. Supported: {list(_TRANSPORT_FACTORIES)}"
        raise ValueError(msg)
    return factory(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


def _create_telegram(
    config: AgentConfig,
    *,
    agent_name: str,
    bus: MessageBus | None,
    lock_pool: LockPool | None,
) -> BotProtocol:
    from controlmesh.messenger.telegram.app import TelegramBot

    return TelegramBot(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


def _create_matrix(
    config: AgentConfig,
    *,
    agent_name: str,
    bus: MessageBus | None,
    lock_pool: LockPool | None,
) -> BotProtocol:
    from controlmesh.messenger.matrix.bot import MatrixBot

    return MatrixBot(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


def _create_feishu(
    config: AgentConfig,
    *,
    agent_name: str,
    bus: MessageBus | None,
    lock_pool: LockPool | None,
) -> BotProtocol:
    from controlmesh.messenger.feishu.bot import FeishuBot

    return FeishuBot(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


def _create_weixin(
    config: AgentConfig,
    *,
    agent_name: str,
    bus: MessageBus | None,
    lock_pool: LockPool | None,
) -> BotProtocol:
    from controlmesh.messenger.weixin.bot import WeixinBot

    return WeixinBot(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


def _create_qqbot(
    config: AgentConfig,
    *,
    agent_name: str,
    bus: MessageBus | None,
    lock_pool: LockPool | None,
) -> BotProtocol:
    from controlmesh.messenger.qqbot.bot import QQBotBot

    return QQBotBot(config, agent_name=agent_name, bus=bus, lock_pool=lock_pool)


_TRANSPORT_FACTORIES: dict[str, _Factory] = {
    "telegram": _create_telegram,
    "matrix": _create_matrix,
    "feishu": _create_feishu,
    "weixin": _create_weixin,
    "qqbot": _create_qqbot,
}
