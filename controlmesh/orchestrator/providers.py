"""Provider/model resolution extracted from the Orchestrator core."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from controlmesh.config import (
    _GEMINI_ALIASES,
    CLAUDE_MODELS,
    ModelRegistry,
    get_gemini_models,
    set_gemini_models,
)
from controlmesh.orchestrator.selectors.capability_registry import (
    CapabilityRegistry,
    default_capability_registry,
)

if TYPE_CHECKING:
    from controlmesh.cli.auth import AuthResult, AuthStatus
    from controlmesh.cli.codex_cache import CodexModelCache
    from controlmesh.cli.codex_cache_observer import CodexCacheObserver
    from controlmesh.cli.service import CLIService
    from controlmesh.config import AgentConfig

logger = logging.getLogger(__name__)

_EXPLICIT_RUNTIME_PROVIDERS = frozenset({"openai_agents", "claw", "opencode"})
_PROVIDER_NAME_ALIASES = {"claw-code": "claw"}
_PROVIDER_DISPLAY_NAMES = {
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini",
    "claw": "Claw-Code",
    "opencode": "OpenCode",
    "openai_agents": "OpenAI Agents",
}
_PROVIDER_PUBLIC_TOKENS = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "claw": "claw-code",
    "opencode": "opencode",
    "openai_agents": "openai_agents",
}
_EXPLICIT_RUNTIME_DEFAULT_MODELS = {
    "claw": "sonnet",
    "opencode": "openai/gpt-4.1",
}


def normalize_provider_name(provider: str | None) -> str:
    """Normalize external provider aliases to internal provider IDs."""
    normalized = (provider or "").strip().lower()
    return _PROVIDER_NAME_ALIASES.get(normalized, normalized)


def provider_display_name(provider: str | None) -> str:
    """Return a human-friendly provider label."""
    normalized = normalize_provider_name(provider)
    return _PROVIDER_DISPLAY_NAMES.get(normalized, normalized.title())


def provider_public_token(provider: str | None) -> str:
    """Return the public-facing provider token for commands and docs."""
    normalized = normalize_provider_name(provider)
    return _PROVIDER_PUBLIC_TOKENS.get(normalized, normalized)


class ProviderManager:
    """Owns provider authentication state, model resolution, and provider metadata.

    Extracted from ``Orchestrator`` to keep the core slim.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        codex_cache_fn: Callable[[], CodexModelCache | None] | None = None,
    ) -> None:
        self._config = config
        self._models = ModelRegistry()
        self._capabilities = default_capability_registry()
        self._known_model_ids: frozenset[str] = frozenset()
        self._available_providers: frozenset[str] = frozenset()
        self._gemini_api_key_mode: bool | None = None
        self._codex_cache_fn = codex_cache_fn
        self.refresh_known_model_ids()

    # -- Public properties ----------------------------------------------------

    @property
    def models(self) -> ModelRegistry:
        """Public access to the model registry."""
        return self._models

    @property
    def capabilities(self) -> CapabilityRegistry:
        """Public access to conservative channel capability metadata."""
        return self._capabilities

    @property
    def available_providers(self) -> frozenset[str]:
        """The set of authenticated provider names."""
        return self._available_providers

    @property
    def gemini_api_key_mode(self) -> bool:
        """Return cached Gemini API-key mode status."""
        if self._gemini_api_key_mode is None:
            from controlmesh.cli.auth import gemini_uses_api_key_mode

            self._gemini_api_key_mode = gemini_uses_api_key_mode()
        return self._gemini_api_key_mode

    @property
    def active_provider_name(self) -> str:
        """Human-readable name for the active CLI provider."""
        _model, provider = self.resolve_runtime_target(self._config.model)
        return provider_display_name(provider)

    # -- Auth / init ----------------------------------------------------------

    def apply_auth_results(
        self,
        auth_results: dict[str, AuthResult],
        *,
        auth_status_enum: type[AuthStatus],
        cli_service: CLIService,
    ) -> None:
        """Log provider auth states and update the runtime provider set."""
        authenticated = auth_status_enum.AUTHENTICATED
        installed = auth_status_enum.INSTALLED

        for provider, result in auth_results.items():
            if result.status == authenticated:
                logger.info("Provider [%s]: authenticated", provider)
            elif result.status == installed:
                logger.warning("Provider [%s]: installed but NOT authenticated", provider)
            else:
                logger.info("Provider [%s]: not found", provider)

        self._available_providers = frozenset(
            name for name, res in auth_results.items() if res.is_authenticated
        )
        cli_service.update_available_providers(self._available_providers)

    def init_gemini_state(self, paths_workspace: object) -> None:
        """Cache Gemini API-key mode and trust workspace once at startup."""
        from controlmesh.cli.auth import gemini_uses_api_key_mode

        self._gemini_api_key_mode = gemini_uses_api_key_mode()
        if "gemini" in self._available_providers:
            from controlmesh.cli.gemini_utils import trust_workspace

            trust_workspace(paths_workspace)  # type: ignore[arg-type]

    # -- Model resolution -----------------------------------------------------

    def on_gemini_models_refresh(self, models: tuple[str, ...]) -> None:
        """Callback for GeminiCacheObserver: update model registry."""
        set_gemini_models(frozenset(models))
        self.refresh_known_model_ids()
        self._gemini_api_key_mode = None  # Invalidate to re-check on next access

    def refresh_known_model_ids(self) -> None:
        """Refresh directive-known model IDs from dynamic provider registries."""
        self._known_model_ids = CLAUDE_MODELS | _GEMINI_ALIASES | get_gemini_models()

    def resolve_runtime_target(self, requested_model: str | None = None) -> tuple[str, str]:
        """Resolve requested model to the effective ``(model, provider)`` pair."""
        model_name = requested_model or self._config.model
        if self._config.provider in _EXPLICIT_RUNTIME_PROVIDERS and (
            requested_model is None or requested_model == self._config.model
        ):
            return model_name, self._config.provider
        return model_name, self._models.provider_for(model_name)

    def is_known_model(self, candidate: str) -> bool:
        """Return True if *candidate* is a recognized model ID for any provider."""
        if candidate in self._known_model_ids:
            return True
        codex = self._codex_cache_fn() if self._codex_cache_fn else None
        return bool(codex and codex.validate_model(candidate))

    def default_model_for_provider(self, provider: str) -> str:
        """Return the default model ID for a provider, or empty string if unknown."""
        provider = normalize_provider_name(provider)
        if provider == "claude":
            return self._config.model if self._config.provider == "claude" else "sonnet"
        if provider == "codex":
            codex = self._codex_cache_fn() if self._codex_cache_fn else None
            if codex:
                for m in codex.models:
                    if m.is_default:
                        return m.id
            return ""
        if provider == "openai_agents":
            return (
                self._config.model
                if self._config.provider == "openai_agents"
                else self._config.agent_graph.openai_agents_model
            )
        if provider in _EXPLICIT_RUNTIME_DEFAULT_MODELS:
            return (
                self._config.model
                if self._config.provider == provider
                else _EXPLICIT_RUNTIME_DEFAULT_MODELS[provider]
            )
        return {"gemini": ""}.get(provider, "")

    def resolve_session_directive(self, key: str) -> tuple[str, str] | None:
        """Resolve a ``@key`` directive to ``(provider, model)`` or ``None``.

        Handles three cases:
        - provider name (``@codex``) -> (provider, default_model)
        - known model   (``@opus``)  -> (inferred_provider, model)
        - unknown                    -> None
        """
        normalized = normalize_provider_name(key)
        if normalized in ("claude", "codex", "gemini", "claw", "opencode"):
            return normalized, self.default_model_for_provider(normalized)
        if self.is_known_model(key):
            provider = self._models.provider_for(key)
            return provider, key
        return None

    # -- Provider metadata for API --------------------------------------------

    def build_provider_info(
        self,
        codex_cache_obs: CodexCacheObserver | None = None,
    ) -> list[dict[str, object]]:
        """Build provider metadata for the API auth_ok response.

        Only includes authenticated providers.
        """
        provider_meta: dict[str, tuple[str, str]] = {
            "claude": (provider_display_name("claude"), "#F97316"),
            "gemini": (provider_display_name("gemini"), "#8B5CF6"),
            "codex": (provider_display_name("codex"), "#10B981"),
            "claw": (provider_display_name("claw"), "#C084FC"),
            "opencode": (provider_display_name("opencode"), "#06B6D4"),
            "openai_agents": (provider_display_name("openai_agents"), "#2563EB"),
        }
        providers: list[dict[str, object]] = []
        for pid in sorted(self._available_providers):
            name, color = provider_meta.get(pid, (pid.title(), "#A1A1AA"))
            models: list[str]
            if pid == "claude":
                models = sorted(CLAUDE_MODELS)
            elif pid == "gemini":
                gemini = get_gemini_models()
                models = sorted(gemini) if gemini else sorted(_GEMINI_ALIASES)
            elif pid == "codex":
                cache = codex_cache_obs.get_cache() if codex_cache_obs else None
                models = [m.id for m in cache.models] if cache and cache.models else []
            elif pid == "openai_agents":
                models = [self._config.model] if self._config.provider == "openai_agents" else []
            elif pid in {"claw", "opencode"}:
                models = [self._config.model] if self._config.provider == pid else []
            else:
                models = []
            providers.append({"id": pid, "name": name, "color": color, "models": models})
        return providers
