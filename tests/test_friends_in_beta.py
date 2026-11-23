"""BETA-5 C (ruling L9, 2026-11-22): Friends is on in every build, and a packaged build keeps its key under a
keychain entry of its own, so a dev run and an installed beta on one computer never overwrite each other's key."""
from pathlib import Path

import zugzwang.config as C
from zugzwang.core.friends import keystore

ROOT = Path(__file__).resolve().parents[1]


def test_friends_is_on_whatever_the_build():
    assert C.FRIENDS_ENABLED is True
    src = (ROOT / "zugzwang/config.py").read_text()
    assert "FRIENDS_ENABLED = True" in src and "FRIENDS_ENABLED = not FROZEN" not in src
    build = (ROOT / "desktop/src/lib/build.ts").read_text()
    assert "export const SHOW_FRIENDS: boolean = true" in build


def test_the_packaged_sidecar_bundles_every_asset_folder():
    """BETA-5 C: the frozen sidecar lacked zugzwang/assets/ratings (Friends' ChessGoals table) and failed
    friends_status; every asset folder the code reads must be in packaging/sidecar.spec's datas."""
    spec = (ROOT / "packaging/sidecar.spec").read_text()
    assets = ROOT / "zugzwang/assets"
    # not shipped on purpose: the Polyglot book; packaged builds download theirs (BOOK-DL)
    not_shipped = {"zugzwang/assets/openings/Perfect2023.bin"}
    leaves = sorted({p.parent.relative_to(ROOT).as_posix() for p in assets.rglob("*") if p.is_file()
                     and "__pycache__" not in p.parts and p.relative_to(ROOT).as_posix() not in not_shipped})
    assert "zugzwang/assets/ratings" in leaves
    for leaf in leaves:
        assert f'"{leaf}"' in spec or any(f'"{leaf.rsplit("/", n)[0]}"' in spec for n in range(1, leaf.count("/"))), leaf


def test_a_packaged_build_has_its_own_keychain_entry():
    assert keystore.SERVICE_DEV == "dev.zugzwang.friends"
    assert keystore.SERVICE_PACKAGED == "dev.zugzwang.desktop.friends"   # the beta's app identifier
    assert keystore.SERVICE == (keystore.SERVICE_PACKAGED if C.FROZEN else keystore.SERVICE_DEV)
    assert not C.FROZEN and keystore.SERVICE == keystore.SERVICE_DEV
    assert keystore.WindowsCredentials.TARGET == keystore.SERVICE + "/identity"
