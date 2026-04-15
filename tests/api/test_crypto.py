"""Tests for E2E encryption."""

from __future__ import annotations

import base64

import pytest

pytest.importorskip("nacl", reason="PyNaCl not installed (optional: pip install controlmesh[api])")

from nacl.exceptions import CryptoError

from controlmesh.api.crypto import E2ESession


def _make_pair() -> tuple[E2ESession, E2ESession]:
    """Create a server/client session pair with exchanged keys."""
    server = E2ESession()
    client = E2ESession()
    server.set_remote_key(client.local_pk_b64)
    client.set_remote_key(server.local_pk_b64)
    return server, client


class TestE2ESession:
    def test_keypair_is_32_bytes(self) -> None:
        session = E2ESession()
        pk_bytes = base64.b64decode(session.local_pk_b64)
        assert len(pk_bytes) == 32

    def test_round_trip(self) -> None:
        server, client = _make_pair()
        msg = {"type": "text_delta", "data": "hello world"}
        assert client.decrypt(server.encrypt(msg)) == msg

    def test_bidirectional(self) -> None:
        server, client = _make_pair()
        msg1 = {"type": "result", "text": "response"}
        assert client.decrypt(server.encrypt(msg1)) == msg1
        msg2 = {"type": "message", "text": "input"}
        assert server.decrypt(client.encrypt(msg2)) == msg2

    def test_wire_format_nonce_prepended(self) -> None:
        server, _client = _make_pair()
        encrypted = server.encrypt({"k": "v"})
        raw = base64.b64decode(encrypted)
        # nonce (24) + MAC (16) + encrypted payload
        assert len(raw) > 40

    def test_wrong_key_rejects(self) -> None:
        server, _client = _make_pair()
        attacker = E2ESession()
        attacker.set_remote_key(server.local_pk_b64)
        encrypted = server.encrypt({"secret": "data"})
        with pytest.raises(CryptoError):
            attacker.decrypt(encrypted)

    def test_tampered_ciphertext_rejects(self) -> None:
        server, client = _make_pair()
        encrypted = server.encrypt({"key": "value"})
        raw = bytearray(base64.b64decode(encrypted))
        raw[-1] ^= 0xFF
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(CryptoError):
            client.decrypt(tampered)

    def test_unique_nonces(self) -> None:
        server, _client = _make_pair()
        msg = {"same": "data"}
        assert server.encrypt(msg) != server.encrypt(msg)

    def test_empty_dict(self) -> None:
        server, client = _make_pair()
        msg: dict[str, object] = {}
        assert client.decrypt(server.encrypt(msg)) == msg

    def test_unicode_content(self) -> None:
        server, client = _make_pair()
        msg = {"type": "text_delta", "data": "Umlaute: \u00f6\u00e4\u00fc \u65e5\u672c\u8a9e"}
        assert client.decrypt(server.encrypt(msg)) == msg

    def test_large_payload(self) -> None:
        server, client = _make_pair()
        msg = {"type": "result", "text": "x" * 100_000}
        assert client.decrypt(server.encrypt(msg)) == msg
