#!/usr/bin/env python3
"""Check the update feed as an installed app would read it (BETA-PUB).

    python packaging/verify_update_feed.py [--url URL] [--expect-version V] [--dir ARTIFACTS]

Fetches `latest.json` from the address compiled into beta builds
(`tauri.beta.conf.json`, `plugins.updater.endpoints`), and for every platform in it
downloads the update file from its `url` and verifies its `signature` against the app's
public key (`plugins.updater.pubkey`) — the check Tauri's updater makes before it
installs anything. `--dir` checks local artifacts (`*.sig` beside each file) instead of
downloading. Exit status 1 on any failure.

The signature is minisign's format, which Tauri uses: Ed25519 over the BLAKE2b-512 hash of
the file (algorithm `ED`) or over the file itself (`Ed`), plus a global signature over the
signature and its trusted comment. Ed25519 is RFC 8032's reference verification (section
6), in pure Python so the check needs no extra package.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "desktop" / "src-tauri" / "tauri.beta.conf.json"

# ── Ed25519 verification, RFC 8032 section 6 ─────────────────────────────────
_p = 2 ** 255 - 19
_d = -121665 * pow(121666, _p - 2, _p) % _p
_q = 2 ** 252 + 27742317777372353535851937790883648493
_SQRT_M1 = pow(2, (_p - 1) // 4, _p)


def _add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % _p, (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C, D = 2 * P[3] * Q[3] * _d % _p, 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q):
    return (P[0] * Q[2] - Q[0] * P[2]) % _p == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0


def _recover_x(y, sign):
    if y >= _p:
        return None
    x2 = (y * y - 1) * pow(_d * y * y + 1, _p - 2, _p)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _SQRT_M1 % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_gy = 4 * pow(5, _p - 2, _p) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _p)


def ed25519_verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    A = _decompress(public)
    R = _decompress(sig[:32])
    if A is None or R is None or len(sig) != 64:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _q:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + public + msg).digest(), "little") % _q
    return _equal(_mul(s, _G), _add(R, _mul(h, A)))


# ── minisign, as Tauri writes it ─────────────────────────────────────────────

def public_key(pubkey_b64: str) -> tuple[bytes, bytes]:
    """(key id, 32-byte key) from tauri.conf's `pubkey` (base64 of minisign's .pub file)."""
    line = base64.b64decode(pubkey_b64).decode().splitlines()[1]
    raw = base64.b64decode(line)
    assert raw[:2] == b"Ed" and len(raw) == 42, "not a minisign Ed25519 public key"
    return raw[2:10], raw[10:]


def verify(data: bytes, signature_b64: str, pubkey_b64: str) -> tuple[bool, str]:
    keyid, pk = public_key(pubkey_b64)
    lines = base64.b64decode(signature_b64).decode().splitlines()
    sig = base64.b64decode(lines[1])
    trusted = lines[2].removeprefix("trusted comment: ").encode()
    global_sig = base64.b64decode(lines[3])
    alg, sig_keyid, sig64 = sig[:2], sig[2:10], sig[10:]
    if sig_keyid != keyid:
        return False, f"signed by key {sig_keyid[::-1].hex().upper()}, the app trusts {keyid[::-1].hex().upper()}"
    msg = hashlib.blake2b(data, digest_size=64).digest() if alg == b"ED" else data
    if not ed25519_verify(pk, msg, sig64):
        return False, "file signature does not verify"
    if not ed25519_verify(pk, sig64 + trusted, global_sig):
        return False, "trusted comment signature does not verify"
    return True, trusted.decode()


def fetch(url: str) -> bytes:
    ctx = None
    try:
        import ssl

        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "zugzwang-verify"})
    with urllib.request.urlopen(req, timeout=600, context=ctx) as r:
        return r.read()


def main() -> int:
    conf = json.loads(CONF.read_text(encoding="utf-8"))["plugins"]["updater"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=conf["endpoints"][0])
    ap.add_argument("--expect-version")
    ap.add_argument("--dir", help="verify local artifacts (file + file.sig) instead")
    a = ap.parse_args()
    bad = 0
    if a.dir:
        for sig in sorted(Path(a.dir).glob("*.sig")):
            art = sig.with_suffix("")
            ok, why = verify(art.read_bytes(), sig.read_text().strip(), conf["pubkey"])
            print(f"{'ok  ' if ok else 'FAIL'} {art.name}: {why}")
            bad += not ok
        return 1 if bad else 0
    feed = json.loads(fetch(a.url))
    print(f"{a.url}\n  version {feed['version']}, published {feed.get('pub_date')}, "
          f"platforms {sorted(feed['platforms'])}")
    if a.expect_version and feed["version"] != a.expect_version:
        print(f"FAIL: expected version {a.expect_version}")
        bad += 1
    for key in ("darwin-aarch64", "darwin-x86_64", "windows-x86_64"):
        entry = feed["platforms"].get(key)
        if entry is None:
            print(f"FAIL {key}: missing from the feed")
            bad += 1
            continue
        data = fetch(entry["url"])
        ok, why = verify(data, entry["signature"], conf["pubkey"])
        print(f"{'ok  ' if ok else 'FAIL'} {key}: {entry['url']} ({len(data)} bytes) — {why}")
        bad += not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
