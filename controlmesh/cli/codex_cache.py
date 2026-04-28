"""Persistent cache for Codex models with periodic refresh."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

from controlmesh.cli.codex_discovery import CodexModelInfo, discover_codex_models
from controlmesh.cli.model_cache import BaseModelCache

# Hardcoded fallback when discovery and disk cache both fail.
_FALLBACK_CODEX_MODELS: tuple[CodexModelInfo, ...] = (
    CodexModelInfo(
        id="gpt-5.5",
        display_name="GPT-5.5",
        description="Latest frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=True,
    ),
    CodexModelInfo(
        id="gpt-5.3-codex",
        display_name="gpt-5.3-codex",
        description="Frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=False,
    ),
    CodexModelInfo(
        id="gpt-5.4",
        display_name="gpt-5.4",
        description="Frontier agentic coding model.",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=False,
    ),
    CodexModelInfo(
        id="gpt-5.4-mini",
        display_name="GPT-5.4-Mini",
        description="Small, fast, cost-efficient coding model.",
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

_FALLBACK_DEFAULT_MODEL_ID = next(
    model.id for model in _FALLBACK_CODEX_MODELS if model.is_default
)


def _merge_with_fallback_catalog(
    models: list[CodexModelInfo],
) -> list[CodexModelInfo]:
    """Keep the built-in Codex baseline visible even when discovery is stale.

    Codex discovery can return an older non-empty catalog that omits newer
    productized baseline models such as ``gpt-5.5``. Merge the discovered
    catalog with the built-in fallback catalog so selectors and validation do
    not regress to an older menu just because the runtime discovery endpoint
    lagged behind.
    """
    if not models:
        return models

    # Keep the fallback baseline only for the legacy/stale Codex 5.x catalog
    # family that can omit newer baseline entries like gpt-5.5. Do not inject
    # fallback models into unrelated synthetic or future discovery catalogs.
    if not any(
        model.id in {fallback.id for fallback in _FALLBACK_CODEX_MODELS}
        or model.id.startswith("gpt-5")
        for model in models
    ):
        return models

    discovered_by_id = {model.id: model for model in models}
    merged: list[CodexModelInfo] = []
    seen: set[str] = set()

    for fallback in _FALLBACK_CODEX_MODELS:
        merged_model = discovered_by_id.get(fallback.id, fallback)
        merged.append(merged_model)
        seen.add(merged_model.id)

    for model in models:
        if model.id in seen:
            continue
        merged.append(model)
        seen.add(model.id)

    return [
        CodexModelInfo(
            id=model.id,
            display_name=model.display_name,
            description=model.description,
            supported_efforts=model.supported_efforts,
            default_effort=model.default_effort,
            is_default=model.id == _FALLBACK_DEFAULT_MODEL_ID,
        )
        for model in merged
    ]


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
        models = await discover_codex_models()
        return _merge_with_fallback_catalog(models)

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
