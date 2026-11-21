"""Install an opening book and switch a database to it by hand (BOOK-DL; W20's backfill).

The same code the app runs (`core/books.py`): `install` is the verified download, `dry-run`
the book relabel with nothing written, `write` the switch (a verified backup, the book recorded
as in use, the relabel). Set the data directory and the database explicitly:

    ZUGZWANG_DATA_DIR=DIR .venv/bin/python tools/book_switch.py install all-20
    ZUGZWANG_DATA_DIR=DIR .venv/bin/python tools/book_switch.py dry-run all-20 --db DB --out OUT
    ZUGZWANG_DATA_DIR=DIR .venv/bin/python tools/book_switch.py write all-20 --db DB --expect N

`dry-run` prints plies whose label changes by previous label, the player's against the
opponents', and the runs whose counts are recomputed; OUT gets every changed ply keyed by
platform and platform game id + ply (the measurement house rule). Any change outside W20's
rule (with the book prefix, BOOK-PREFIX) exits 3. `write` refuses unless the labels it would
change equal --expect.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from zugzwang.core import books, relabel  # noqa: E402


def _games(db: Path) -> dict[int, tuple]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0]: r[1:] for r in con.execute(
            "SELECT r.id, g.source, g.external_id, g.player_color, g.id FROM analysis_runs r "
            "JOIN games g ON g.id = r.game_id WHERE r.completed_at IS NOT NULL")}
    finally:
        con.close()


def _counts(db: Path) -> Counter:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return Counter(dict(con.execute(
            "SELECT m.classification, COUNT(*) FROM move_analyses m JOIN analysis_runs r "
            "ON r.id = m.run_id WHERE r.completed_at IS NOT NULL GROUP BY 1")))
    finally:
        con.close()


def _movers(db: Path) -> dict[tuple[int, int], str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {(r[0], r[1]): ("white" if " w " in r[2] else "black") for r in con.execute(
            "SELECT run_id, ply, fen_before FROM move_analyses")}
    finally:
        con.close()


def _measure(db: Path, path: Path, out: Path | None) -> tuple[dict, list]:
    games = _games(db)
    movers = _movers(db)
    changed: list[tuple] = []

    def detail(rid, ch):
        src, ext, colour, gid = games[rid]
        for ply, old, new, ob, nb, op in ch:
            mover = movers[(rid, ply)]
            changed.append((src, ext, ply, old, new, int(ob), int(nb),
                            "player" if mover == colour else "opponent", gid,
                            "" if op is None else int(op)))

    res = books.relabel_for_book(db, path, write=False, detail=detail)
    if out is not None:
        with open(out, "w") as f:
            # game_id is this database's games.id: it tells apart local games, which have no
            # platform id; a re-pull renumbers it, so the platform id is the key elsewhere.
            f.write("source\tgame\tply\tlabel_before\tlabel_after\tis_book_before\t"
                    "is_book_after\tside\tgame_id\tbook_prefix_open\n")
            for c in sorted(changed, key=lambda c: (c[0], str(c[1]), c[2], c[8])):
                f.write("\t".join(str(x) for x in c) + "\n")
    return res, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "dry-run", "write"])
    ap.add_argument("book", help="a manifest id (all-20, all-6, all-3) or 'none'")
    ap.add_argument("--db", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--expect", type=int)
    a = ap.parse_args()
    if "ZUGZWANG_DATA_DIR" not in os.environ:
        sys.exit("set ZUGZWANG_DATA_DIR: the data directory the book goes into")
    b = None if a.book == "none" else books.spec(a.book)
    if a.action == "install":
        if b is None:
            sys.exit("nothing to install")
        last = {"p": -1}

        def prog(got, total):
            p = got * 100 // total
            if p // 10 != last["p"] // 10:
                print(f"  {p}% ({got} of {total} bytes)", flush=True)
            last["p"] = p
        path = books.download(b, progress=prog)
        print(f"installed and verified: {path} ({b.bytes} bytes, sha256 {b.sha256})")
        return 0
    if a.db is None:
        sys.exit("--db is required")
    path = None
    if b is not None:
        if not books.installed(b):
            sys.exit(f"{b.id} is not installed in {books.books_dir()}: run install first")
        path = books.book_path(b)
    res, changed = _measure(a.db, path, a.out)
    outside = [c for c in changed
               if books.outside_w20((*c[2:7], None if c[9] == "" else bool(c[9])))]
    lab = [c for c in changed if c[3] != c[4]]
    print(f"database {a.db}: {res['runs']} complete runs; book {a.book}")
    print(f"  plies flagged in book {res['pliesFlagged']}, unflagged {res['pliesUnflagged']}; "
          f"runs with a flag change {res['runsChanged']} ({res['runsFlagsOnly']} at an older "
          "classifier: flags only)")
    print(f"  labels changed {res['labelsChanged']}: the player's "
          f"{sum(c[7] == 'player' for c in lab)}, the opponents' {sum(c[7] == 'opponent' for c in lab)}")
    for side in ("player", "opponent", None):
        t = Counter(f"{c[3]}>{c[4]}" for c in lab if side is None or c[7] == side)
        print(f"  {side or 'all'}: " + ", ".join(f"{k} {v}" for k, v in t.most_common()))
    print(f"  runs whose counts are recomputed: {len(res['relabelledRuns'])}")
    print(f"  outside W20's rule: {len(outside)}")
    for c in outside[:20]:
        print("    ", c[:8])
    if outside:
        return 3
    if a.action == "dry-run":
        return 0
    if a.expect is None or a.expect != res["labelsChanged"]:
        sys.exit(f"refused: --expect {a.expect}, the dry run changes {res['labelsChanged']}")
    before = _counts(a.db)
    backup = relabel.backup_database(a.db, a.db.parent / "backups",
                                     f"pre-book-{b.id if b else 'none'}")
    print(f"backup (verified): {backup}")
    books.set_active(b.id if b else None, relabelled=False)
    out = books.relabel_for_book(a.db, path, write=True)
    if b is not None:
        books.set_active(b.id, relabelled=True)
    after = _counts(a.db)
    print(f"written: labels changed {out['labelsChanged']}, facts deleted {out['factsDeleted']}, "
          f"integrity {out['integrity']}")
    print("by label, before -> after: " + ", ".join(
        f"{k} {before[k]} -> {after[k]}" for k in sorted(set(before) | set(after))
        if before[k] != after[k]))
    print(json.dumps({k: v for k, v in out.items() if k != "relabelledRuns"}))
    return 0 if out["labelsChanged"] == a.expect and out["integrity"] == "ok" else 4


if __name__ == "__main__":
    sys.exit(main())
