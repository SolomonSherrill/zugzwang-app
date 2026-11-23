"""FRIENDS-1 C: the account key, its recovery code, and where it is kept (rulings A1, A2)."""
import os
import stat
import sys

import pytest

from zugzwang.core.friends import ed25519
from zugzwang.core.friends.identity import (SECRET_BYTES, Identity, RecoveryCodeError, format_code,
                                            hkdf_sha256, parse_code)
from zugzwang.core.friends.keystore import FileKeystore, Keystore, select_keystore

# RFC 8032 section 7.1, TEST 1, TEST 2 and TEST 3 (FRIENDS-1B B: kept through the move to `cryptography`)
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


@pytest.mark.parametrize("seed,pub,msg,sig", VECTORS)
def test_ed25519_matches_rfc8032(seed, pub, msg, sig):
    s, m = bytes.fromhex(seed), bytes.fromhex(msg)
    assert ed25519.public_key(s).hex() == pub
    assert ed25519.sign(s, m).hex() == sig
    assert ed25519.verify(bytes.fromhex(pub), m, bytes.fromhex(sig))
    assert not ed25519.verify(bytes.fromhex(pub), m + b"x", bytes.fromhex(sig))


def test_ed25519_refuses_malformed_input():
    _, pub, _, sig = VECTORS[0]
    with pytest.raises(ValueError):
        ed25519.public_key(b"short")
    assert not ed25519.verify(bytes.fromhex(pub)[:31], b"", bytes.fromhex(sig))
    assert not ed25519.verify(bytes.fromhex(pub), b"", bytes.fromhex(sig)[:63])
    assert not ed25519.verify(b"\xff" * 32, b"", bytes.fromhex(sig))   # not a point on the curve


def test_ed25519_is_the_cryptography_package():
    """Ruling Z2 (2026-11-21): the sidecar signs through `cryptography`, not hand-written curve code."""
    import inspect
    src = inspect.getsource(ed25519)
    assert "from cryptography.hazmat.primitives.asymmetric.ed25519 import" in src
    assert "_P = 2 ** 255 - 19" not in src


def test_hkdf_matches_rfc5869_case_1():
    okm = hkdf_sha256(bytes.fromhex("0b" * 22), bytes.fromhex("000102030405060708090a0b0c"),
                      bytes.fromhex("f0f1f2f3f4f5f6f7f8f9"), 42)
    assert okm.hex() == ("3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
                         "34007208d5b887185865")


def test_the_secret_is_at_least_128_bits_and_the_code_round_trips():
    assert SECRET_BYTES * 8 >= 128
    ident = Identity.new()
    code = ident.recovery_code
    groups = code.split("-")
    assert len(groups) == 9 and all(len(g) == 4 for g in groups)
    assert parse_code(code) == ident.secret
    # forgiving: case, spaces, no dashes, O for 0 and I/L for 1
    messy = code.lower().replace("-", " ").replace("0", "o").replace("1", "l")
    assert parse_code(messy) == ident.secret


def test_a_mistyped_code_is_caught_before_any_request():
    code = Identity.new().recovery_code
    i = 3 if code[3] != "A" else 5
    typo = code[:i] + ("A" if code[i] != "A" else "B") + code[i + 1:]
    with pytest.raises(RecoveryCodeError, match="does not check out"):
        parse_code(typo)
    with pytest.raises(RecoveryCodeError, match="36"):
        parse_code(code[:-5])
    with pytest.raises(RecoveryCodeError, match="no U"):
        parse_code("U" + code[1:])


def test_recovery_restores_the_same_key_on_another_computer(tmp_path):
    first = Identity.new()
    store_a = FileKeystore(tmp_path / "computer_a.json")
    store_a.set(first.secret.hex())
    # another computer: only the code
    second = Identity.from_code(first.recovery_code)
    store_b = FileKeystore(tmp_path / "computer_b.json")
    store_b.set(second.secret.hex())
    assert Identity(bytes.fromhex(store_b.get())).public_key == first.public_key
    sig = second.sign(b"request")
    assert ed25519.verify(first.public_key, b"request", sig)


def test_file_keystore_is_private_and_deletable(tmp_path):
    ks = FileKeystore(tmp_path / "k.json")
    assert ks.get() is None
    ks.set("ab" * 20)
    assert ks.get() == "ab" * 20
    if sys.platform != "win32":     # Windows has no POSIX modes (its CI found 0o666; BETA-5 D)
        assert stat.S_IMODE(os.stat(tmp_path / "k.json").st_mode) == 0o600
    ks.delete()
    assert ks.get() is None


def test_the_suite_never_reaches_a_real_keychain(tmp_path):
    # tests/conftest.py points ZUGZWANG_KEYSTORE at a file in each test's folder
    ks = select_keystore()
    assert isinstance(ks, FileKeystore)
    assert str(ks.path).startswith(str(tmp_path))


def test_no_keystore(monkeypatch):
    monkeypatch.setenv("ZUGZWANG_KEYSTORE", "none")
    ks = select_keystore()
    assert type(ks) is Keystore and not ks.available


@pytest.mark.skipif(os.environ.get("ZUGZWANG_TEST_MAC_KEYCHAIN") != "1",
                    reason="opt-in: makes and deletes a temporary macOS keychain file")
def test_macos_keychain_round_trip_in_a_temporary_keychain(tmp_path):
    import subprocess
    from zugzwang.core.friends.keystore import MacKeychain
    kc = str(tmp_path / "zz-test.keychain-db")
    before = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True,
                            text=True).stdout.split()
    subprocess.run(["security", "create-keychain", "-p", "zz-test", kc], check=True)
    try:
        subprocess.run(["security", "unlock-keychain", "-p", "zz-test", kc], check=True)
        ks = MacKeychain(keychain=kc)
        assert ks.get() is None
        ks.set("cd" * 20)
        assert ks.get() == "cd" * 20
        ks.delete()
        assert ks.get() is None
    finally:
        subprocess.run(["security", "delete-keychain", kc])
        subprocess.run(["security", "list-keychains", "-d", "user", "-s",
                        *[k.strip('"') for k in before]])
