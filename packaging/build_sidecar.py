#!/usr/bin/env python3
"""Freeze the sidecar and lay it out for `tauri build` (BETA item 2).

    python packaging/build_sidecar.py [--beta] [--triple <rust target triple>]

1. writes `build/build_info.json` (version from tauri.conf.json, git commit, beta flag,
   target), which the spec bakes into the bundle as `zugzwang/build_info.json`;
2. runs PyInstaller one-dir (`packaging/sidecar.spec`) into `build/sidecar-dist/`;
3. leaves the one-dir folder in `build/sidecar-dist/zugzwang-sidecar/`, which
   `tauri.beta.conf.json` ships whole as the resource folder `sidecar/`
   (`Contents/Resources/sidecar/` on macOS, `<install dir>\\sidecar\\` on Windows) and the
   app spawns through `$RESOURCE` (`capabilities/beta.json`). Not an `externalBin`: that is
   one file in `Contents/MacOS`, where PyInstaller's bootloader then insists on
   `Contents/Frameworks`, and codesign rejects the data files there (BETA.md, item 2).

Stockfish is placed separately by `tools/get_stockfish.py --tauri <triple>`.

Must run on the target OS and CPU: PyInstaller does not cross-compile. Tester builds come
from CI, not the owner's Mac: Homebrew's Python is built for the running macOS only
(`minos 27.0`, BETA.md stage 1, M16).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def host_triple() -> str:
    out = subprocess.run(["rustc", "--print", "host-tuple"], capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout.strip()
    for line in subprocess.run(["rustc", "-Vv"], capture_output=True, text=True).stdout.splitlines():
        if line.startswith("host:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("error: cannot determine the Rust target triple")


def git_commit() -> str | None:
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    return out.stdout.strip() or None if out.returncode == 0 else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beta", action="store_true", help="stamp the build as a beta")
    ap.add_argument("--triple", help="Rust target triple (default: this host)")
    a = ap.parse_args()
    triple = a.triple or host_triple()

    conf = json.loads((ROOT / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    beta_conf = ROOT / "desktop/src-tauri/tauri.beta.conf.json"
    version = conf["version"]
    if a.beta and beta_conf.exists():
        version = json.loads(beta_conf.read_text(encoding="utf-8")).get("version", version)
    info = {"version": version, "commit": git_commit(), "beta": a.beta,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target": triple}
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    (build / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"build_info: {info}")

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN",
                    "--distpath", str(build / "sidecar-dist"),
                    "--workpath", str(build / "sidecar-work"),
                    str(ROOT / "packaging" / "sidecar.spec")], check=True)

    size = sum(p.stat().st_size for p in (build / "sidecar-dist").rglob("*") if p.is_file())
    print(f"sidecar one-dir: {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
