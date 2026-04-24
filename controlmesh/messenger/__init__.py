"""Messenger abstraction layer — transport-agnostic protocols and registry.

Keep package exports lazy so low-level modules like ``messenger.address`` do
not trigger the whole messenger import graph during import-time type loading.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DIRECT_COMMANDS",
    "MULTIAGENT_COMMANDS",
    "ORCHESTRATOR_COMMANDS",
    "BaseSendOpts",
    "BotProtocol",
    "CompositeNotificationService",
    "MessengerCapabilities",
    "MultiBotAdapter",
    "NotificationService",
    "classify_command",
    "create_bot",
]


def __getattr__(name: str) -> Any:
    if name in {
        "DIRECT_COMMANDS",
        "MULTIAGENT_COMMANDS",
        "ORCHESTRATOR_COMMANDS",
        "classify_command",
    }:
        from controlmesh.messenger.commands import (
            DIRECT_COMMANDS,
            MULTIAGENT_COMMANDS,
            ORCHESTRATOR_COMMANDS,
            classify_command,
        )

        return {
            "DIRECT_COMMANDS": DIRECT_COMMANDS,
            "MULTIAGENT_COMMANDS": MULTIAGENT_COMMANDS,
            "ORCHESTRATOR_COMMANDS": ORCHESTRATOR_COMMANDS,
            "classify_command": classify_command,
        }[name]

    if name == "MessengerCapabilities":
        from controlmesh.messenger.capabilities import MessengerCapabilities

        return MessengerCapabilities

    if name == "MultiBotAdapter":
        from controlmesh.messenger.multi import MultiBotAdapter

        return MultiBotAdapter

    if name in {"CompositeNotificationService", "NotificationService"}:
        from controlmesh.messenger.notifications import (
            CompositeNotificationService,
            NotificationService,
        )

        return {
            "CompositeNotificationService": CompositeNotificationService,
            "NotificationService": NotificationService,
        }[name]

    if name == "BotProtocol":
        from controlmesh.messenger.protocol import BotProtocol

        return BotProtocol

    if name == "create_bot":
        from controlmesh.messenger.registry import create_bot

        return create_bot

    if name == "BaseSendOpts":
        from controlmesh.messenger.send_opts import BaseSendOpts

        return BaseSendOpts

    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
