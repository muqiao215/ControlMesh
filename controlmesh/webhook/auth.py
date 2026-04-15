"""Webhook authentication and rate limiting."""

from __future__ import annotations

import base64
import hmac
import logging
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controlmesh.webhook.models import WebhookEntry

logger = logging.getLogger(__name__)

_HASH_ALGORITHMS: dict[str, str] = {
    "sha256": "sha256",
    "sha1": "sha1",
    "sha512": "sha512",
}


@dataclass(frozen=True, slots=True)
class HmacConfig:
    """HMAC validation parameters extracted from a webhook entry."""

    algorithm: str = "sha256"
    encoding: str = "hex"
    sig_prefix: str = "sha256="
    sig_regex: str = ""
    payload_prefix_regex: str = ""

    @classmethod
    def from_hook(cls, hook: WebhookEntry) -> HmacConfig:
        """Build from a WebhookEntry's HMAC fields."""
        return cls(
            algorithm=hook.hmac_algorithm,
            encoding=hook.hmac_encoding,
            sig_prefix=hook.hmac_sig_prefix,
            sig_regex=hook.hmac_sig_regex,
            payload_prefix_regex=hook.hmac_payload_prefix_regex,
        )


def validate_bearer_token(authorization: str, expected_token: str) -> bool:
    """Check ``Authorization: Bearer <token>`` header value.

    Uses constant-time comparison to prevent timing attacks.
    """
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        logger.warning("Auth failed: invalid token")
        return False
    valid = hmac.compare_digest(authorization[len(prefix) :], expected_token)
    if not valid:
        logger.warning("Auth failed: invalid token")
    return valid


def _extract_signature(signature_value: str, cfg: HmacConfig) -> str | None:
    """Extract the actual signature from a header value, returning None on failure."""
    if cfg.sig_regex:
        m = re.search(cfg.sig_regex, signature_value)
        if not m or not m.group(1):
            logger.warning("HMAC auth failed: sig_regex did not match")
            return None
        return m.group(1)
    if cfg.sig_prefix:
        return signature_value.removeprefix(cfg.sig_prefix)
    return signature_value


def validate_hmac_signature(
    body: bytes,
    signature_value: str,
    secret: str,
    cfg: HmacConfig | None = None,
) -> bool:
    """Validate an HMAC signature with fully configurable parameters."""
    if not signature_value or not secret:
        logger.warning("HMAC auth failed: missing signature or secret")
        return False

    if cfg is None:
        cfg = HmacConfig()

    sig = _extract_signature(signature_value, cfg)
    if sig is None:
        return False

    # Construct payload to sign (optionally prepend extracted prefix)
    signed_payload = body
    if cfg.payload_prefix_regex:
        m = re.search(cfg.payload_prefix_regex, signature_value)
        if m and m.group(1):
            signed_payload = m.group(1).encode() + b"." + body

    # Compute HMAC with configured algorithm
    algo = _HASH_ALGORITHMS.get(cfg.algorithm, "sha256")
    computed = hmac.new(secret.encode(), signed_payload, algo)

    # Encode and compare
    if cfg.encoding == "base64":
        expected = base64.b64encode(computed.digest()).decode()
    else:
        expected = computed.hexdigest()

    valid = hmac.compare_digest(sig, expected)
    if not valid:
        logger.warning(
            "HMAC auth failed: signature mismatch (algo=%s, enc=%s)",
            cfg.algorithm,
            cfg.encoding,
        )
    return valid


def validate_hook_auth(
    hook: WebhookEntry,
    *,
    authorization: str,
    signature_header_value: str,
    body: bytes,
    global_token: str,
) -> bool:
    """Per-hook authentication dispatcher.

    For ``auth_mode="hmac"``: validates signature using the hook's HMAC configuration.
    For ``auth_mode="bearer"`` (default): validates per-hook token with global fallback.
    """
    if hook.auth_mode == "hmac":
        return validate_hmac_signature(
            body,
            signature_header_value,
            hook.hmac_secret,
            cfg=HmacConfig.from_hook(hook),
        )

    # Bearer mode (default for unrecognized auth_mode too)
    expected = hook.token or global_token
    if not expected:
        logger.warning("Auth failed: no token configured for hook=%s", hook.id)
        return False
    return validate_bearer_token(authorization, expected)


class RateLimiter:
    """Simple sliding-window rate limiter using a deque of timestamps."""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._timestamps: deque[float] = deque()

    def check(self) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        while self._timestamps and now - self._timestamps[0] > 60:
            self._timestamps.popleft()
        remaining = self._max - len(self._timestamps)
        logger.debug("Rate limit check remaining=%d", remaining)
        if remaining <= 0:
            logger.warning("Rate limit exceeded")
            return False
        self._timestamps.append(now)
        return True

    def reset(self) -> None:
        """Clear all recorded timestamps."""
        self._timestamps.clear()
