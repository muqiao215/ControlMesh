"""QR-derived credential store for the Weixin iLink transport."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from ductor_bot.infra.json_store import atomic_json_save, load_json

DEFAULT_WEIXIN_BASE_URL = "https://ilinkai.weixin.qq.com"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredWeixinCredentials:
    """Credentials returned after the iLink QR login is confirmed."""

    token: str
    base_url: str
    account_id: str
    user_id: str


class WeixinCredentialStore:
    """JSON-backed iLink credential store under the user's Ductor home."""

    def __init__(
        self,
        ductor_home: str | Path,
        *,
        relative_path: str = "weixin_store/credentials.json",
    ) -> None:
        self.path = Path(ductor_home).expanduser() / relative_path

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


def _pick_string(value: Mapping[str, object], snake_name: str, camel_name: str) -> str | None:
    snake_value = value.get(snake_name)
    if isinstance(snake_value, str):
        return snake_value
    camel_value = value.get(camel_name)
    return camel_value if isinstance(camel_value, str) else None
