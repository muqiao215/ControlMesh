"""CLI auth detection via filesystem checks."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from importlib.util import find_spec
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, unique
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

from controlmesh.cli.gemini_utils import find_gemini_cli
from controlmesh.config import NULLISH_TEXT_VALUES

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_GEMINI_AUTH_ENV_KEYS = frozenset(
    {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"}
)
_GEMINI_SELECTED_AUTH_TYPES = frozenset(
    {"oauth-personal", "gemini-api-key", "vertex-ai", "compute-default-credentials", "cloud-shell"}
)
_GEMINI_NON_API_KEY_AUTH_TYPES = frozenset(
    {"oauth-personal", "vertex-ai", "compute-default-credentials", "cloud-shell"}
)
_CLAW_AUTH_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "XAI_API_KEY",
        "DASHSCOPE_API_KEY",
    }
)
_OPENCODE_AUTH_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GITHUB_TOKEN",
        "VERTEXAI_PROJECT",
        "VERTEXAI_LOCATION",
        "GROQ_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_API_VERSION",
        "LOCAL_ENDPOINT",
    }
)


@unique
class AuthStatus(StrEnum):
    """Provider authentication state."""

    AUTHENTICATED = "authenticated"
    INSTALLED = "installed"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Result of a provider auth check."""

    provider: str
    status: AuthStatus
    auth_file: Path | None = None
    auth_age: datetime | None = None
    diagnostic: str = ""

    @property
    def is_authenticated(self) -> bool:
        return self.status == AuthStatus.AUTHENTICATED

    @property
    def age_human(self) -> str:
        """Human-readable age of the auth file."""
        if self.auth_age is None:
            return ""
        return format_age(self.auth_age)


