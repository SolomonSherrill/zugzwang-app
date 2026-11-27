"""Relabel on update (BETA item 5): bring every complete run to the current classifier.

When a build with a newer `CLASSIFIER_VERSION` opens a database, runs written by an older
classifier carry stale labels. Labels are a function of stored rows only
(`labelling.label_game`, no engine), so they are recomputed from what is stored — the
computation `review/baselines/cls_v3_relabel.py` (the owner's stage-6 tool) performs, per
run: each ply's label, depth-14 after-score, after-move search and `hard_only_move` (with the
mover's PGN rating, `labelling.game_ratings`, and BR-F's stored search: BRIL-2 B); the
run's summary, accuracies and `classifier_version`.

Differences from the hand procedure, all deliberate:
- **Only stale runs** — `classifier_version` NULL or below the current one; a run already
  at the current version is left as it is (the tool rewrites every run, which for such a
  run is a no-op: its recompute pass is 0).
- **One transaction per run**, not one for the database, so the app stays usable and an
  interrupted relabel resumes on the next open: a run is stamped with the new version in
  the same transaction that writes its labels.
- **No dry run and no approval**: this is for testers' databases. The owner's database is
  relabelled by hand: `sidecar/main.py` runs this only in the packaged app (or with
  `ZUGZWANG_AUTO_RELABEL=1`).
- **A verified backup first** (`backup_database`), with Python's sqlite3 backup API, so it
  works where `scripts/backup-db.sh` (bash + the sqlite3 CLI) does not — Windows.

RULE_VERSION needs no counterpart: no stored text depends on it (explanations are computed
when asked for; BETA.md stage 1).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from zugzwang.core import labelling
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.core.database import MoveAnalysis

COUNTED = ("games", "analysis_runs", "move_analyses")

_COLS = ("id, ply, fen_before, played_uci, best_uci, pv_uci, score_before_cp, "
         "score_before_mate, score_after_cp, score_after_mate, second_best_uci, "
         "second_best_cp, second_best_mate, classification, is_book, lines_json, "
         "after_search_cp, after_search_mate, hard_only_move, verify_cp, verify_mate, verify_depth")


class BackupFailed(RuntimeError):
    pass


def stale_run_ids(con: sqlite3.Connection) -> list[int]:
    """Complete runs whose labels an older classifier wrote (NULL = before versioning)."""
    return [r[0] for r in con.execute(
        "SELECT id FROM analysis_runs WHERE completed_at IS NOT NULL AND "
        "(classifier_version IS NULL OR classifier_version < ?) ORDER BY id",
        (CLASSIFIER_VERSION,))]


def _counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in COUNTED}


def backup_database(db_path: Path, backup_dir: Path, tag: str) -> Path:
    """A consistent, self-contained, verified copy of *db_path* in *backup_dir*.

    The checks are `scripts/backup-db.sh`'s: a snapshot through the backup API (safe with
    the app running; never a file copy, W3), converted to a single file (no WAL), kept only
    if `PRAGMA integrity_check` is `ok` and the row counts of games, analysis_runs and
    move_analyses equal the source's. On any failure the partial file is removed and
    `BackupFailed` raised."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"zugzwang-{stamp}-{tag}.db"
    src = sqlite3.connect(str(db_path))
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
            ok = out.execute("PRAGMA integrity_check").fetchone()[0]
            got = _counts(out)
        finally:
            out.close()
        want = _counts(src)
    except sqlite3.Error as exc:
        dest.unlink(missing_ok=True)
        raise BackupFailed(f"backup failed: {exc}") from exc
    finally:
        src.close()
    if ok != "ok" or got != want:
        dest.unlink(missing_ok=True)
        raise BackupFailed(f"backup did not verify: integrity {ok}, counts {got} != {want}")
    return dest


def _to_ma(r) -> MoveAnalysis:
    return MoveAnalysis(
        ply=r[1], fen_before=r[2], played_uci=r[3], best_uci=r[4] or None, pv_uci=r[5] or "",
        score_before_cp=r[6], score_before_mate=r[7], score_after_cp=r[8],
        score_after_mate=r[9], second_best_uci=r[10], second_best_cp=r[11],
        second_best_mate=r[12], classification=r[13], is_book=bool(r[14]),
        lines=json.loads(r[15]) if r[15] else [], after_search_cp=r[16],
        after_search_mate=r[17], hard_only_move=None if r[18] is None else bool(r[18]),
        verify_cp=r[19], verify_mate=r[20], verify_depth=r[21])


