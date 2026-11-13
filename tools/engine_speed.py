#!/usr/bin/env python3
"""Q6 (BETA-PUB, owner 2026-11-12): how much slower is the widest-CPU Stockfish 18 build
than the fastest official build that runs on this machine?

    python tools/engine_speed.py [--repeat 3] [--games 3]

For every official `sf_18` x86-64 asset for this OS (macOS or Windows): download it, check
its sha256 against the digest GitHub publishes for the release asset, extract it, and ask
it for `uci`. A build that does not answer (an instruction this CPU lacks) is recorded as
"does not run here". Every build that runs is benched `--repeat` times: the node count
must be the signature, 2050811, and nodes per second is the median. Then the widest build
(plain x86-64) and the fastest that runs each analyse the same fixed games at depth 14 the
way the app does (`analyze_game_plies`, one thread, `configure_engine_for_analysis`), and
the seconds per game are printed.

The games are constructed (deterministic self-play by the sf_18 arm64 binary at depth 8,
one thread, 16 MB hash, 60 plies from three openings) and keyed by their moves below, so a
re-run measures the same set on any machine (the house rule, CLAUDE.md). No platform game is
involved.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zugzwang import config as C  # noqa: E402

RELEASE_API = "https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/sf_18"
DOWNLOAD = "https://github.com/official-stockfish/Stockfish/releases/download/sf_18/{asset}"

# Constructed games (see the docstring): UCI moves from the start position, 60 plies each.
GAMES = {
    "sicilian-60": "e2e4 c7c5 g1f3 d7d6 f1b5 c8d7 b5d7 d8d7 e1g1 g8f6 f1e1 e7e6 c2c3 b8c6 d1e2 "
                   "f8e7 d2d3 h7h6 b1a3 d6d5 c1f4 e8g8 a1d1 a7a6 f3e5 c6e5 f4e5 b7b5 a3b1 d7b7 "
                   "e4d5 b7d5 c3c4 d5b7 b2b3 f6d7 e5b2 e7f6 b2f6 d7f6 b1c3 f8d8 e2e5 b7b6 c3e4 "
                   "f6d7 e5h5 a8c8 g2g4 d7f8 g4g5 h6g5 e4g5 g7g6 h5h6 d8d4 g5f3 d4g4 g1f1 b6c7",
    "nimzo-60": "d2d4 g8f6 c2c4 e7e6 g1f3 d7d5 b1c3 f8b4 c1g5 e8g8 e2e3 h7h6 g5h4 c7c5 c4d5 "
                "e6d5 f1d3 c5d4 f3d4 b4c3 b2c3 b8c6 d4c6 b7c6 e1g1 a7a5 a1c1 f8e8 h2h3 c8a6 "
                "d3a6 a8a6 c3c4 d8d6 d1d3 d6e6 h4f6 e6f6 c4d5 c6d5 d3d5 e8d8 d5b5 a6d6 a2a4 "
                "d6d5 c1c5 d5d1 c5c1 d1d5 b5c4 f6e5 c4c7 e5f5 c1c4 d5d7 c4f4 d7c7 f4f5 g7g6",
    "ruy-60": "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5c6 d7c6 b1c3 c8g4 h2h3 g4f3 d1f3 g8f6 e1g1 "
              "d8d7 d2d3 d7e6 a2a4 f8b4 c3d1 f6d7 d1e3 g7g6 f3e2 e8c8 e3c4 f7f5 c1g5 d8e8 "
              "c2c3 b4f8 b2b4 f5f4 f2f3 h7h6 g5h4 g6g5 h4f2 h6h5 b4b5 g5g4 b5a6 b7a6 c4a5 "
              "c6c5 d3d4 e5d4 c3d4 g4h3 e2b2 e6b6 b2b6 c7b6 a5c4 h8g8 g1h2 h3g2 f1g1 c8c7",
}


def _ctx():
    try:
        import ssl

        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def fetch(url: str, accept: str | None = None) -> bytes:
    headers = {"User-Agent": "zugzwang-build"}
    if accept:
        headers["Accept"] = accept
    import os
    if "api.github.com" in url and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=600, context=_ctx()) as r:
        return r.read()


def candidates() -> list[dict]:
    """This OS's x86-64 assets with their published sha256, widest first."""
    os_name = {"Darwin": "macos", "Windows": "windows"}[platform.system()]
    assets = json.loads(fetch(RELEASE_API, "application/vnd.github+json"))["assets"]
    out = []
    for a in assets:
        name = a["name"]
        if not name.startswith(f"stockfish-{os_name}-x86-64"):
            continue
        out.append({"asset": name, "sha256": a["digest"].split(":", 1)[1],
                    "variant": name.split(".")[0].removeprefix(f"stockfish-{os_name}-")})
    out.sort(key=lambda c: (c["variant"] != "x86-64", c["variant"]))
    return out