def format_age(dt: datetime) -> str:
    """Format a datetime as a human-readable relative age string."""
    delta = datetime.now(UTC) - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def check_claude_auth() -> AuthResult:
    """Check Claude Code CLI auth via credentials file, env var, or CLI fallback."""
    claude_dir = Path.home() / ".claude"
    credentials = claude_dir / ".credentials.json"

    # Fast path: credentials file (standard OAuth login).
    if credentials.is_file():
        mtime = datetime.fromtimestamp(credentials.stat().st_mtime, tz=UTC)
        result = AuthResult("claude", AuthStatus.AUTHENTICATED, credentials, mtime)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    # ANTHROPIC_API_KEY environment variable.
    if _has_nonempty_env("ANTHROPIC_API_KEY"):
        result = AuthResult("claude", AuthStatus.AUTHENTICATED)
        logger.debug("Auth check provider=%s status=%s (env key)", result.provider, result.status)
        return result

    # Fallback: ask the CLI itself (covers managed keys, OAuth tokens, etc.).
    if _claude_cli_logged_in():
        result = AuthResult("claude", AuthStatus.AUTHENTICATED)
        logger.debug("Auth check provider=%s status=%s (cli)", result.provider, result.status)
        return result

    if claude_dir.is_dir():
        result = AuthResult("claude", AuthStatus.INSTALLED)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    result = AuthResult("claude", AuthStatus.NOT_FOUND)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def _claude_cli_logged_in() -> bool:
    """Run ``claude auth status`` and return True when the CLI reports logged-in."""
    try:
        proc = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        data = json.loads(proc.stdout)
        return data.get("loggedIn") is True
    except (
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return False


def check_codex_auth() -> AuthResult:
    """Check Codex CLI auth via ``$CODEX_HOME/auth.json``, env var, or install markers."""
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    auth_file = codex_home / "auth.json"

    # Fast path: auth.json credential file.
    if auth_file.is_file():
        mtime = datetime.fromtimestamp(auth_file.stat().st_mtime, tz=UTC)
        result = AuthResult("codex", AuthStatus.AUTHENTICATED, auth_file, mtime)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    # OPENAI_API_KEY environment variable.
    if _has_nonempty_env("OPENAI_API_KEY"):
        result = AuthResult("codex", AuthStatus.AUTHENTICATED)
        logger.debug("Auth check provider=%s status=%s (env key)", result.provider, result.status)
        return result

    # Installation indicators: version.json or config.toml.
    if (codex_home / "version.json").is_file() or (codex_home / "config.toml").is_file():
        result = AuthResult("codex", AuthStatus.INSTALLED)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    result = AuthResult("codex", AuthStatus.NOT_FOUND)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def check_openai_agents_auth() -> AuthResult:
    """Check optional OpenAI Agents SDK backend availability and API-key auth."""
    if not _openai_agents_sdk_installed():
        result = AuthResult("openai_agents", AuthStatus.NOT_FOUND)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    if _has_nonempty_env("OPENAI_API_KEY"):
        result = AuthResult("openai_agents", AuthStatus.AUTHENTICATED)
        logger.debug("Auth check provider=%s status=%s (env key)", result.provider, result.status)
        return result

    result = AuthResult("openai_agents", AuthStatus.INSTALLED)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def check_claw_auth() -> AuthResult:
    """Check claw-code runtime availability and minimal auth presence."""
    if which("claw") is None:
        result = AuthResult("claw", AuthStatus.NOT_FOUND)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    if any(_has_nonempty_env(name) for name in _CLAW_AUTH_ENV_KEYS):
        result = AuthResult("claw", AuthStatus.AUTHENTICATED)
        logger.debug("Auth check provider=%s status=%s (env key)", result.provider, result.status)
        return result

    result = AuthResult("claw", AuthStatus.INSTALLED)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def check_opencode_auth() -> AuthResult:
    """Check opencode runtime availability and common auth/config surfaces."""
    if which("opencode") is None:
        result = AuthResult("opencode", AuthStatus.NOT_FOUND)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    if any(_has_nonempty_env(name) for name in _OPENCODE_AUTH_ENV_KEYS):
        diagnostic = _opencode_runnable_diagnostic()
        status = AuthStatus.AUTHENTICATED if not diagnostic else AuthStatus.INSTALLED
        result = AuthResult("opencode", status, diagnostic=diagnostic)
        logger.debug("Auth check provider=%s status=%s (env key)", result.provider, result.status)
        return result

    auth_file = _find_opencode_auth_file()
    auth_age = None
    auth_providers: set[str] = set()
    if auth_file is not None:
        auth_age = datetime.fromtimestamp(auth_file.stat().st_mtime, tz=UTC)
        auth_providers = _read_opencode_auth_provider_ids(auth_file)

    installed_config: Path | None = None
    installed_age: datetime | None = None
    for config_file in _iter_opencode_config_files():
        auth_source, source_age = _read_opencode_config_auth(
            config_file,
            auth_file=auth_file,
            auth_provider_ids=auth_providers,
        )
        if auth_source is not None:
            diagnostic = _opencode_runnable_diagnostic()
            status = AuthStatus.AUTHENTICATED if not diagnostic else AuthStatus.INSTALLED
            result = AuthResult("opencode", status, auth_source, source_age, diagnostic=diagnostic)
            logger.debug(
                "Auth check provider=%s status=%s (config key)",
                result.provider,
                result.status,
            )
            return result
        if installed_config is None:
            installed_config = config_file
            installed_age = datetime.fromtimestamp(config_file.stat().st_mtime, tz=UTC)

    if auth_file is not None and auth_providers:
        diagnostic = _opencode_runnable_diagnostic()
        status = AuthStatus.AUTHENTICATED if not diagnostic else AuthStatus.INSTALLED
        result = AuthResult("opencode", status, auth_file, auth_age, diagnostic=diagnostic)
        logger.debug(
            "Auth check provider=%s status=%s (auth file)",
            result.provider,
            result.status,
        )
        return result

    if installed_config is not None:
        diagnostic = _missing_runtime_env_diagnostic("opencode", _OPENCODE_AUTH_ENV_KEYS)
        result = AuthResult(
            "opencode",
            AuthStatus.INSTALLED,
            installed_config,
            installed_age,
            diagnostic=diagnostic,
        )
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    diagnostic = _missing_runtime_env_diagnostic("opencode", _OPENCODE_AUTH_ENV_KEYS)
    result = AuthResult("opencode", AuthStatus.INSTALLED, diagnostic=diagnostic)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def _opencode_runnable_diagnostic() -> str:
    """Return a diagnostic when OpenCode config exists but no runnable model resolves."""
    from controlmesh.cli.opencode_discovery import resolve_opencode_runnable_model_sync

    model = resolve_opencode_runnable_model_sync()
    if model:
        return ""
    return "OpenCode is installed/configured, but no runnable runtime model passed preflight."


def _openai_agents_sdk_installed() -> bool:
    return find_spec("agents") is not None


def _find_opencode_config_file() -> Path | None:
    for path in _iter_opencode_config_files():
        return path
    return None


def _iter_opencode_config_roots() -> tuple[Path, ...]:
    home = Path.home()
    default_xdg = home / ".config"
    configured_xdg = Path(os.environ.get("XDG_CONFIG_HOME", default_xdg))
    roots: list[Path] = []
    for root in (configured_xdg, default_xdg):
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _iter_opencode_config_files() -> tuple[Path, ...]:
    home = Path.home()
    candidates: list[Path] = [home / ".opencode.json"]
    for root in _iter_opencode_config_roots():
        candidates.extend(
            (
                root / "opencode" / ".opencode.json",
                root / "opencode" / "opencode.jsonc",
                root / "opencode" / "opencode.json",
            )
        )
    return tuple(path for path in candidates if path.is_file())


def _iter_opencode_data_roots() -> tuple[Path, ...]:
    home = Path.home()
    default_xdg = home / ".local" / "share"
    configured_xdg = Path(os.environ.get("XDG_DATA_HOME", default_xdg))
    roots: list[Path] = []
    for root in (configured_xdg, default_xdg):
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def _find_opencode_auth_file() -> Path | None:
    for root in _iter_opencode_data_roots():
        path = root / "opencode" / "auth.json"
        if path.is_file():
            return path
    return None


def _find_opencode_runtime_config_file() -> Path | None:
    for root in _iter_opencode_config_roots():
        for path in (
            root / "opencode" / "opencode.jsonc",
            root / "opencode" / "opencode.json",
        ):
            if path.is_file():
                return path
    return None


def _load_opencode_json(path: Path) -> dict[str, object] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Accept simple JSONC config files without adding a new parser dependency.
        stripped = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)
        stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.MULTILINE)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None


