"""The provenance stamp written on every analysis run (FIXPLAN RUN-PROVENANCE).

Before this, a run recorded its engine *name* ("Stockfish"), its depth and a date —
not which binary, how many threads, which code, or whether an opening book was
loaded. The last matters most: without `book_mingame3.bin` no ply can be labelled
`book`, and nothing in the stored row said so. One JSON object per `analysis_runs`
row, in `provenance_json`; NULL means "written before provenance existed".

Everything here is recorded, never consulted: no reader branches on it.
"""

from __future__ import annotations

import functools
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from zugzwang import config as C
from zugzwang.core.classification import CLASSIFIER_VERSION

#: Bump when a key changes meaning, so a reader can tell two stamps apart.
PROVENANCE_VERSION = 2   # 2: adds classifier_version (W22, 2026-11-07)


@functools.lru_cache(maxsize=8)
def file_sha256(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


@functools.lru_cache(maxsize=1)
def code_commit() -> dict:
    """HEAD of the checkout the code runs from, and whether tracked files differ from
    it. A packaged build has no checkout: its commit is the one it was built from, baked
    in at build time, and git is never called (on Windows that would flash a console
    window — BETA, M10)."""
    if C.FROZEN:
        from zugzwang.build_info import info
        return {"commit": info()["commit"], "dirty": False if info()["commit"] else None}

    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", str(C.REPO_ROOT), *args],
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=no") if head else None
    return {"commit": head, "dirty": (bool(status) if status is not None else None)}


def book_state(has_book: bool, book_path: Path = C.OPENINGS_BOOK_PATH) -> dict | None:
    """None when no book was loaded — the run's plies cannot be `book`."""
    if not has_book:
        return None
    return {"file": book_path.name, "sha256": file_sha256(str(book_path))}


def engine_run(*, engine_name: str | None, engine_path: Path | None, depth: int,
               has_book: bool) -> dict:
    """A Stockfish run, configured by `configure_engine_for_analysis`."""
    return {
        "v": PROVENANCE_VERSION,
        "kind": "engine",
        "engine": engine_name,
        "engine_sha256": file_sha256(str(engine_path)) if engine_path else None,
        "depth": depth,
        "after_move_depth": max(depth - 4, 10),
        "threads": C.ANALYSIS_THREADS,
        "hash_mb": C.ANALYSIS_HASH_MB,
        "multipv": C.ANALYSIS_MULTIPV,
        "pv_store_len": C.ANALYSIS_PV_STORE_LEN,
        "final_position_searched": True,
        "book": book_state(has_book),
        "classifier_version": CLASSIFIER_VERSION,
        **code_commit(),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }


def evals_run(*, has_book: bool) -> dict:
    """A run classified from a Lichess PGN's embedded `[%eval]`s — no engine."""
    return {
        "v": PROVENANCE_VERSION,
        "kind": "lichess_evals",
        "book": book_state(has_book),
        "classifier_version": CLASSIFIER_VERSION,
        **code_commit(),
        "stamped_at": datetime.now(timezone.utc).isoformat(),
    }
