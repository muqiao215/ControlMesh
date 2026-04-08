"""Shared type aliases for gateway configuration."""

from __future__ import annotations

from typing import Literal

GatewayType = Literal["command", "webhook"]
GatewayPrecedence = Literal["explicit-first", "broadcast-fallback"]