def _read_opencode_config_auth(
    config_file: Path,
    *,
    auth_file: Path | None = None,
    auth_provider_ids: set[str] | None = None,
) -> tuple[Path | None, datetime | None]:
    data = _load_opencode_json(config_file)
    if not isinstance(data, dict):
        return None, None
    if _opencode_env_uses_auth_signal(data.get("env")):
        return config_file, datetime.fromtimestamp(config_file.stat().st_mtime, tz=UTC)
    for provider_cfg in _iter_opencode_provider_configs(data):
        if _opencode_provider_uses_auth_signal(provider_cfg):
            return config_file, datetime.fromtimestamp(config_file.stat().st_mtime, tz=UTC)
    provider_ids = _read_opencode_runtime_provider_ids(data)
    if auth_file is not None and auth_provider_ids and (
        not provider_ids or provider_ids & auth_provider_ids
    ):
        return auth_file, datetime.fromtimestamp(auth_file.stat().st_mtime, tz=UTC)
    return None, None


def _read_opencode_runtime_provider_ids(data: dict[str, object]) -> set[str]:
    provider_ids: set[str] = set()
    for key in ("provider", "providers"):
        raw = data.get(key)
        if not isinstance(raw, dict):
            continue
        for provider_id, cfg in raw.items():
            if isinstance(provider_id, str) and provider_id.strip() and isinstance(cfg, dict):
                provider_ids.add(provider_id.strip())
    return provider_ids


def _iter_opencode_provider_configs(data: dict[str, object]) -> tuple[dict[str, object], ...]:
    configs: list[dict[str, object]] = []
    for key in ("provider", "providers"):
        raw = data.get(key)
        if not isinstance(raw, dict):
            continue
        configs.extend(cfg for cfg in raw.values() if isinstance(cfg, dict))
    return tuple(configs)


def _read_opencode_model_declaration(data: dict[str, object]) -> tuple[str, bool]:
    """Return ``(model, is_explicit)`` from runtime config data."""
    model = data.get("model")
    if isinstance(model, str) and model.strip():
        return _normalize_opencode_model_name(model), True

    env_cfg = data.get("env")
    if not isinstance(env_cfg, dict):
        return "", False

    for key in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_REASONING_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    ):
        value = env_cfg.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_opencode_model_name(value), False
    return "", False


