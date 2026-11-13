#!/usr/bin/env python3
"""Build the beta app for this machine's target, end to end (BETA item 2).

    python packaging/build_app.py            # sidecar + Stockfish + tauri build (beta configs)
    python packaging/build_app.py --no-tauri # stop after laying out the externalBins

The one entry point CI and a person use. Steps: `packaging/build_sidecar.py --beta`,
`tools/get_stockfish.py --bench --tauri <triple>`, then `tauri build` with
`tauri.beta.conf.json` and the OS's `tauri.beta.<os>.conf.json` merged over the dev config
(the owner's `npm run tauri dev` reads none of them). Updater artifacts are signed when
`TAURI_SIGNING_PRIVATE_KEY` is set in the environment; it is never read from a file here.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
sys.path.insert(0, str(Path(__file__).parent))

from build_sidecar import host_triple  # noqa: E402


#: x86-64 bundles both Stockfish builds (BETA-PUB Q6); arm64 ships one.
EXTERNAL_BINS_X86 = '{"bundle":{"externalBin":["binaries/stockfish","binaries/stockfish-avx2"]}}'


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tauri", action="store_true")
    ap.add_argument("--stockfish-asset", help="a local copy of the release asset (skips download)")
    a = ap.parse_args()
    triple = host_triple()
    os_name = "windows" if "windows" in triple else "macos" if "apple" in triple else "linux"

    run([sys.executable, str(ROOT / "packaging/build_sidecar.py"), "--beta", "--triple", triple])
    sf = [sys.executable, str(ROOT / "tools/get_stockfish.py"), "--bench", "--tauri", triple]
    if a.stockfish_asset:
        sf += ["--from-file", a.stockfish_asset]
    run(sf)
    # x86-64 ships a second, faster build, chosen at startup by CPU feature (BETA-PUB Q6).
    two_builds = "x86_64" in triple
    if two_builds:
        run([sys.executable, str(ROOT / "tools/get_stockfish.py"), "--variant", "avx2",
             "--bench", "--tauri", triple])
    if a.no_tauri:
        return

    if "TAURI_SIGNING_PRIVATE_KEY" not in os.environ:
        print("note: TAURI_SIGNING_PRIVATE_KEY is not set — updater artifacts will not be "
              "signed (tauri.beta.conf.json then needs createUpdaterArtifacts off)", flush=True)
    npx = shutil.which("npx") or "npx"
    env = dict(os.environ, CI="true")  # bundle_dmg.sh skips its Finder AppleScript
    run([npx, "tauri", "build",
         "--config", "src-tauri/tauri.beta.conf.json",
         "--config", f"src-tauri/tauri.beta.{os_name}.conf.json",
         *(["--config", EXTERNAL_BINS_X86] if two_builds else [])], cwd=DESKTOP, env=env)
    bundle = DESKTOP / "src-tauri" / "target" / "release" / "bundle"
    for p in sorted(bundle.rglob("*")):
        if p.is_file() and p.suffix in {".dmg", ".exe", ".msi", ".gz", ".sig"}:
            print(f"artifact {p.relative_to(ROOT)}  {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
