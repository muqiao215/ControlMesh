"""Application configuration and model registry."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from controlmesh.gateways.config import GatewayDispatchConfig

logger = logging.getLogger(__name__)
NULLISH_TEXT_VALUES: frozenset[str] = frozenset({"null", "none"})
DEFAULT_EMPTY_GEMINI_API_KEY: str = "null"

# Intentional bind-all: the API is designed for private-network use (Tailscale).
# Public exposure is gated by ``allow_public`` + a prominent warning at startup.
_BIND_ALL_INTERFACES: str = ".".join(["0"] * 4)

# Pre-build a safe UTC fallback.  On Windows without the ``tzdata`` package
# (now a declared dependency), ``ZoneInfo("UTC")`` raises.  The fallback
# is a minimal ``datetime.tzinfo`` subclass with a ``.key`` attribute so
# callers that log ``tz.key`` keep working.
try:
    _SAFE_UTC: ZoneInfo = ZoneInfo("UTC")
except (ZoneInfoNotFoundError, KeyError):
    import datetime as _dt

    class _UTCFallback(_dt.tzinfo):  # pragma: no cover
        """Minimal UTC stand-in for systems without IANA timezone data."""

        key: str = "UTC"
        _ZERO = _dt.timedelta(0)

        def utcoffset(self, dt: _dt.datetime | None) -> _dt.timedelta:
            return self._ZERO

        def tzname(self, dt: _dt.datetime | None) -> str:
            return "UTC"

        def dst(self, dt: _dt.datetime | None) -> _dt.timedelta:
            return self._ZERO

    _SAFE_UTC = _UTCFallback()  # type: ignore[assignment]
    logger.warning("tzdata package missing — using built-in UTC fallback")


class StreamingConfig(BaseModel):
    """Settings for streaming response output."""

    enabled: bool = True
    min_chars: int = 200
    max_chars: int = 4000
    idle_ms: int = 800
    edit_interval_seconds: float = 2.0
    max_edit_failures: int = 3
    append_mode: bool = False
    sentence_break: bool = True


class DockerConfig(BaseModel):
    """Settings for Docker-based CLI sandboxing."""

    enabled: bool = False
    image_name: str = "controlmesh-sandbox"
    container_name: str = "controlmesh-sandbox"
    auto_build: bool = True
    mount_host_cache: bool = False
    mounts: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)


_DEFAULT_HEARTBEAT_PROMPT = (
    "You are running as a background heartbeat check. Review the current workspace context:\n"
    "- Read memory_system/MAINMEMORY.md for user interests and personality\n"
    "- Check cron_tasks/ for active projects\n"
    "- Think about what might be useful, interesting, or fun for the user\n"
    "\n"
    "If you have a creative idea, suggestion, interesting fact, or something the user might enjoy:\n"
    "Reply with your message directly.\n"
    "\n"
    "If nothing needs attention right now:\n"
    "Reply exactly: HEARTBEAT_OK"
)

_DEFAULT_HEARTBEAT_ACK = "HEARTBEAT_OK"


class HeartbeatTarget(BaseModel):
    """A specific chat/topic to send heartbeat checks to.

    All optional fields override the global HeartbeatConfig when set.
    """

    enabled: bool = True
    chat_id: int | None = None
    topic_id: int | None = None
    prompt: str | None = None
    ack_token: str | None = None
    interval_minutes: int | None = None
    quiet_start: int | None = None
    quiet_end: int | None = None


class HeartbeatConfig(BaseModel):
    """Settings for the periodic heartbeat system."""

    enabled: bool = False
    interval_minutes: int = 30
    cooldown_minutes: int = 5
    quiet_start: int = 21
    quiet_end: int = 8
    prompt: str = _DEFAULT_HEARTBEAT_PROMPT
    ack_token: str = _DEFAULT_HEARTBEAT_ACK
    group_targets: list[HeartbeatTarget] = Field(
        default_factory=lambda: [
            HeartbeatTarget(
                enabled=False,
                chat_id=None,
                topic_id=None,
                prompt="Replace chat_id with your group ID to enable this target.",
            ),
        ]
    )


class CleanupConfig(BaseModel):
    """Settings for automatic file cleanup of workspace directories."""

    enabled: bool = True
    media_files_days: int = 30
    output_to_user_days: int = 30
    api_files_days: int = 30
    check_hour: int = 3

    def __init__(self, **data: object) -> None:
        # Backwards compat: accept old name ``telegram_files_days``.
        if "telegram_files_days" in data and "media_files_days" not in data:
            data["media_files_days"] = data.pop("telegram_files_days")
        elif "telegram_files_days" in data:
            data.pop("telegram_files_days")
        super().__init__(**data)


class ImageConfig(BaseModel):
    """Settings for incoming image processing."""

    max_dimension: int = 2000
    output_format: str = "webp"
    quality: int = 85


class CLIParametersConfig(BaseModel):
    """CLI parameters for main agent."""

    claude: list[str] = Field(default_factory=list)
    codex: list[str] = Field(default_factory=list)
    gemini: list[str] = Field(default_factory=list)


class MatrixConfig(BaseModel):
    """Matrix homeserver connection settings."""

    homeserver: str = ""  # https://matrix.myserver.com
    user_id: str = ""  # @controlmesh:myserver.com
    password: str = ""  # for initial login
    access_token: str = ""  # persisted after first login
    device_id: str = ""  # persisted after first login
    allowed_rooms: list[str] = Field(default_factory=list)  # ["!abc:server", "#room:server"]
    allowed_users: list[str] = Field(default_factory=list)  # ["@user:server"]
    store_path: str = "matrix_store"  # relative to controlmesh_home


class FeishuConfig(BaseModel):
    """Feishu bot-only transport settings."""

    mode: str = "bot_only"
    brand: str = "feishu"
    app_id: str = ""
    app_secret: str = ""
    domain: str = "https://open.feishu.cn"
    listener_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("listener_host", "callback_host"),
    )
    listener_port: int = Field(
        default=8765,
        validation_alias=AliasChoices("listener_port", "callback_port"),
    )
    listener_path: str = Field(
        default="/feishu/events",
        validation_alias=AliasChoices("listener_path", "callback_path"),
    )
    listener_max_body_bytes: int = Field(
        default=262144,
        validation_alias=AliasChoices("listener_max_body_bytes", "callback_max_body_bytes"),
    )
    allow_from: list[str] = Field(default_factory=list)
    group_reply_all: bool = False
    thread_isolation: bool = False
    reply_to_trigger: bool = True
    progress_mode: Literal["text", "card_preview"] = "text"

    @field_validator("listener_path")
    @classmethod
    def _validate_listener_path(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "Feishu listener_path must start with '/'"
            raise ValueError(msg)
        return value

    @property
    def callback_host(self) -> str:
        return self.listener_host

    @property
    def callback_port(self) -> int:
        return self.listener_port

    @property
    def callback_path(self) -> str:
        return self.listener_path

    @property
    def callback_max_body_bytes(self) -> int:
        return self.listener_max_body_bytes

    @model_validator(mode="after")
    def _validate_cut1_shape(self) -> FeishuConfig:
        if self.mode != "bot_only":
            msg = "Feishu cut 1 supports only mode='bot_only'"
            raise ValueError(msg)
        if self.brand != "feishu":
            msg = "Feishu cut 1 supports only brand='feishu'"
            raise ValueError(msg)
        return self


class WeixinConfig(BaseModel):
    """Weixin iLink transport settings.

    This is intentionally disabled by default: iLink requires QR-derived bot
    credentials and a context-token-bearing inbound message before replies are
    safe to send.
    """

    mode: Literal["ilink"] = "ilink"
    enabled: bool = False
    base_url: str = "https://ilinkai.weixin.qq.com"
    credentials_path: str = "weixin_store/credentials.json"
    poll_initial_cursor: str = ""
    longpoll_timeout_ms: int = 40000
    channel_version: str = "1.0.0"
    reply_chunk_chars: int = 2000


class TasksConfig(BaseModel):
    """Settings for background task delegation."""

    enabled: bool = True
    max_parallel: int = 5
    timeout_seconds: float = 3600.0


class TimeoutConfig(BaseModel):
    """Per-execution-path timeout settings."""

    normal: float = 600.0
    background: float = 1800.0
    subagent: float = 3600.0
    warning_intervals: list[float] = Field(default_factory=lambda: [60.0, 10.0])
    extend_on_activity: bool = True
    activity_extension: float = 120.0
    max_extensions: int = 3


class WebhookConfig(BaseModel):
    """Settings for the webhook HTTP server."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8742
    token: str = ""
    max_body_bytes: int = 262144
    rate_limit_per_minute: int = 30