def read_opencode_default_model() -> str:
    """Return the configured OpenCode default model, if one is declared locally."""
    config_file = _find_opencode_runtime_config_file()
    if config_file is None:
        return ""
    data = _load_opencode_json(config_file)
    if not isinstance(data, dict):
        return ""
    model, _is_explicit = _read_opencode_model_declaration(data)
    return model


def read_opencode_primary_provider() -> str:
    """Return the most likely active OpenCode provider from runtime config/auth."""
    config_file = _find_opencode_runtime_config_file()
    data: dict[str, object] | None = None
    provider_ids: set[str] = set()
    if config_file is not None:
        loaded = _load_opencode_json(config_file)
        if isinstance(loaded, dict):
            data = loaded
            provider_ids = _read_opencode_runtime_provider_ids(loaded)

    if data is not None:
        configured_model, _is_explicit = _read_opencode_model_declaration(data)
        if "/" in configured_model:
            model_provider = configured_model.split("/", 1)[0].strip()
            if model_provider and (not provider_ids or model_provider in provider_ids):
                return model_provider

    if len(provider_ids) == 1:
        return next(iter(provider_ids))

    auth_file = _find_opencode_auth_file()
    auth_provider_ids = _read_opencode_auth_provider_ids(auth_file) if auth_file is not None else set()
    overlap = provider_ids & auth_provider_ids
    if len(overlap) == 1:
        return next(iter(overlap))
    if not provider_ids and len(auth_provider_ids) == 1:
        return next(iter(auth_provider_ids))
    return ""


def opencode_model_uses_runtime_env_default(model: str) -> bool:
    """Return True when *model* is supplied by env-backed OpenCode defaults."""
    normalized = _normalize_opencode_model_name(model)
    if not normalized:
        return False
    config_file = _find_opencode_runtime_config_file()
    if config_file is None:
        return False
    data = _load_opencode_json(config_file)
    if not isinstance(data, dict):
        return False
    configured, is_explicit = _read_opencode_model_declaration(data)
    return bool(configured) and not is_explicit and configured == normalized


def _normalize_opencode_model_name(value: str) -> str:
    """Normalize OpenCode model declarations into ControlMesh-facing ids."""
    model = value.strip()
    if not model:
        return ""
    if "/" in model:
        return model
    if model.upper().startswith("GLM-"):
        return f"zhipuai/{model.lower()}"
    return model


def _read_opencode_auth_provider_ids(auth_file: Path) -> set[str]:
    data = _load_opencode_json(auth_file)
    if not isinstance(data, dict):
        return set()
    provider_ids: set[str] = set()
    for provider_id, provider_cfg in data.items():
        if not isinstance(provider_id, str) or not provider_id.strip():
            continue
        if isinstance(provider_cfg, dict) and _opencode_auth_entry_has_signal(provider_cfg):
            provider_ids.add(provider_id.strip())
    return provider_ids


def check_gemini_auth() -> AuthResult:
    """Check Gemini CLI auth via OAuth cache, env/.env keys, and Gemini settings."""
    try:
        find_gemini_cli()
    except FileNotFoundError:
        result = AuthResult("gemini", AuthStatus.NOT_FOUND)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    gemini_home = _gemini_home_dir()

    oauth_file = gemini_home / "oauth_creds.json"
    if _is_nonempty_file(oauth_file):
        mtime = datetime.fromtimestamp(oauth_file.stat().st_mtime, tz=UTC)
        result = AuthResult("gemini", AuthStatus.AUTHENTICATED, oauth_file, mtime)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    auth_file, auth_age = _gemini_key_auth_source(gemini_home)
    if auth_file is not None or auth_age is not None or _gemini_has_env_auth():
        result = AuthResult("gemini", AuthStatus.AUTHENTICATED, auth_file, auth_age)
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    selected_result = _gemini_selected_type_auth(gemini_home)
    if selected_result is not None:
        result = selected_result
        logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
        return result

    result = AuthResult("gemini", AuthStatus.INSTALLED)
    logger.debug("Auth check provider=%s status=%s", result.provider, result.status)
    return result


def _gemini_home_dir() -> Path:
    base = Path(os.environ.get("GEMINI_CLI_HOME", str(Path.home())))
    return base / ".gemini"


def _has_nonempty_env(name: str) -> bool:
    return bool(_normalize_key_like_value(os.environ.get(name, "")))


