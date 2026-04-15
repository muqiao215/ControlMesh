"""QR-derived credential store for the Weixin iLink transport."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from controlmesh.infra.atomic_io import atomic_bytes_save
from controlmesh.infra.json_store import atomic_json_save, load_json

DEFAULT_WEIXIN_BASE_URL = "https://ilinkai.weixin.qq.com"
WEIXIN_AUTH_STATE_LOGGED_OUT = "logged_out"
WEIXIN_AUTH_STATE_QR_WAITING_SCAN = "qr_waiting_scan"
WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM = "qr_scanned_waiting_confirm"
WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING = "qr_confirmed_persisting"
WEIXIN_AUTH_STATE_LOGGED_IN = "logged_in"
WEIXIN_AUTH_STATE_REAUTH_REQUIRED = "reauth_required"
_WEIXIN_AUTH_STATES = frozenset(
    {
        WEIXIN_AUTH_STATE_LOGGED_OUT,
        WEIXIN_AUTH_STATE_QR_WAITING_SCAN,
        WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM,
        WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING,
        WEIXIN_AUTH_STATE_LOGGED_IN,
        WEIXIN_AUTH_STATE_REAUTH_REQUIRED,
    }
)
_ACTIVE_QR_AUTH_STATES = frozenset(
    {
        WEIXIN_AUTH_STATE_QR_WAITING_SCAN,
        WEIXIN_AUTH_STATE_QR_SCANNED_WAITING_CONFIRM,
        WEIXIN_AUTH_STATE_QR_CONFIRMED_PERSISTING,
    }
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredWeixinCredentials:
    """Credentials returned after the iLink QR login is confirmed."""

    token: str
    base_url: str
    account_id: str
    user_id: str


@dataclass(frozen=True, slots=True)
class WeixinQrLoginState:
    """Persisted QR login progress for restart-safe CLI auth recovery."""

    auth_state: str = WEIXIN_AUTH_STATE_LOGGED_OUT
    qrcode_id: str | None = None
    qrcode_url: str | None = None
    qrcode_created_at: int | None = None
    last_status: str | None = None
    last_polled_at: int | None = None
    updated_at: int | None = None

    @property
    def has_active_qr(self) -> bool:
        return (
            self.auth_state in _ACTIVE_QR_AUTH_STATES
            and self.qrcode_id is not None
            and self.qrcode_url is not None
        )


class WeixinCredentialStore:
    """JSON-backed iLink credential store under the user's ControlMesh home."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "weixin_store/credentials.json",
    ) -> None:
        self.path = Path(controlmesh_home).expanduser() / relative_path

    def load_credentials(self) -> StoredWeixinCredentials | None:
        raw = load_json(self.path)
        if raw is None:
            return None
        try:
            return _coerce_credentials(raw, self.path)
        except (TypeError, ValueError):
            logger.warning("Invalid Weixin credentials format in %s", self.path)
            return None

    def save_credentials(self, credentials: StoredWeixinCredentials) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(self.path, asdict(credentials))
        self._protect_file()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _protect_file(self) -> None:
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)


class WeixinQrLoginStateStore:
    """Persist QR login recovery state under the user's ControlMesh home."""

    def __init__(
        self,
        controlmesh_home: str | Path,
        *,
        relative_path: str = "weixin_store/qr_login_state.json",
        qr_image_relative_path: str = "weixin_store/current_qr.png",
    ) -> None:
        root = Path(controlmesh_home).expanduser()
        self.path = root / relative_path
        self.qr_image_path = root / qr_image_relative_path

    def load(self) -> WeixinQrLoginState:
        raw = load_json(self.path)
        if raw is None:
            return WeixinQrLoginState()
        try:
            return _coerce_qr_login_state(raw, self.path)
        except (TypeError, ValueError):
            logger.warning("Invalid Weixin QR login state format in %s", self.path)
            return WeixinQrLoginState()

    def save(self, state: WeixinQrLoginState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_json_save(self.path, asdict(state))
        self._protect_file(self.path)

    def save_qr_image_bytes(self, content: bytes) -> None:
        self.qr_image_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_bytes_save(self.qr_image_path, content)
        self._protect_file(self.qr_image_path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def clear_qr_image(self) -> None:
        self.qr_image_path.unlink(missing_ok=True)

    @staticmethod
    def _protect_file(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def credentials_from_confirmed_qr_status(
    status: Mapping[str, object],
    *,
    fallback_base_url: str = DEFAULT_WEIXIN_BASE_URL,
) -> StoredWeixinCredentials:
    """Build credentials from a confirmed iLink QR polling payload."""
    token = status.get("bot_token")
    account_id = status.get("ilink_bot_id")
    user_id = status.get("ilink_user_id")
    base_url = status.get("baseurl") or fallback_base_url
    if (
        not isinstance(token, str)
        or not isinstance(account_id, str)
        or not isinstance(user_id, str)
        or not isinstance(base_url, str)
    ):
        raise TypeError("QR login confirmed, but the API did not return bot credentials")
    return StoredWeixinCredentials(
        token=token,
        base_url=base_url,
        account_id=account_id,
        user_id=user_id,
    )


def _coerce_credentials(
    value: Mapping[str, object],
    source: Path,
) -> StoredWeixinCredentials:
    token = value.get("token")
    base_url = _pick_string(value, "base_url", "baseUrl")
    account_id = _pick_string(value, "account_id", "accountId")
    user_id = _pick_string(value, "user_id", "userId")

    if not isinstance(token, str) or base_url is None or account_id is None or user_id is None:
        raise ValueError(f"Invalid Weixin credentials format in {source}")

    return StoredWeixinCredentials(
        token=token,
        base_url=base_url,
        account_id=account_id,
        user_id=user_id,
    )


def _coerce_qr_login_state(
    value: Mapping[str, object],
    source: Path,
) -> WeixinQrLoginState:
    auth_state = _pick_string(value, "auth_state", "authState")
    if auth_state not in _WEIXIN_AUTH_STATES:
        raise ValueError(f"Invalid Weixin QR login state format in {source}")
    qrcode_id = _optional_string(value, "qrcode_id", "qrcodeId")
    qrcode_url = _optional_string(value, "qrcode_url", "qrcodeUrl")
    qrcode_created_at = _optional_int(value, "qrcode_created_at", "qrcodeCreatedAt")
    last_status = _optional_string(value, "last_status", "lastStatus")
    last_polled_at = _optional_int(value, "last_polled_at", "lastPolledAt")
    updated_at = _optional_int(value, "updated_at", "updatedAt")
    return WeixinQrLoginState(
        auth_state=auth_state,
        qrcode_id=qrcode_id,
        qrcode_url=qrcode_url,
        qrcode_created_at=qrcode_created_at,
        last_status=last_status,
        last_polled_at=last_polled_at,
        updated_at=updated_at,
    )


def _pick_string(value: Mapping[str, object], snake_name: str, camel_name: str) -> str | None:
    snake_value = value.get(snake_name)
    if isinstance(snake_value, str):
        return snake_value
    camel_value = value.get(camel_name)
    return camel_value if isinstance(camel_value, str) else None


def _optional_string(value: Mapping[str, object], snake_name: str, camel_name: str) -> str | None:
    picked = _pick_string(value, snake_name, camel_name)
    return picked or None


def _optional_int(value: Mapping[str, object], snake_name: str, camel_name: str) -> int | None:
    snake_value = value.get(snake_name)
    if isinstance(snake_value, int):
        return snake_value
    camel_value = value.get(camel_name)
    return camel_value if isinstance(camel_value, int) else None
