"""Tests for the interactive model selector wizard."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from controlmesh.cli.auth import AuthResult, AuthStatus
from controlmesh.cli.codex_cache import CodexModelCache
from controlmesh.cli.codex_discovery import CodexModelInfo
from controlmesh.config import reset_gemini_models, set_gemini_models
from controlmesh.orchestrator.core import Orchestrator
from controlmesh.orchestrator.selectors.model_selector import (
    handle_model_callback,
    is_model_selector_callback,
    model_selector_start,
    switch_model,
)
from controlmesh.session.key import SessionKey

_AUTHED_CLAUDE = AuthResult("claude", AuthStatus.AUTHENTICATED)
_AUTHED_CODEX = AuthResult("codex", AuthStatus.AUTHENTICATED)
_AUTHED_GEMINI = AuthResult("gemini", AuthStatus.AUTHENTICATED)
_AUTHED_CLAW = AuthResult("claw", AuthStatus.AUTHENTICATED)
_AUTHED_OPENCODE = AuthResult("opencode", AuthStatus.AUTHENTICATED)
_NOT_FOUND_CLAUDE = AuthResult("claude", AuthStatus.NOT_FOUND)
_NOT_FOUND_CODEX = AuthResult("codex", AuthStatus.NOT_FOUND)
_NOT_FOUND_GEMINI = AuthResult("gemini", AuthStatus.NOT_FOUND)
_NOT_FOUND_CLAW = AuthResult("claw", AuthStatus.NOT_FOUND)
_NOT_FOUND_OPENCODE = AuthResult("opencode", AuthStatus.NOT_FOUND)

_CODEX_MODELS = [
    CodexModelInfo(
        id="gpt-5.2-codex",
        display_name="gpt-5.2-codex",
        description="Frontier",
        supported_efforts=("low", "medium", "high", "xhigh"),
        default_effort="medium",
        is_default=True,
    ),
    CodexModelInfo(
        id="gpt-5.1-codex-mini",
        display_name="gpt-5.1-codex-mini",
        description="Mini",
        supported_efforts=("medium", "high"),
        default_effort="medium",
        is_default=False,
    ),
]


def _patch_auth(auth_map: dict[str, AuthResult]) -> Any:
    return patch(
        "controlmesh.orchestrator.selectors.model_selector.check_all_auth",
        return_value=auth_map,
    )


@pytest.fixture(autouse=True)
def _reset_gemini_models() -> Any:
    reset_gemini_models()
    yield
    reset_gemini_models()


@contextmanager
def _with_codex_cache(orch: Orchestrator, models: list[CodexModelInfo] | None = None) -> Any:
    """Set up a mock codex_cache_obs on the observer manager."""
    cache = CodexModelCache(
        last_updated=datetime.now(UTC).isoformat(),
        models=models if models is not None else _CODEX_MODELS,
    )
    mock_observer = MagicMock()
    mock_observer.get_cache = MagicMock(return_value=cache)
    old = getattr(orch._observers, "codex_cache_obs", None)
    orch._observers.codex_cache_obs = mock_observer
    try:
        yield
    finally:
        orch._observers.codex_cache_obs = old


# -- is_model_selector_callback --


def test_prefix_detection() -> None:
    assert is_model_selector_callback("ms:p:claude") is True
    assert is_model_selector_callback("ms:m:opus") is True
    assert is_model_selector_callback("other") is False
    assert is_model_selector_callback("") is False


# -- model_selector_start --


async def test_start_no_providers(orch: Orchestrator) -> None:
    with _patch_auth(
        {
            "claude": _NOT_FOUND_CLAUDE,
            "codex": _NOT_FOUND_CODEX,
            "gemini": _NOT_FOUND_GEMINI,
            "claw": _NOT_FOUND_CLAW,
            "opencode": _NOT_FOUND_OPENCODE,
        }
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert "No authenticated providers" in resp.text
    assert resp.buttons is None


async def test_start_one_provider_claude(orch: Orchestrator) -> None:
    with _patch_auth(
        {
            "claude": _AUTHED_CLAUDE,
            "codex": _NOT_FOUND_CODEX,
            "gemini": _NOT_FOUND_GEMINI,
            "claw": _NOT_FOUND_CLAW,
            "opencode": _NOT_FOUND_OPENCODE,
        }
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert "Select Claude model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "HAIKU" in labels
    assert "SONNET" in labels
    assert "OPUS" in labels


async def test_start_one_provider_codex(orch: Orchestrator) -> None:
    with (
        _patch_auth(
            {
                "claude": _NOT_FOUND_CLAUDE,
                "codex": _AUTHED_CODEX,
                "gemini": _NOT_FOUND_GEMINI,
                "claw": _NOT_FOUND_CLAW,
                "opencode": _NOT_FOUND_OPENCODE,
            }
        ),
        _with_codex_cache(orch),
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert "Select Codex model" in resp.text
    assert resp.buttons is not None


async def test_start_shows_configured_model_without_runtime_fallback(orch: Orchestrator) -> None:
    orch._providers._available_providers = frozenset({"codex"})
    with (
        _patch_auth(
            {
                "claude": _NOT_FOUND_CLAUDE,
                "codex": _AUTHED_CODEX,
                "gemini": _NOT_FOUND_GEMINI,
                "claw": _NOT_FOUND_CLAW,
                "opencode": _NOT_FOUND_OPENCODE,
            }
        ),
        _with_codex_cache(orch),
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert resp.buttons is not None
    assert "Current: opus" in resp.text
    assert "Configured default:" not in resp.text


async def test_start_two_providers(orch: Orchestrator) -> None:
    with _patch_auth(
        {
            "claude": _AUTHED_CLAUDE,
            "codex": _AUTHED_CODEX,
            "gemini": _NOT_FOUND_GEMINI,
            "claw": _NOT_FOUND_CLAW,
            "opencode": _NOT_FOUND_OPENCODE,
        }
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert "Model Selector" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "CLAUDE" in labels
    assert "CODEX" in labels


async def test_start_one_provider_gemini_uses_discovered_models(orch: Orchestrator) -> None:
    set_gemini_models(
        frozenset(
            {
                "gemini-2.5-pro",
                "gemini-2.5-flash",
                "gemini-3-pro-preview",
            }
        )
    )
    with _patch_auth(
        {
            "claude": _NOT_FOUND_CLAUDE,
            "codex": _NOT_FOUND_CODEX,
            "gemini": _AUTHED_GEMINI,
            "claw": _NOT_FOUND_CLAW,
            "opencode": _NOT_FOUND_OPENCODE,
        }
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert "Select Gemini model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "2.5-pro" in labels
    assert "2.5-flash" in labels
    assert "3-pro-preview" in labels


async def test_start_runtime_providers_get_their_own_row(orch: Orchestrator) -> None:
    with _patch_auth(
        {
            "claude": _AUTHED_CLAUDE,
            "codex": _AUTHED_CODEX,
            "gemini": _NOT_FOUND_GEMINI,
            "claw": _AUTHED_CLAW,
            "opencode": _AUTHED_OPENCODE,
        }
    ):
        resp = await model_selector_start(orch, SessionKey(chat_id=1))
    assert resp.buttons is not None
    assert len(resp.buttons.rows) == 2
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "CLAW-CODE" in labels
    assert "OPENCODE" in labels


# -- handle_model_callback: provider selection --


async def test_callback_provider_claude(orch: Orchestrator) -> None:
    resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:p:claude")
    assert "Select Claude model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "OPUS" in labels
    assert "<< Back" in labels


async def test_callback_provider_codex(orch: Orchestrator) -> None:
    with _with_codex_cache(orch):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:p:codex")
    assert "Select Codex model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "gpt-5.2-codex" in labels


async def test_callback_provider_codex_fallback(orch: Orchestrator) -> None:
    with _with_codex_cache(orch, models=[]):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:p:codex")
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert any("o3" in label.lower() for label in labels) or "<< Back" in labels


async def test_callback_provider_opencode_uses_runtime_default_model(orch: Orchestrator) -> None:
    with patch("controlmesh.cli.auth.read_opencode_default_model", return_value="zhipuai/glm-5.1"):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:p:opencode")
    assert "Select OpenCode model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "zhipuai/glm-5.1" in labels


async def test_callback_provider_opencode_shows_current_runtime_model(orch: Orchestrator) -> None:
    orch._config.provider = "opencode"
    orch._config.model = "openai/gpt-4.1"

    resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:p:opencode")

    assert "Select OpenCode model" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "openai/gpt-4.1" in labels


# -- handle_model_callback: model selection --


async def test_callback_model_claude_switches(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:m:sonnet")
    assert "sonnet" in resp.text
    assert resp.buttons is None
    assert orch._config.model == "sonnet"


async def test_callback_model_codex_shows_reasoning(orch: Orchestrator) -> None:
    with _with_codex_cache(orch):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:m:gpt-5.2-codex")
    assert "Thinking level" in resp.text
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "Low" in labels
    assert "High" in labels
    assert "XHigh" in labels


async def test_callback_model_codex_mini_limited_efforts(orch: Orchestrator) -> None:
    with _with_codex_cache(orch):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:m:gpt-5.1-codex-mini")
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "Medium" in labels
    assert "High" in labels
    assert "Low" not in labels
    assert "XHigh" not in labels


async def test_callback_runtime_provider_switches_to_opencode(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))

    resp = await handle_model_callback(
        orch,
        SessionKey(chat_id=1),
        "ms:x:opencode:openai/gpt-4.1",
    )

    assert "Provider:" in resp.text
    assert "opencode" in resp.text
    assert orch._config.provider == "opencode"
    assert orch._config.model == "openai/gpt-4.1"


async def test_switch_model_provider_change_to_opencode_resets_target_session(orch: Orchestrator) -> None:
    session, _ = await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="codex", model="gpt-5.4"
    )
    session.session_id = "codex-sid"
    session.provider_sessions["opencode"] = type(session._current_provider_data())(
        session_id="old-opencode-sid",
        message_count=3,
    )
    await orch._sessions.update_session(session)

    mock_kill = AsyncMock(return_value=0)
    object.__setattr__(orch._process_registry, "kill_all", mock_kill)
    with patch.object(orch._sessions, "reset_provider_session", wraps=orch._sessions.reset_provider_session) as reset_mock:
        result = await switch_model(
            orch,
            SessionKey(chat_id=1),
            "zhipuai/glm-5.1",
            provider_override="opencode",
        )

    reset_mock.assert_called_once_with(
        SessionKey(chat_id=1),
        provider="opencode",
        model="zhipuai/glm-5.1",
    )
    assert "Resuming session" not in result
    active = await orch._sessions.get_active(SessionKey(chat_id=1))
    assert active is not None
    assert active.provider == "opencode"
    assert active.model == "zhipuai/glm-5.1"
    assert active.session_id == ""


# -- handle_model_callback: reasoning selection --


async def test_callback_reasoning_switches(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:r:high:gpt-5.2-codex")
    assert "gpt-5.2-codex" in resp.text
    assert "high" in resp.text.lower()
    assert resp.buttons is None


# -- handle_model_callback: back navigation --


async def test_callback_back_root(orch: Orchestrator) -> None:
    with _patch_auth(
        {"claude": _AUTHED_CLAUDE, "codex": _AUTHED_CODEX, "gemini": _NOT_FOUND_GEMINI}
    ):
        resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:b:root")
    assert resp.buttons is not None
    labels = [btn.text for row in resp.buttons.rows for btn in row]
    assert "CLAUDE" in labels


async def test_callback_back_provider(orch: Orchestrator) -> None:
    resp = await handle_model_callback(orch, SessionKey(chat_id=1), "ms:b:claude")
    assert "Select Claude model" in resp.text


# -- switch_model --


async def test_switch_model_basic(orch: Orchestrator) -> None:
    mock_kill = AsyncMock(return_value=0)
    mock_reset = AsyncMock()
    object.__setattr__(orch._process_registry, "kill_all", mock_kill)
    object.__setattr__(orch._sessions, "reset_provider_session", mock_reset)
    result = await switch_model(orch, SessionKey(chat_id=1), "sonnet")
    assert "opus" in result
    assert "sonnet" in result
    assert "Session reset" not in result
    assert "Resuming session" not in result
    assert orch._config.model == "sonnet"
    mock_kill.assert_called_once_with(1)
    mock_reset.assert_not_called()


async def test_switch_model_already_set(orch: Orchestrator) -> None:
    result = await switch_model(orch, SessionKey(chat_id=1), "opus")
    assert "Already running" in result


async def test_switch_model_with_reasoning_effort(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await switch_model(orch, SessionKey(chat_id=1), "sonnet", reasoning_effort="high")
    assert "high" in result.lower()
    assert orch._config.reasoning_effort == "high"
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["reasoning_effort"] == "high"


async def test_switch_model_persists_to_config(orch: Orchestrator) -> None:
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    await switch_model(orch, SessionKey(chat_id=1), "sonnet")
    saved = json.loads(orch.paths.config_path.read_text(encoding="utf-8"))
    assert saved["model"] == "sonnet"


async def test_switch_model_provider_change(orch: Orchestrator) -> None:
    mock_reset = AsyncMock()
    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    object.__setattr__(orch._sessions, "reset_provider_session", mock_reset)
    result = await switch_model(orch, SessionKey(chat_id=1), "o3")
    assert "Provider:" in result
    assert orch._config.provider == "codex"
    mock_reset.assert_not_called()


async def test_switch_model_shows_resume_hint_same_provider(orch: Orchestrator) -> None:
    session, _ = await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="claude", model="opus"
    )
    session.session_id = "claude-abc123"
    await orch._sessions.update_session(session)

    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await switch_model(orch, SessionKey(chat_id=1), "sonnet")

    assert "Resuming session `claude-abc123`." in result
    assert "You have already sent 1 message in this provider session." in result
    assert "Current model: `sonnet`." in result
    assert "Use /new to start a fresh session." in result


async def test_switch_model_shows_resume_hint_provider_change(orch: Orchestrator) -> None:
    session, _ = await orch._sessions.resolve_session(
        SessionKey(chat_id=1), provider="codex", model="gpt-5.2-codex"
    )
    session.session_id = "codex-xyz789"
    await orch._sessions.update_session(session)

    object.__setattr__(orch._process_registry, "kill_all", AsyncMock(return_value=0))
    result = await switch_model(orch, SessionKey(chat_id=1), "o3")

    assert "Resuming session `codex-xyz789`." in result
    assert "You have already sent 1 message in this provider session." in result
    assert "Current model: `o3`." in result
    assert "Use /new to start a fresh session." in result


async def test_switch_reasoning_only(orch: Orchestrator) -> None:
    """Changing only reasoning effort does not reset session."""
    mock_kill = AsyncMock(return_value=0)
    mock_reset = AsyncMock()
    object.__setattr__(orch._process_registry, "kill_all", mock_kill)
    object.__setattr__(orch._sessions, "reset_provider_session", mock_reset)
    result = await switch_model(orch, SessionKey(chat_id=1), "opus", reasoning_effort="high")
    assert "Reasoning effort updated" in result
    mock_kill.assert_not_called()
    mock_reset.assert_not_called()