def _missing_runtime_env_diagnostic(provider: str, keys: set[str] | frozenset[str]) -> str:
    """Describe when ``~/.controlmesh/.env`` has provider auth keys but process env does not."""
    controlmesh_env = _controlmesh_env_path()
    dotenv_keys = _read_dotenv_keys_generic(controlmesh_env)
    present_in_dotenv = sorted(key for key in keys if key in dotenv_keys)
    present_in_env = sorted(key for key in keys if _has_nonempty_env(key))
    if not present_in_dotenv or present_in_env:
        return ""
    joined = ", ".join(present_in_dotenv)
    return (
        f"{provider} auth keys exist in {controlmesh_env} but are missing from the current process "
        f"environment: {joined}. If ControlMesh runs as a service, make sure the service loads that "
        "env file."
    )


def _is_nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _discover_gemini_dotenv_keys(gemini_home: Path) -> tuple[set[str], Path | None]:
    keys: set[str] = set()
    source: Path | None = None
    # Gemini CLI checks ~/.gemini/.env first, then ~/.env
    for path in (gemini_home / ".env", gemini_home.parent / ".env"):
        file_keys = _read_dotenv_keys(path)
        if file_keys:
            keys |= file_keys
            if source is None:
                source = path
    return keys, source


def _gemini_has_env_auth() -> bool:
    has_key = _has_nonempty_env("GEMINI_API_KEY") or _has_nonempty_env("GOOGLE_API_KEY")
    has_vertex = _has_nonempty_env("GOOGLE_CLOUD_PROJECT") and _has_nonempty_env(
        "GOOGLE_CLOUD_LOCATION"
    )
    return has_key or has_vertex


def _gemini_key_auth_source(gemini_home: Path) -> tuple[Path | None, datetime | None]:
    """Return file-based auth source for Gemini API-key style auth, if available."""
    dotenv_keys, dotenv_file = _discover_gemini_dotenv_keys(gemini_home)
    has_dotenv_key = "GEMINI_API_KEY" in dotenv_keys or "GOOGLE_API_KEY" in dotenv_keys
    has_dotenv_vertex = {
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    }.issubset(dotenv_keys)
    if has_dotenv_key or has_dotenv_vertex:
        if dotenv_file is None:
            return None, None
        return dotenv_file, datetime.fromtimestamp(dotenv_file.stat().st_mtime, tz=UTC)

    controlmesh_key, controlmesh_config_path = read_controlmesh_gemini_api_key()
    if controlmesh_key and controlmesh_config_path is not None:
        return controlmesh_config_path, datetime.fromtimestamp(
            controlmesh_config_path.stat().st_mtime, tz=UTC
        )
    return None, None


def _gemini_selected_type_auth(gemini_home: Path) -> AuthResult | None:
    settings_file = gemini_home / "settings.json"
    selected_type = read_gemini_selected_auth_type(settings_file)
    if selected_type == "oauth-personal":
        accounts_file = gemini_home / "google_accounts.json"
        if _has_active_google_account(accounts_file):
            mtime = datetime.fromtimestamp(accounts_file.stat().st_mtime, tz=UTC)
            return AuthResult("gemini", AuthStatus.AUTHENTICATED, accounts_file, mtime)
        return None
    if selected_type == "gemini-api-key":
        # Treat explicit API-key mode selection as authenticated. The key itself
        # may come from external sources (e.g. shell/profile/secret store) that
        # are not reliably discoverable via filesystem probes.
        mtime = datetime.fromtimestamp(settings_file.stat().st_mtime, tz=UTC)
        return AuthResult("gemini", AuthStatus.AUTHENTICATED, settings_file, mtime)
    if selected_type in _GEMINI_SELECTED_AUTH_TYPES:
        mtime = datetime.fromtimestamp(settings_file.stat().st_mtime, tz=UTC)
        return AuthResult("gemini", AuthStatus.AUTHENTICATED, settings_file, mtime)
    return None


def _read_dotenv_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    found: set[str] = set()
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            key, separator, value = line.partition("=")
            if separator != "=":
                continue
            key = key.strip()
            if key not in _GEMINI_AUTH_ENV_KEYS:
                continue
            parsed = _normalize_dotenv_value(value)
            if parsed:
                found.add(key)
    except OSError:
        return set()
    return found


