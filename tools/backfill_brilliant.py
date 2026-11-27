"""BRIL-3 C: the brilliant backfill by hand, for a measurement on a scratch copy (core/brilliant_backfill.py).

    python tools/backfill_brilliant.py <copy.db> <out-prefix> [--workers N] [--dry]

The same functions as the app's background job (`AnalysisRunner.refill_brilliant`): every complete run at the current
classifier version that is not backfilled at this key gets BR-F's depth-22 search for its candidates, is relabelled from
its stored rows, and gets M1's proof for its brilliant plies; then it is stamped. The app runs one engine and waits while
an interactive screen is open; this runs N one-thread engines (Stockfish as the app finds it, configured as the app
configures it) side by side, so its wall time is shorter. The figures (<out-prefix>.out) give the single-engine cost too:
the sum of the search times and of the labelling passes. Every candidate and every proof is keyed by platform game id +
ply (<out-prefix>.set.txt). --dry computes everything and writes nothing.

Refuses any database under ~/.zugzwang (the owner's data): point it at a copy."""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DB = None
_ENGINE = None


def _init(db_path: str) -> None:
    global _DB, _ENGINE
    from zugzwang.core.analysis import configure_engine_for_analysis
    from zugzwang.core.database import Database
    from zugzwang.core.engine_locator import find_stockfish, popen_engine
    _DB = Database(Path(db_path), read_only=True)
    _ENGINE = popen_engine(find_stockfish())
    configure_engine_for_analysis(_ENGINE)


def _work(run_id: int):
    from zugzwang.core import brilliant_backfill as BB
    t = time.monotonic()
    loaded = BB.load_run(_DB, run_id)
    if loaded is None:
        return None, 0.0
    plies, final, ratings = loaded
    res = BB.compute_run(plies, final, ratings, run_id, _ENGINE)
    return res, time.monotonic() - t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    db_path = Path(a.db).resolve()
    if ".zugzwang" in db_path.parts:
        print("refused: a database under ~/.zugzwang; use a scratch copy", file=sys.stderr)
        return 2
    from zugzwang.core import brilliant_backfill as BB
    from zugzwang.core.classification import CLASSIFIER_VERSION
    from zugzwang.core.database import Database
    Database(db_path).close()                               # the migrations (v26), on the copy
    con = sqlite3.connect(str(db_path), isolation_level=None)
    todo = BB.runs_to_backfill(con)
    meta = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT r.id, g.external_id, g.source, g.player_color FROM analysis_runs r JOIN games g ON g.id = r.game_id")}
    before = {(r[0], r[1]): r[2] for r in con.execute(
        "SELECT run_id, ply, classification FROM move_analyses WHERE run_id IN (SELECT id FROM analysis_runs "
        "WHERE completed_at IS NOT NULL AND classifier_version = ?)", (CLASSIFIER_VERSION,))}
    t0 = time.monotonic()
    results, wall_per_run = [], []
    with mp.Pool(a.workers, initializer=_init, initargs=(str(db_path),)) as pool:
        for res, secs in pool.imap_unordered(_work, todo, chunksize=4):
            if res is None:
                continue
            results.append(res)
            wall_per_run.append(secs)
            if not a.dry:
                BB.apply(con, res)
    wall = time.monotonic() - t0
    after = {(r[0], r[1]): r[2] for r in con.execute(
        "SELECT run_id, ply, classification FROM move_analyses WHERE run_id IN (%s)" %
        ",".join(str(r.run_id) for r in results))} if results and not a.dry else {}
    cands = sorted(((r.run_id, p) for r in results for p in r.candidates))
    brf_s = sum(r.seconds_by_kind["brf"] for r in results)
    m1_s = sum(r.seconds_by_kind["m1"] for r in results)
    label_s = sum(wall_per_run) - brf_s - m1_s
    proofs = sorted(((r.run_id, p, pr) for r in results for p, pr in r.proofs.items()), key=lambda x: (x[0], x[1]))
    changed = sorted(k for k, v in after.items() if before.get(k) != v)
    lines = []
    p = lambda *x: lines.append(" ".join(str(v) for v in x))   # noqa: E731
    p(f"BRIL-3 C brilliant backfill; {time.strftime('%Y-%m-%d %H:%M')} local; classifier version {CLASSIFIER_VERSION}, "
      f"key {BB.backfill_key()}; {'dry run' if a.dry else 'written'}; {a.workers} one-thread engines")
    p(f"runs read: {len(results)} (listed {len(todo)}); failed: {sum(r.failed for r in results)}")
    p(f"BR-F: candidates without a stored search {len(cands)}, depth-22 searches {len(cands)}, search time {brf_s:.1f} s")
    p(f"M1: brilliant plies proved {len(proofs)}, proven {sum(1 for *_, pr in proofs if pr['proven'])}, depth-14 "
      f"searches {sum(pr['searched'] for *_, pr in proofs)}, search time {m1_s:.1f} s")
    p(f"labelling passes (no engine): {label_s:.1f} s summed over runs")
    p(f"single-engine cost (search time + labelling passes): {brf_s + m1_s + label_s:.1f} s; wall here {wall:.1f} s")
    p(f"labels changed by the backfill: {len(changed)}" + (" (dry run: not written)" if a.dry else ""))
    Path(a.out + ".out").write_text("\n".join(lines) + "\n")
    by = {r.run_id: r for r in results}
    with open(a.out + ".set.txt", "w") as fh:
        fh.write(f"## candidates ({len(cands)}): platform game id, ply, depth-22 after-score (mover's side), label\n")
        for rid, ply in cands:
            ext, src, colour = meta[rid]
            v = by[rid].verify.get(ply)
            fh.write(f"{src} {ext} ply {ply}\tdepth22={v[0] if v else None},{v[1] if v else None}\t"
                     f"{before.get((rid, ply))} -> {after.get((rid, ply), before.get((rid, ply)))}\n")
        fh.write(f"## proofs ({len(proofs)}): platform game id, ply, proven, searched, mates or the move that holds\n")
        for rid, ply, pr in proofs:
            ext, src, colour = meta[rid]
            fh.write(f"{src} {ext} ply {ply}\tproven={pr['proven']}\tsearched={pr['searched']}\t"
                     + (json.dumps(pr["mates"]) if pr["proven"] else f"holds={pr['refuted_by']} {pr['refuted_score']}")
                     + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
