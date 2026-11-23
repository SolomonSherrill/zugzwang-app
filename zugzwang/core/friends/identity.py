"""The account key and its recovery code (FRIENDS.md rulings A1, A2).

The recovery code encodes a random **160-bit secret** (A2: at least 128). The Ed25519 key is derived
from it, so the code alone restores the key on another computer:

    seed = HKDF-SHA256(secret, salt="zugzwang-friends-v1", info="ed25519-seed", 32 bytes)

Written as 32 Crockford base32 characters in eight groups of four, then one group of four check
characters (the first 20 bits of SHA-256 over the secret), so a mistyped code is caught before any
request: `K7QF-2M9D-XW4P-8RTA-6HVN-…`. Reading is forgiving: case, spaces and dashes are ignored,
and O reads as 0, I and L as 1 (Crockford's rule).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from zugzwang.core.friends import ed25519

SECRET_BYTES = 20
SALT = b"zugzwang-friends-v1"
INFO = b"ed25519-seed"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_READ = {c: i for i, c in enumerate(CROCKFORD)} | {"O": 0, "I": 1, "L": 1}


class RecoveryCodeError(ValueError):
    """A recovery code that cannot be read: the message says why, in words for the user."""


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def _b32(data: bytes) -> str:
    bits, value, out = 0, 0, []
    for b in data:
        value = (value << 8) | b
        bits += 8
        while bits >= 5:
            out.append(CROCKFORD[(value >> (bits - 5)) & 31])
            bits -= 5
    if bits:
        out.append(CROCKFORD[(value << (5 - bits)) & 31])
    return "".join(out)


def _check(secret: bytes) -> str:
    return _b32(hashlib.sha256(b"zugzwang-recovery-check" + secret).digest()[:3])[:4]


def format_code(secret: bytes) -> str:
    if len(secret) != SECRET_BYTES:
        raise ValueError(f"the secret is {SECRET_BYTES} bytes")
    body = _b32(secret)                       # 160 bits = exactly 32 characters
    chars = body + _check(secret)
    return "-".join(chars[i:i + 4] for i in range(0, len(chars), 4))


def parse_code(code: str) -> bytes:
    """The secret a recovery code encodes; RecoveryCodeError when it cannot be one."""
    cleaned = "".join(ch for ch in code.upper() if ch not in " -\t\r\n")
    if len(cleaned) != 36:
        raise RecoveryCodeError(
            f"A recovery code has 36 letters and numbers; this has {len(cleaned)}.")
    bad = sorted({ch for ch in cleaned if ch not in _READ})
    if bad:
        raise RecoveryCodeError(f"A recovery code has no {', '.join(bad)}.")
    value = 0
    for ch in cleaned[:32]:
        value = (value << 5) | _READ[ch]
    secret = value.to_bytes(SECRET_BYTES, "big")
    if _check(secret) != "".join(CROCKFORD[_READ[c]] for c in cleaned[32:]):
        raise RecoveryCodeError("This recovery code does not check out: a character is wrong.")
    return secret


def new_secret() -> bytes:
    return os.urandom(SECRET_BYTES)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Identity:
    """A Friends key, from the recovery secret."""

    secret: bytes

    @property
    def seed(self) -> bytes:
        return hkdf_sha256(self.secret, SALT, INFO, 32)

    @property
    def public_key(self) -> bytes:
        return ed25519.public_key(self.seed)

    @property
    def public_key_b64(self) -> str:
        return b64url(self.public_key)

    @property
    def recovery_code(self) -> str:
        return format_code(self.secret)

    def sign(self, message: bytes) -> bytes:
        return ed25519.sign(self.seed, message)

    @classmethod
    def from_code(cls, code: str) -> "Identity":
        return cls(parse_code(code))

    @classmethod
    def new(cls) -> "Identity":
        return cls(new_secret())
