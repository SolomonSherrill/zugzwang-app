"""Fill `pattern_facts` (R6, PATTERNS.md §6a) for every complete run that has no counting row.

    .venv/bin/python tools/backfill_pattern_facts.py <db> [--all] [--workers N]

Opens <db> read-write once (so migration v19 creates the table), lists the complete runs with
no facts row of this `FACTS_VERSION` at the run's classifier version (every complete run with
--all), computes each run's facts in a process pool (each worker on its own read-only
connection; the game report is engine-free) and writes them from this process in batches. It
is re-runnable, and it is what to run after any relabel. Run against the live database only
with no app or sidecar open, after `scripts/backup-db.sh`.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from zugzwang.core import patterns  # noqa: E402
from zugzwang.core.database import Database  # noqa: E402
from zugzwang.core.explain import RULE_VERSION  # noqa: E402

_db: Database | None = None
_path: Path | None = None


def _init(path: str) -> None:
    global _path
    _path = Path(path)


def _one(run_id: int):
    global _db
    if _db is None:
        _db = Database(_path, read_only=True)
    return patterns.facts_row(_db, run_id)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("db", type=Path)
    ap.add_argument("--all", action="store_true", help="recompute every complete run")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--batch", type=int, default=200)
    a = ap.parse_args()
    if not a.db.exists():
        print(f"no database at {a.db}", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    db = Database(a.db)   # read-write: runs the migrations, so the table exists
    todo = db.runs_without_pattern_facts(patterns.FACTS_VERSION, rule_version=RULE_VERSION,
                                         every=a.all)
    print(f"{len(todo)} complete runs to fill (facts version {patterns.FACTS_VERSION})",
          flush=True)
    written = skipped = 0
    batch: list[tuple] = []
    with mp.get_context("spawn").Pool(a.workers, initializer=_init,
                                      initargs=(str(a.db),)) as pool:
        for row in pool.imap_unordered(_one, todo, chunksize=8):
            if row is None:
                skipped += 1
                continue
            batch.append(row)
            if len(batch) >= a.batch:
                db.save_pattern_facts(batch)
                written += len(batch)
                batch = []
    if batch:
        db.save_pattern_facts(batch)
        written += len(batch)
    left = len(db.runs_without_pattern_facts(patterns.FACTS_VERSION, rule_version=RULE_VERSION))
    db.close()
    print(f"written {written}, skipped {skipped} (not complete when read); runs still "
          f"without facts {left}; {time.monotonic() - t0:.1f} s wall, {a.workers} workers")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
