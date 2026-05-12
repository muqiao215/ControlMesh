"""Shared provider/model binding normalization and display helpers."""

from __future__ import annotations

from collections.abc import Callable

_PROVIDER_NAME_ALIASES = {
    "claw-code": "claw",
    "openai": "codex",
}
_PROVIDER_DEFAULT_MODELS = {
    "claude": "sonnet",
    "claw": "sonnet",
}
_EXPLICIT_PROVIDER_INFERRED_ALLOWLIST: dict[str, frozenset[str]] = {
    "claude": frozenset({"", "claude"}),
    "claw": frozenset({"", "claude"}),
    "codex": frozenset({"", "codex"}),
    "gemini": frozenset({"", "gemini"}),
}


def _infer_explicit_model_family(
    provider: str,
    model: str,
    inferred_provider: str,
) -> str:
    """Apply lightweight explicit-runtime heuristics missing from ModelRegistry."""
    if "/" in model and provider in {"claude", "claw", "codex", "gemini"}:
        return "opencode"
    return inferred_provider


def normalize_provider_name(provider: str | None) -> str:
    """Normalize external provider aliases to internal provider IDs."""
    normalized = (provider or "").strip().lower()
    return _PROVIDER_NAME_ALIASES.get(normalized, normalized)


def provider_model_label(
    provider: str | None,
    model: str | None,
    *,
    default_provider: str = "parent-default",
    default_model: str = "parent-default",
) -> str:
    """Render a stable provider/model label for user-facing surfaces."""
    provider_text = (provider or "").strip() or default_provider
    model_text = (model or "").strip() or default_model
    return f"{provider_text} / {model_text}"


def validate_provider_model_binding(
    provider: str | None,
    model: str | None,
    *,
    model_provider_resolver: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """Normalize and validate one provider/model binding."""
    normalized_provider = normalize_provider_name(provider)
    normalized_model = (model or "").strip()
    if not normalized_provider:
        msg = "error:missing_provider"
        raise ValueError(msg)
    if "/" in normalized_provider:
        msg = f"error:invalid_provider_token provider={normalized_provider}"
        raise ValueError(msg)

    resolver = model_provider_resolver
    inferred_provider = resolver(normalized_model) if resolver and normalized_model else ""
    inferred_provider = _infer_explicit_model_family(
        normalized_provider,
        normalized_model,
        inferred_provider,
    )
    if normalized_model:
        allowed_inferred = _EXPLICIT_PROVIDER_INFERRED_ALLOWLIST.get(normalized_provider)
        if allowed_inferred is not None and inferred_provider not in allowed_inferred:
            msg = (
                "error:model_provider_mismatch "
                f"provider={normalized_provider} model={normalized_model} inferred_provider={inferred_provider}"
            )
            raise ValueError(msg)

    if not normalized_model and normalized_provider in _PROVIDER_DEFAULT_MODELS:
        normalized_model = _PROVIDER_DEFAULT_MODELS[normalized_provider]

    return normalized_provider, normalized_model
