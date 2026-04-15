"""Gateway configuration models.

This is a skeleton only. It establishes the stable config surface before
runtime delivery is wired into the bus.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from controlmesh.gateways.types import GatewayPrecedence, GatewayType


class GatewayTargetConfig(BaseModel):
    """One named gateway target."""

    enabled: bool = True
    type: GatewayType = "command"
    timeout_ms: int = Field(default=5000, ge=1)
    command: str = ""
    url: str = ""
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, value: str) -> str:
        stripped = value.strip().upper()
        if not stripped:
            msg = "webhook gateways require a non-empty method"
            raise ValueError(msg)
        return stripped

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> GatewayTargetConfig:
        if self.type == "command" and not self.command.strip():
            msg = "command gateways require a non-empty command"
            raise ValueError(msg)
        if self.type == "webhook" and not self.url.strip():
            msg = "webhook gateways require a non-empty url"
            raise ValueError(msg)
        return self


class GatewayEventRuleConfig(BaseModel):
    """Routing rule for one named event."""

    enabled: bool = True
    gateway: str = ""
    instruction: str = ""
    fallback_allowed: bool = True

    @model_validator(mode="after")
    def _validate_enabled_rule(self) -> GatewayEventRuleConfig:
        if not self.enabled:
            return self
        if not self.gateway.strip():
            msg = "enabled gateway event rules require a non-empty gateway"
            raise ValueError(msg)
        if not self.instruction.strip():
            msg = "enabled gateway event rules require a non-empty instruction"
            raise ValueError(msg)
        return self


class GatewayDispatchConfig(BaseModel):
    """Top-level gateway dispatch configuration."""

    enabled: bool = False
    precedence: GatewayPrecedence = "explicit-first"
    default_timeout_ms: int = Field(default=5000, ge=1)
    gateways: dict[str, GatewayTargetConfig] = Field(default_factory=dict)
    events: dict[str, GatewayEventRuleConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_event_targets(self) -> GatewayDispatchConfig:
        enabled_gateways = {name for name, cfg in self.gateways.items() if cfg.enabled}
        for event_name, rule in self.events.items():
            if not rule.enabled:
                continue
            if rule.gateway not in self.gateways:
                msg = f"event '{event_name}' references unknown gateway '{rule.gateway}'"
                raise ValueError(msg)
            if rule.gateway not in enabled_gateways:
                msg = f"event '{event_name}' references disabled gateway '{rule.gateway}'"
                raise ValueError(msg)
        return self

    def enabled_gateway_names(self) -> tuple[str, ...]:
        """Return enabled gateway names in stable order."""
        return tuple(name for name, cfg in self.gateways.items() if cfg.enabled)

    def enabled_event_names(self) -> tuple[str, ...]:
        """Return enabled event names in stable order."""
        return tuple(name for name, cfg in self.events.items() if cfg.enabled)
