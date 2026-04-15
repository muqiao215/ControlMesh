"""Persistent cache for Codex models with periodic refresh."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

from controlmesh.cli.codex_discovery import CodexModelInfo, discover_codex_models
from controlmesh.cli.model_cache import BaseModelCache

# Hardcoded fallback when discovery and disk cache both fail.
_FALLBACK_CODEX_MODELS: tuple[CodexModelInfo, ...] = (
    CodexModelInfo(
        id="gpt-5.3-codex",
        display_name="gpt-5.3-codex",
        description="Latest frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=True,
    ),
    CodexModelInfo(
        id="gpt-5.4",
        display_name="gpt-5.4",
        description="Latest frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=False,
    ),
    CodexModelInfo(
        id="gpt-5.2-codex",
        display_name="gpt-5.2-codex",
        description="Frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=False,
    ),
    CodexModelInfo(
        id="gpt-5.1-codex-mini",
        display_name="gpt-5.1-codex-mini",
        description="Optimized for codex. Cheaper, faster, but less capable.",
        supported_efforts=("medium", "high"),
        default_effort="medium",
        is_default=False,
    ),
)


@dataclass(frozen=True)
class CodexModelCache(BaseModelCache):
    """Immutable cache of Codex models with refresh logic."""

    last_updated: str  # ISO 8601 timestamp
    models: list[CodexModelInfo]

    @classmethod
    def _provider_name(cls) -> str:
        return "Codex"

    @classmethod
    async def _discover(cls) -> list[CodexModelInfo]:
        return await discover_codex_models()

    @classmethod
    def _empty_models(cls) -> list[CodexModelInfo]:
        return []

    @classmethod
    def _fallback_models(cls) -> list[CodexModelInfo]:
        return list(_FALLBACK_CODEX_MODELS)

    def get_model(self, model_id: str) -> CodexModelInfo | None:
        """Look up model by ID."""
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def validate_model(self, model_id: str) -> bool:
        """Check if model exists in cache."""
        return self.get_model(model_id) is not None

    def validate_reasoning_effort(self, model_id: str, effort: str) -> bool:
        """Check if effort is supported by model."""
        model = self.get_model(model_id)
        if model is None:
            return False
        if not model.supported_efforts:
            return False
        return effort in model.supported_efforts

    def to_json(self) -> dict[str, Any]:
        """Serialize for persistence."""
        return {
            "last_updated": self.last_updated,
            "models": [
                {
                    "id": m.id,
                    "display_name": m.display_name,
                    "description": m.description,
                    "supported_efforts": list(m.supported_efforts),
                    "default_effort": m.default_effort,
                    "is_default": m.is_default,
                }
                for m in self.models
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Self:
        """Deserialize from JSON."""
        models = [
            CodexModelInfo(
                id=m["id"],
                display_name=m["display_name"],
                description=m["description"],
                supported_efforts=tuple(m["supported_efforts"]),
                default_effort=m["default_effort"],
                is_default=m["is_default"],
            )
            for m in data["models"]
        ]

        return cls(
            last_updated=data["last_updated"],
            models=models,
        )
