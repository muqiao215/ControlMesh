"""Direct API package with lazy optional crypto imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["ApiServer", "E2ESession"]

if TYPE_CHECKING:
    from ductor_bot.api.crypto import E2ESession
    from ductor_bot.api.server import ApiServer


def __getattr__(name: str) -> Any:
    if name == "ApiServer":
        from ductor_bot.api.server import ApiServer

        return ApiServer
    if name == "E2ESession":
        from ductor_bot.api.crypto import E2ESession

        return E2ESession
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