def extract(asset: str, blob: bytes, dest: Path) -> Path:
    stem = asset.split(".")[0]
    want = f"stockfish/{stem}.exe" if asset.endswith(".zip") else f"stockfish/{stem}"
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            data = z.read(want)
    else:
        with tarfile.open(fileobj=io.BytesIO(blob)) as t:
            f = t.extractfile(want)
            assert f is not None, want
            data = f.read()
    path = dest / Path(want).name
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def engine_io(path: Path, commands: str, timeout: float) -> tuple[int | None, str]:
    try:
        p = subprocess.run([str(path)], input=commands, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, str(exc)


def bench(path: Path) -> tuple[int | None, int | None]:
    code, text = engine_io(path, "bench\nquit\n", 900)
    nodes = nps = None
    for ln in text.splitlines():
        if ln.startswith("Nodes searched"):
            nodes = int(ln.split(":", 1)[1])
        elif ln.startswith("Nodes/second"):
            nps = int(ln.split(":", 1)[1])
    return nodes, nps


def seconds_per_game(path: Path, n_games: int) -> list[tuple[str, float]]:
    import chess.engine

    from zugzwang.core.analysis import analyze_game_plies, configure_engine_for_analysis
    out = []
    for key, moves in list(GAMES.items())[:n_games]:
        board = chess.Board()
        game = chess.pgn.Game()
        node = game
        for u in moves.split():
            node = node.add_variation(chess.Move.from_uci(u))
            board.push_uci(u)
        pgn = str(game)
        eng = chess.engine.SimpleEngine.popen_uci(str(path))
        try:
            configure_engine_for_analysis(eng)
            t0 = time.perf_counter()
            plies = sum(1 for ev in analyze_game_plies(eng, pgn, 14) if ev[0] == "ply")
            dt = time.perf_counter() - t0
        finally:
            eng.quit()
        assert plies == 60, (key, plies)
        out.append((key, dt))
    return out


def main() -> int:
    import chess.pgn  # noqa: F401 — imported here so a missing dependency fails early

    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--json", help="also write the results here")
    a = ap.parse_args()

    print(f"machine: {platform.system()} {platform.machine()} {platform.processor()!r}; "
          f"python {platform.python_version()}")
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for c in candidates():
            blob = fetch(DOWNLOAD.format(asset=c["asset"]))
            got = hashlib.sha256(blob).hexdigest()
            if got != c["sha256"]:
                raise SystemExit(f"error: {c['asset']} sha256 {got} != published {c['sha256']}")
            d = Path(tmp) / c["variant"]
            d.mkdir()
            exe = extract(c["asset"], blob, d)
            del blob
            code, text = engine_io(exe, "uci\nquit\n", 60)
            runs = code == 0 and "Stockfish 18" in text
            row = {**c, "binary_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
                   "runs": runs, "path": str(exe)}
            if runs:
                benches = [bench(exe) for _ in range(a.repeat)]
                row["bench_nodes"] = sorted({n for n, _ in benches if n is not None})
                row["nps"] = [nps for _, nps in benches]
                # A build can answer `uci` and still die in the search on an instruction
                # this CPU lacks (avx512icl on the Windows runner, speed-q6-1): it runs
                # here only if every bench finished.
                if any(n is None or nps is None for n, nps in benches):
                    row["runs"] = False
                    row["note"] = "answers uci, crashes in bench"
                else:
                    row["nps_median"] = statistics.median(row["nps"])
                    row["signature_ok"] = row["bench_nodes"] == [C.STOCKFISH_BENCH_NODES]
            else:
                row["exit"] = code
            print(json.dumps({k: v for k, v in row.items() if k != "path"}), flush=True)
            results.append(row)

        ok = [r for r in results if r["runs"] and r["signature_ok"]]
        wide = next(r for r in ok if r["variant"] == "x86-64")
        fast = max(ok, key=lambda r: r["nps_median"])
        # The build that ships beside the wide one (BETA-PUB Q6): AVX2, the fastest build
        # that ran on every CI machine seen (the AVX-512 builds crash on the AMD runner).
        ship = next((r for r in ok if r["variant"] == "x86-64-avx2"), None)
        for r in {id(x): x for x in (wide, fast, ship) if x is not None}.values():
            r["games"] = seconds_per_game(Path(r["path"]), a.games)
            r["s_per_game_mean"] = statistics.mean(t for _, t in r["games"])
        slower_nps = 1 - wide["nps_median"] / fast["nps_median"]
        slower_game = wide["s_per_game_mean"] / fast["s_per_game_mean"] - 1
        print()
        print(f"{'variant':<22}{'runs':<6}{'bench':<10}{'nps (median)':>14}{'s/game d14':>12}")
        for r in results:
            print(f"{r['variant']:<22}{'yes' if r['runs'] else 'NO':<6}"
                  f"{(str(r.get('bench_nodes', ['-'])[0]) if r['runs'] else '-'):<10}"
                  f"{(f'{r['nps_median']:,.0f}' if r['runs'] else '-'):>14}"
                  f"{(f'{r['s_per_game_mean']:.1f}' if 's_per_game_mean' in r else ''):>12}")
        print()
        print(f"widest: {wide['variant']}; fastest that runs: {fast['variant']}")
        print(f"widest is {slower_nps:.1%} slower in nodes/second (lower nps), "
              f"and takes {slower_game:+.1%} time per game at depth 14")
        if ship is not None and ship is not fast:
            print(f"widest against {ship['variant']} (shipped): "
                  f"{1 - wide['nps_median'] / ship['nps_median']:.1%} lower nps, "
                  f"{wide['s_per_game_mean'] / ship['s_per_game_mean'] - 1:+.1%} time per game; "
                  f"{ship['variant']} per game {[round(t, 1) for _, t in ship['games']]} s")
        print(f"games: {', '.join(k for k, _ in wide['games'])}; per game "
              f"widest {[round(t, 1) for _, t in wide['games']]} s, "
              f"fastest {[round(t, 1) for _, t in fast['games']]} s")
        if a.json:
            Path(a.json).write_text(json.dumps(
                {"results": [{k: v for k, v in r.items() if k != "path"} for r in results],
                 "widest": wide["variant"], "fastest": fast["variant"],
                 "shipped": ship["variant"] if ship else None,
                 "slower_nps": slower_nps, "slower_per_game": slower_game}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