def _read_dotenv_keys_generic(path: Path) -> set[str]:
    """Return all non-empty dotenv keys in *path*."""
    if not path.is_file():
        return set()
    found: set[str] = set()
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line.removeprefix("export ").strip()
            key, separator, value = line.partition("=")
            if separator != "=":
                continue
            key = key.strip()
            if not key:
                continue
            if _normalize_dotenv_value(value):
                found.add(key)
    except OSError:
        return set()
    return found


def _normalize_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in {'"', "'"} and value[-1:] == value[0]:
        return _normalize_key_like_value(value[1:-1].strip())
    return _normalize_key_like_value(value.split("#", 1)[0].strip())


def read_gemini_selected_auth_type(settings_file: Path) -> str | None:
    if not settings_file.is_file():
        return None
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    selected: object | None = None
    if isinstance(data, dict):
        security = data.get("security")
        if isinstance(security, dict):
            auth = security.get("auth")
            if isinstance(auth, dict):
                selected = auth.get("selectedType")

    if isinstance(selected, str) and selected:
        return selected
    return None


def read_controlmesh_gemini_api_key() -> tuple[str | None, Path | None]:
    """Read ``gemini_api_key`` from ``~/.controlmesh/config/config.json``.

    Returns ``(key, path)`` when configured, otherwise ``(None, None)``.
    """
    config_path = _controlmesh_config_path()
    if not config_path.is_file():
        return None, None

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None, None

    if not isinstance(data, dict):
        return None, None

    raw = data.get("gemini_api_key")
    if isinstance(raw, str):
        key = _normalize_key_like_value(raw)
        if key:
            return key, config_path
    return None, None


def gemini_api_key_mode_selected(settings_file: Path) -> bool:
    """Return True when Gemini config indicates API-key mode (or no explicit mode)."""
    selected_type = read_gemini_selected_auth_type(settings_file)
    if selected_type is None:
        return True
    if selected_type in _GEMINI_NON_API_KEY_AUTH_TYPES:
        return False
    return selected_type == "gemini-api-key"


def gemini_uses_api_key_mode() -> bool:
    """Return True when Gemini settings explicitly use API-key auth mode."""
    settings_file = _gemini_home_dir() / "settings.json"
    return read_gemini_selected_auth_type(settings_file) == "gemini-api-key"


def _controlmesh_config_path() -> Path:
    from controlmesh.workspace.paths import resolve_paths

    return resolve_paths().config_path


def _controlmesh_env_path() -> Path:
    from controlmesh.workspace.paths import resolve_paths

    return resolve_paths().env_file


def _has_active_google_account(accounts_file: Path) -> bool:
    if not accounts_file.is_file():
        return False
    try:
        data = json.loads(accounts_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    active = data.get("active")
    return isinstance(active, str) and bool(active.strip())


def _normalize_key_like_value(raw: str) -> str:
    value = raw.strip()
    if not value or value.lower() in NULLISH_TEXT_VALUES:
        return ""
    return value


def _opencode_provider_uses_auth_signal(provider_cfg: dict[str, object]) -> bool:
    api_key = _normalize_key_like_value(str(provider_cfg.get("apiKey", "")))
    if not api_key:
        return False
    if api_key.startswith("env."):
        return api_key[4:] in _OPENCODE_AUTH_ENV_KEYS
    return True


def _opencode_auth_entry_has_signal(provider_cfg: dict[str, object]) -> bool:
    for key in ("key", "token", "apiKey", "api_key"):
        raw = provider_cfg.get(key)
        if isinstance(raw, str) and _normalize_key_like_value(raw):
            return True
    return False


def _opencode_env_uses_auth_signal(env_cfg: object) -> bool:
    if not isinstance(env_cfg, dict):
        return False
    for key in _OPENCODE_AUTH_ENV_KEYS:
        raw = env_cfg.get(key)
        if isinstance(raw, str) and _normalize_key_like_value(raw):
            return True
    return False


_CHECKERS: dict[str, Callable[[], AuthResult]] = {
    "claude": check_claude_auth,
    "codex": check_codex_auth,
    "openai_agents": check_openai_agents_auth,
    "claw": check_claw_auth,
    "opencode": check_opencode_auth,
    "gemini": check_gemini_auth,
}


def check_all_auth() -> dict[str, AuthResult]:
    """Check auth for all known providers."""
    return {name: fn() for name, fn in _CHECKERS.items()}
