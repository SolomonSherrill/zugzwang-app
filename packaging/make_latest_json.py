#!/usr/bin/env python3
"""Write the updater's static `latest.json` from a folder of signed artifacts (BETA item 8).

    python packaging/make_latest_json.py <artifacts dir> <tag> [--base <download URL base>]

Format per <https://v2.tauri.app/plugin/updater/> ("Static JSON File"): `version`, `notes`,
`pub_date` (RFC 3339) and `platforms`, keyed `darwin-aarch64`, `darwin-x86_64`,
`windows-x86_64`, each with `url` and `signature` — the `.sig` file's *content*. Tauri
validates the whole file, so a platform without its signature is left out rather than
written half-complete. The base URL defaults to `$DOWNLOAD_BASE`, else this repository's
release download URL for the tag (the public repository, BETA-PUB Q1).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

UPDATERS = {
    "darwin-aarch64": "Zugzwang_darwin-aarch64.app.tar.gz",
    "darwin-x86_64": "Zugzwang_darwin-x86_64.app.tar.gz",
    "windows-x86_64": "*_x64-setup.exe",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("tag")
    ap.add_argument("--base", default=os.environ.get("DOWNLOAD_BASE") or None)
    ap.add_argument("--notes", default=None)
    a = ap.parse_args()
    d = Path(a.dir)
    repo = os.environ.get("REPO", "SolomonSherrill/zugzwang-app")
    base = (a.base or f"https://github.com/{repo}/releases/download/{a.tag}").rstrip("/")
    platforms = {}
    for key, pattern in UPDATERS.items():
        hits = sorted(d.glob(pattern))
        if not hits:
            print(f"note: no updater artifact for {key}", file=sys.stderr)
            continue
        art = hits[0]
        sig = art.with_name(art.name + ".sig")
        if not sig.exists():
            print(f"note: {art.name} has no .sig; {key} left out", file=sys.stderr)
            continue
        platforms[key] = {"url": f"{base}/{art.name}",
                          "signature": sig.read_text(encoding="utf-8").strip()}
    if not platforms:
        raise SystemExit("error: no signed updater artifacts found")
    print(json.dumps({
        "version": a.tag.removeprefix("v"),
        "notes": a.notes or f"Zugzwang {a.tag.removeprefix('v')}",
        "pub_date": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "platforms": platforms,
    }, indent=2))


if __name__ == "__main__":
    main()
