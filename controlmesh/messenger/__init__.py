"""Messenger abstraction layer — transport-agnostic protocols and registry."""

from controlmesh.messenger.capabilities import MessengerCapabilities
from controlmesh.messenger.commands import (
    DIRECT_COMMANDS,
    MULTIAGENT_COMMANDS,
    ORCHESTRATOR_COMMANDS,
    classify_command,
)
from controlmesh.messenger.multi import MultiBotAdapter
from controlmesh.messenger.notifications import CompositeNotificationService, NotificationService
from controlmesh.messenger.protocol import BotProtocol
from controlmesh.messenger.registry import create_bot
from controlmesh.messenger.send_opts import BaseSendOpts

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
