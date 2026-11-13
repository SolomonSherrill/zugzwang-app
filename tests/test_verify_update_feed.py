"""The update-feed checker (`packaging/verify_update_feed.py`, BETA-PUB) verifies what
Tauri's updater verifies. Fixture: a file signed by `tauri signer` with a throwaway key made
for this test (the key was deleted; only its public half is kept), never the real one."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "update_sig"
_spec = importlib.util.spec_from_file_location("verify_update_feed",
                                               ROOT / "packaging" / "verify_update_feed.py")
vuf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vuf)

PUB = (FIX / "throwaway.key.pub").read_text().strip()
SIG = (FIX / "update.bin.sig").read_text().strip()
DATA = (FIX / "update.bin").read_bytes()


def test_a_signed_file_verifies():
    ok, why = vuf.verify(DATA, SIG, PUB)
    assert ok, why


def test_a_changed_file_does_not():
    ok, why = vuf.verify(DATA + b"x", SIG, PUB)
    assert not ok and "does not verify" in why


def test_another_key_does_not():
    real = json.loads((ROOT / "desktop/src-tauri/tauri.beta.conf.json").read_text())
    ok, why = vuf.verify(DATA, SIG, real["plugins"]["updater"]["pubkey"])
    assert not ok and "signed by key" in why


def test_rfc8032_test_vector_1():
    """RFC 8032 section 7.1, TEST 1 (empty message)."""
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
                        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert vuf.ed25519_verify(pk, b"", sig)
    assert not vuf.ed25519_verify(pk, b"x", sig)
