"""End-to-end encryption for WebSocket API sessions.

Uses NaCl Box (Curve25519-XSalsa20-Poly1305) for authenticated encryption.
Each WebSocket session uses ephemeral keypairs for forward secrecy.

Wire format: base64(nonce_24 + ciphertext_with_mac)
"""

from __future__ import annotations

import base64
import json
from typing import Any

from nacl.public import Box, PrivateKey, PublicKey


class E2ESession:
    """Per-connection E2E encryption session with ephemeral keypair."""

    __slots__ = ("_box", "_sk", "local_pk_b64")

    def __init__(self) -> None:
        self._sk: PrivateKey = PrivateKey.generate()
        self.local_pk_b64: str = base64.b64encode(bytes(self._sk.public_key)).decode()
        self._box: Box | None = None

    def set_remote_key(self, remote_pk_b64: str) -> None:
        """Compute shared key from remote public key.  Call before encrypt/decrypt."""
        remote_pk = PublicKey(base64.b64decode(remote_pk_b64))
        self._box = Box(self._sk, remote_pk)

    def encrypt(self, data: dict[str, Any]) -> str:
        """Encrypt a dict to base64(nonce + ciphertext)."""
        if self._box is None:
            msg = "E2E session not initialized -- call set_remote_key() first"
            raise RuntimeError(msg)
        plaintext = json.dumps(data, separators=(",", ":")).encode()
        encrypted = self._box.encrypt(plaintext)
        return base64.b64encode(bytes(encrypted)).decode()

    def decrypt(self, frame: str) -> dict[str, Any]:
        """Decrypt a base64 frame.  Raises ``nacl.exceptions.CryptoError`` on failure."""
        if self._box is None:
            msg = "E2E session not initialized -- call set_remote_key() first"
            raise RuntimeError(msg)
        raw = base64.b64decode(frame)
        plaintext = self._box.decrypt(raw)
        result: dict[str, Any] = json.loads(plaintext)
        return result
