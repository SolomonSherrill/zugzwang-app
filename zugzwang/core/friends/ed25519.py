"""Ed25519 signatures (RFC 8032) through the `cryptography` package (FRIENDS.md ruling Z2, 2026-11-21;
FRIENDS-1 built it in pure Python, replaced by FRIENDS-1B B).

Only what Friends needs: the public key of a 32-byte seed, signing, and verifying (for the tests).
Checked against RFC 8032's test vectors (tests/test_friends_identity.py) and, end to end, against the
server's WebCrypto verification (sidecar/friends_e2e.py). The packaged sidecar freezes the package
(PyInstaller's own hook; measured in review/reports/FRIENDS-1B.md).
"""
from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def _private(seed: bytes) -> Ed25519PrivateKey:
    if len(seed) != 32:
        raise ValueError("an Ed25519 seed is 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(bytes(seed))


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte seed (RFC 8032's "secret key")."""
    return _private(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of *message*."""
    return _private(seed).sign(bytes(message))


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public)).verify(bytes(signature), bytes(message))
    except (InvalidSignature, ValueError):
        return False
    return True
