#!/usr/bin/env python3
"""Fetch, verify and bench the official Stockfish 18 build for a target (BETA item 1).

    python tools/get_stockfish.py                      # this machine's target, into stockfish/
    python tools/get_stockfish.py --bench              # ... and assert the bench signature
    python tools/get_stockfish.py --target windows/x86_64 --tauri x86_64-pc-windows-msvc
    python tools/get_stockfish.py --variant avx2 --bench --tauri x86_64-apple-darwin

Cross-platform successor to `tools/get_stockfish.sh` (which stays, for the owner's Mac).
The asset and binary hashes, the bench signature and the source link are in
`zugzwang/config.py` (`STOCKFISH_ASSETS`, `STOCKFISH_BENCH_NODES`). Checks, in order:
the downloaded asset's sha256, the extracted binary's sha256, `uci` answering
"Stockfish 18", and with `--bench` the node count of `bench` — the signature that proves a
different build searches identically, so labels stay comparable across machines.

`--tauri <triple>` also copies the binary to `desktop/src-tauri/binaries/stockfish-<triple>`
(the externalBin naming Tauri requires). `--variant avx2` fetches the second x86-64 build
(`STOCKFISH_FAST_ASSETS`, BETA-PUB Q6) instead, copied as `stockfish-avx2-<triple>`.
The licence text the app shows is committed at
`desktop/public/licenses/stockfish-COPYING.txt`; this checks the release still carries it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zugzwang import config as C  # noqa: E402

URL = "https://github.com/official-stockfish/Stockfish/releases/download/sf_18/{asset}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str) -> bytes:
    ctx = None
    try:
        import ssl

        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": "zugzwang-build"})
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        return resp.read()


def extract(asset: str, blob: bytes, binary: str) -> tuple[bytes, bytes | None]:
    """(binary bytes, Copying.txt bytes) from the release archive."""
    want = f"stockfish/{binary}"
    lic = "stockfish/Copying.txt"
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = set(z.namelist())
            return z.read(want), (z.read(lic) if lic in names else None)
    with tarfile.open(fileobj=io.BytesIO(blob)) as t:
        b = t.extractfile(want)
        if b is None:
            raise SystemExit(f"error: {want} not in {asset}")
        data = b.read()
        try:
            lf = t.extractfile(lic)
            licence = lf.read() if lf else None
        except KeyError:
            licence = None
        return data, licence


def run_engine(path: Path, commands: str, timeout: int) -> str:
    out = subprocess.run([str(path)], input=commands, capture_output=True, text=True,
                         timeout=timeout)
    return out.stdout + out.stderr


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="os/cpu, e.g. darwin/arm64, darwin/x86_64, windows/x86_64")
    ap.add_argument("--bench", action="store_true", help="assert the bench signature")
    ap.add_argument("--tauri", metavar="TRIPLE", help="also copy as a Tauri externalBin")
    ap.add_argument("--from-file", help="use this already-downloaded asset instead")
    ap.add_argument("--variant", choices=["wide", C.STOCKFISH_FAST_VARIANT], default="wide",
                    help="the wide build (default) or the second x86-64 build")
    a = ap.parse_args()

    target = tuple(a.target.split("/")) if a.target else C.host_target()
    table = C.STOCKFISH_ASSETS if a.variant == "wide" else C.STOCKFISH_FAST_ASSETS
    spec = table.get(target)  # type: ignore[arg-type]
    if spec is None:
        raise SystemExit(f"error: no Stockfish 18 {a.variant} asset recorded for {target}")

    blob = Path(a.from_file).read_bytes() if a.from_file else download(URL.format(**spec))
    got = sha256(blob)
    if got != spec["asset_sha256"]:
        raise SystemExit(f"error: asset sha256 {got} != {spec['asset_sha256']}")
    print(f"asset sha256 ok: {spec['asset']} {got}")

    binary, licence = extract(spec["asset"], blob, spec["binary"])
    got = sha256(binary)
    if got != spec["binary_sha256"]:
        raise SystemExit(f"error: binary sha256 {got} != {spec['binary_sha256']}")
    print(f"binary sha256 ok: {spec['binary']} {got}")

    dest = ROOT / "stockfish" / spec["binary"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(binary)
    dest.chmod(0o755)
    print(f"installed {dest}")

    if target == C.host_target():
        ident = run_engine(dest, "uci\nquit\n", 60).splitlines()[0]
        if not ident.startswith("Stockfish 18 "):
            raise SystemExit(f"error: binary says {ident!r}")
        print(f"uci ok: {ident}")
        if a.bench:
            text = run_engine(dest, "bench\nquit\n", 600)
            nodes = next((ln.split(":", 1)[1].strip() for ln in text.splitlines()
                          if ln.startswith("Nodes searched")), None)
            if nodes != str(C.STOCKFISH_BENCH_NODES):
                raise SystemExit(f"error: bench {nodes} != {C.STOCKFISH_BENCH_NODES}")
            print(f"bench ok: {nodes} nodes")
    elif a.bench:
        raise SystemExit("error: --bench needs the target to be this machine")

    if a.tauri:
        exe = ".exe" if spec["binary"].endswith(".exe") else ""
        stem = "stockfish" if a.variant == "wide" else f"stockfish-{a.variant}"
        out = ROOT / "desktop" / "src-tauri" / "binaries" / f"{stem}-{a.tauri}{exe}"
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, out)
        print(f"externalBin {out}")
    shipped = ROOT / "desktop" / "public" / "licenses" / "stockfish-COPYING.txt"
    norm = lambda b: b.replace(b"\r\n", b"\n")  # noqa: E731 — the Windows zip has CRLF
    if licence is not None and shipped.exists() and norm(shipped.read_bytes()) != norm(licence):
        raise SystemExit(f"error: {shipped} differs from the release's Copying.txt")


if __name__ == "__main__":
    main()
