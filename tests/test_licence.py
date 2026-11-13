"""BETA-PUB Q5 (owner, 2026-11-12): Zugzwang is GPL-3.0-or-later and its source is public.
The licence text ships in the app, and the Licences card links to this version's source."""

import hashlib
import json
from pathlib import Path

import zugzwang.config as C

ROOT = Path(__file__).resolve().parent.parent
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"  # FSF gpl-3.0.txt


def test_licence_is_gpl3_or_later_with_the_full_text():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (C) 2026 Solomon Sherrill" in text
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in text
    assert "either version 3 of the License, or (at your option) any later version" in text
    full = text[text.index("                    GNU GENERAL PUBLIC LICENSE"):]
    assert hashlib.sha256(full.encode()).hexdigest() == GPL3_SHA256


def test_the_app_ships_the_same_licence():
    shipped = ROOT / "desktop" / "public" / "licenses" / "zugzwang-LICENSE.txt"
    assert shipped.read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_source_link_is_the_release_tag():
    assert C.source_url("0.1.0-beta.1") == \
        "https://github.com/SolomonSherrill/zugzwang-app/tree/v0.1.0-beta.1"
    assert C.source_url("dev") == "https://github.com/SolomonSherrill/zugzwang-app"
    assert C.source_url(None) == "https://github.com/SolomonSherrill/zugzwang-app"


def test_the_update_address_is_the_public_repo():
    """Compiled into every beta build; it can never change (BETA.md)."""
    conf = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.beta.conf.json").read_text())
    assert conf["plugins"]["updater"]["endpoints"] == [
        "https://github.com/SolomonSherrill/zugzwang-app/releases/latest/download/latest.json"]