def _hom(v) -> int | None:
    return None if v is None else int(v)


def relabel_run(con: sqlite3.Connection, run_id: int) -> int:
    """Relabel one run in its own transaction; returns how many labels changed."""
    con.execute("BEGIN IMMEDIATE")
    try:
        changed = relabel_rows(con, run_id)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return changed


def relabel_rows(con: sqlite3.Connection, run_id: int) -> int:
    """Relabel one run from its stored rows inside the caller's transaction (`relabel_run`; the brilliant backfill,
    `core/brilliant_backfill.apply`); returns how many labels changed."""
    fl = con.execute("SELECT r.final_lines_json, g.source, g.pgn FROM analysis_runs r "
                     "JOIN games g ON g.id = r.game_id WHERE r.id=?", (run_id,)).fetchone()
    if fl is None:
        return 0                                   # replaced by a re-analysis meanwhile
    rows = con.execute(f"SELECT {_COLS} FROM move_analyses WHERE run_id=? ORDER BY ply",
                       (run_id,)).fetchall()
    plies = [_to_ma(r) for r in rows]
    # BRIL-2 B: the mover's rating from the PGN (BR-A/C); BR-F reads the stored search only.
    new = labelling.label_game(plies, json.loads(fl[0]) if fl[0] else [],
                               ratings=labelling.game_ratings(fl[1], fl[2]))
    summ = labelling.summary(new)
    changed = sum(1 for old, m in zip(plies, new) if old.classification != m.classification)
    con.executemany(
        "UPDATE move_analyses SET classification=?, score_after_cp=?, "
        "score_after_mate=?, after_search_cp=?, after_search_mate=?, "
        "hard_only_move=? WHERE id=?",
        [(m.classification, m.score_after_cp, m.score_after_mate, m.after_search_cp,
          m.after_search_mate, _hom(m.hard_only_move), r[0]) for r, m in zip(rows, new)])
    con.execute(
        "UPDATE analysis_runs SET payload_json=?, white_accuracy=?, black_accuracy=?, "
        "classifier_version=? WHERE id=?",
        (json.dumps(summ), summ["white"]["accuracy"], summ["black"]["accuracy"],
         CLASSIFIER_VERSION, run_id))
    return changed


def relabel_stale(db_path: Path, *, backup_dir: Path | None = None,
                  progress: Callable[[int, int], None] | None = None,
                  cancelled: Callable[[], bool] | None = None) -> dict:
    """Back up, then relabel every stale run of *db_path*; verify; report.

    Returns {"runs", "labelsChanged", "backup", "integrity", "unstamped", "from"}. Raises
    `BackupFailed` (nothing written) if the backup does not verify. The database must
    already be migrated (the sidecar's `Database` has opened it)."""
    con = sqlite3.connect(str(db_path), isolation_level=None)
    con.execute("PRAGMA busy_timeout = 5000")
    try:
        ids = stale_run_ids(con)
        if not ids:
            return {"runs": 0, "labelsChanged": 0, "backup": None, "integrity": None,
                    "unstamped": 0, "from": []}
        versions = sorted({str(v) for (v,) in con.execute(
            "SELECT DISTINCT classifier_version FROM analysis_runs WHERE id IN "
            f"({','.join('?' * len(ids))})", ids)})
        tag = f"pre-relabel-v{CLASSIFIER_VERSION}"
        backup = backup_database(db_path, backup_dir or db_path.parent / "backups", tag)
        changed = 0
        for i, rid in enumerate(ids, 1):
            if cancelled is not None and cancelled():
                break
            changed += relabel_run(con, rid)
            if progress is not None:
                progress(i, len(ids))
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        unstamped = len(stale_run_ids(con))
        return {"runs": len(ids) - unstamped, "labelsChanged": changed, "backup": str(backup),
                "integrity": integrity, "unstamped": unstamped, "from": versions}
    finally:
        con.close()