class SceneConfig(BaseModel):
    """Settings for scene indicators and technical footer."""

    seen_reaction: bool = False
    technical_footer: bool = False


class CodexHooksConfig(BaseModel):
    """Settings for Codex native hook awareness."""

    enabled: bool = False
    prefer_native: bool = True
    config_file: str = ".codex/config.toml"
    hooks_file: str = ".codex/hooks.json"
    manage_project_hooks: bool = False


class ApiConfig(BaseModel):
    """Settings for the direct WebSocket API server.

    Designed for use over Tailscale or other private networks.
    When ``allow_public`` is False and Tailscale is not detected,
    the server still starts but logs a prominent warning.

    ``chat_id`` controls which session the API client uses.
    ``0`` means "use the first ``allowed_user_ids`` entry".
    """

    enabled: bool = False
    host: str = _BIND_ALL_INTERFACES
    port: int = 8741
    token: str = ""
    chat_id: int = 0
    allow_public: bool = False


def deep_merge_config(
    user: dict[str, object],
    defaults: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Recursively merge *defaults* into *user*, preserving user values.

    Returns ``(merged_dict, changed)`` where *changed* is True when new keys were added.
    """
    result: dict[str, object] = dict(user)
    changed = False
    new_keys = 0
    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val
            changed = True
            new_keys += 1
        elif isinstance(default_val, dict) and isinstance(result[key], dict):
            sub_merged, sub_changed = deep_merge_config(
                result[key],  # type: ignore[arg-type]
                default_val,
            )
            result[key] = sub_merged
            changed = changed or sub_changed
    if new_keys:
        logger.info("Config deep-merge: %d new keys added", new_keys)
    return result, changed


def update_config_file(config_path: Path, **updates: object) -> None:
    """Update specific keys in config.json without overwriting other user settings."""
    from controlmesh.infra.json_store import atomic_json_save

    data: dict[str, object] = json.loads(config_path.read_text(encoding="utf-8"))
    data.update(updates)
    atomic_json_save(config_path, data)
    logger.info("Persisted config update: %s", ", ".join(f"{k}={v}" for k, v in updates.items()))


async def update_config_file_async(config_path: Path, **updates: object) -> None:
    """Async wrapper: update config.json without blocking the event loop."""
    import asyncio

    await asyncio.to_thread(update_config_file, config_path, **updates)


class AgentConfig(BaseModel):
    """Top-level configuration loaded from config.json."""

    log_level: str = "INFO"
    provider: str = "claude"
    model: str = "opus"
    controlmesh_home: str = "~/.controlmesh"
    idle_timeout_minutes: int = 1440
    session_age_warning_hours: int = 12
    daily_reset_hour: int = 4
    daily_reset_enabled: bool = False
    max_budget_usd: float | None = None
    max_turns: int | None = None
    max_session_messages: int | None = None
    permission_mode: str = "bypassPermissions"
    cli_timeout: float = 1800.0
    reasoning_effort: str = "medium"
    file_access: str = "all"
    gemini_api_key: str | None = None
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    docker: DockerConfig = Field(default_factory=DockerConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    cleanup: CleanupConfig = Field(default_factory=CleanupConfig)
    webhooks: WebhookConfig = Field(default_factory=WebhookConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    cli_parameters: CLIParametersConfig = Field(default_factory=CLIParametersConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    tasks: TasksConfig = Field(default_factory=TasksConfig)
    scene: SceneConfig = Field(default_factory=SceneConfig)
    codex_hooks: CodexHooksConfig = Field(default_factory=CodexHooksConfig)
    gateways: GatewayDispatchConfig = Field(default_factory=GatewayDispatchConfig)
    user_timezone: str = ""
    language: str = "en"
    update_check: bool = True
    group_mention_only: bool = False
    interagent_port: int = 8799
    transport: str = "telegram"  # "telegram" | "matrix" | "feishu" | "weixin"
    transports: list[str] = Field(default_factory=list)
    telegram_token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)
    allowed_group_ids: list[int] = Field(default_factory=list)
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    weixin: WeixinConfig = Field(default_factory=WeixinConfig)

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def _normalize_gemini_api_key(cls, value: object) -> object:
        """Normalize null-like string values to ``None`` for optional key config."""
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized or normalized.lower() in NULLISH_TEXT_VALUES:
            return None
        return normalized

    @model_validator(mode="after")
    def _sync_cli_timeout_to_timeouts(self) -> AgentConfig:
        """Sync legacy ``cli_timeout`` to ``timeouts.normal`` for backward compat.

        When ``cli_timeout`` differs from the default 600.0 and ``timeouts.normal``
        is still at its default, propagate ``cli_timeout`` into ``timeouts.normal``.
        """
        if self.cli_timeout != 600.0 and self.timeouts.normal == 600.0:
            self.timeouts.normal = self.cli_timeout
        return self

    @model_validator(mode="after")
    def _normalize_transports(self) -> AgentConfig:
        """Normalize ``transports`` and ``transport`` for backward compat.

        - Empty ``transports`` → populated from ``transport`` (single-transport).
        - Non-empty ``transports`` → ``transport`` set to first entry (primary).
        """
        if not self.transports:
            self.transports = [self.transport]
        else:
            self.transport = self.transports[0]
        return self

    @property
    def is_multi_transport(self) -> bool:
        """True when more than one transport is configured."""
        return len(self.transports) > 1


def resolve_timeout(config: AgentConfig, path: str) -> float:
    """Resolve timeout for execution path: 'normal', 'background', 'subagent'."""
    mapping = {
        "normal": config.timeouts.normal,
        "background": config.timeouts.background,
        "subagent": config.timeouts.subagent,
    }
    return mapping.get(path, config.cli_timeout)


def resolve_user_timezone(configured: str = "") -> ZoneInfo:
    """Resolve timezone: config value -> host system -> UTC.

    Returns a ``ZoneInfo`` instance. Invalid or empty *configured* values
    fall through to the host OS timezone, then to UTC as last resort.
    """
    trimmed = configured.strip()
    if trimmed:
        try:
            return ZoneInfo(trimmed)
        except (ZoneInfoNotFoundError, KeyError):
            logger.warning("Invalid user_timezone '%s', falling back to host/UTC", trimmed)

    # Try host system timezone via environment or OS-specific detection.
    import os
    import sys

    tz_env = os.environ.get("TZ", "").strip()
    if tz_env:
        try:
            return ZoneInfo(tz_env)
        except (ZoneInfoNotFoundError, KeyError):
            pass

    detected = _detect_host_timezone() if sys.platform == "win32" else _detect_posix_timezone()
    return detected or _SAFE_UTC


def _detect_host_timezone() -> ZoneInfo | None:
    """Detect timezone on Windows via datetime."""
    import datetime

    local_tz = datetime.datetime.now(datetime.UTC).astimezone().tzinfo
    if local_tz is None:
        return None
    tz_name = getattr(local_tz, "key", None) or str(local_tz)
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return None


def _detect_posix_timezone() -> ZoneInfo | None:
    """Detect timezone on POSIX via /etc/localtime symlink."""
    localtime = Path("/etc/localtime")
    if not localtime.is_symlink():
        return None
    target = str(localtime.resolve())
    marker = "/zoneinfo/"
    idx = target.find(marker)
    if idx == -1:
        return None
    candidate = target[idx + len(marker) :]
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, KeyError):
        return None


CLAUDE_MODELS_ORDERED: tuple[str, ...] = ("haiku", "sonnet", "opus")
CLAUDE_MODELS: frozenset[str] = frozenset(CLAUDE_MODELS_ORDERED)

# "auto" is a Gemini-specific alias (Gemini CLI auto-selects the best model).
_GEMINI_ALIASES: frozenset[str] = frozenset({"auto", "pro", "flash", "flash-lite"})

_runtime_gemini: list[frozenset[str]] = [frozenset()]


class ModelRegistry:
    """Provider resolution for models.

    Claude models (haiku, sonnet, opus) are hardcoded.
    Gemini models are hardcoded (parsed from CLI at startup if available).
    Codex models are discovered dynamically at runtime.
    """

    @staticmethod
    def provider_for(model_id: str) -> str:
        """Return the provider for a model ID."""
        if model_id in CLAUDE_MODELS:
            return "claude"
        if (
            model_id in _GEMINI_ALIASES
            or model_id in _runtime_gemini[0]
            or model_id.startswith(("gemini-", "auto-gemini-"))
        ):
            return "gemini"
        return "codex"


def get_gemini_models() -> frozenset[str]:
    """Return dynamically discovered Gemini models (may be empty)."""
    return _runtime_gemini[0]


def set_gemini_models(models: frozenset[str]) -> None:
    """Set runtime Gemini models discovered from local Gemini CLI files.

    Refuses to overwrite with an empty set to prevent cache wipe.
    """
    if not models:
        return
    _runtime_gemini[0] = models


def reset_gemini_models() -> None:
    """Clear runtime Gemini models. For test teardown only."""
    _runtime_gemini[0] = frozenset()
