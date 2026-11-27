"""BRIL-3 C (owner, 2026-11-27; BRILLIANT.md "BRIL-3"): the brilliant backfill.

Classifier version 11 turns BR-F on, and BR-F's check (2) reads a depth-22 search stored on the row (`verify_*`), which
a relabel never runs. A run analysed before version 11 has no such search, so its BR-F candidates keep the label version
10 gives them. This module fills that in, per complete run already at the current classifier version:

1. **BR-F**: every ply where `labelling.brilliant_path` asks for the verification search (a candidate) and none is
   stored gets the search (`verification_search`: the position after the move, depth `BRILLIANT_VERIFY_DEPTH`, one
   search in a new game, as the analysis loop runs it). A failed search is not stored ("not searched").
2. **M1**, "The only move that avoids mate." (behind `ONLY_MOVE_AVOIDS_MATE`, off): every brilliant ply of the run, as
   labelled with those searches, gets its proof (`only_move_proof`): each other legal move searched at depth 14
   (`ONLY_MOVE_DEPTH`); proven only when every one gives the opponent a forced mate. It stops at the first that does not.
   Never read from the three stored lines: they only order the search.
3. **The write** (`apply`), one transaction per run: the searches stored, the run relabelled from its stored rows
   (`relabel.relabel_rows`, the relabel every path uses), the proofs stored, and the run stamped
   `analysis_runs.brilliant_backfill` = `backfill_key()` so it is never read again at this key.

A run is listed again (`runs_to_backfill`) when its key differs: a newer classifier version or BACKFILL_VERSION. A run
at an older classifier version is left alone (it waits for its relabel: the beta's on open, the owner's by hand). Nothing
is remembered outside the database, so the job resumes after a restart by listing what is missing.

Used by the sidecar's background job (`AnalysisRunner.refill_brilliant`, the analysis engine) and by
`tools/backfill_brilliant.py` (the same functions, for a measurement on a copy)."""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import chess
import chess.engine

from zugzwang import config as C
from zugzwang.core import labelling
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.core.database import MoveAnalysis

#: Bumped when what a backfilled run carries changes, so every run is read again.
BACKFILL_VERSION = 1
#: M1's search depth (the owner's ruling: depth 14, Stockfish 18 bundled, one thread).
ONLY_MOVE_DEPTH = 14
#: The sentence M1 adds to a brilliant move's explanation when proven (and the switch is on).
ONLY_MOVE_SENTENCE = "The only move that avoids mate."


def backfill_key() -> str:
    return f"{CLASSIFIER_VERSION}.{BACKFILL_VERSION}"


def runs_to_backfill(con: sqlite3.Connection) -> list[int]:
    """Complete runs at the current classifier version not yet backfilled at this key, newest first."""
    return [r[0] for r in con.execute(
        "SELECT id FROM analysis_runs WHERE completed_at IS NOT NULL AND classifier_version = ? "
        "AND (brilliant_backfill IS NULL OR brilliant_backfill != ?) ORDER BY id DESC",
        (CLASSIFIER_VERSION, backfill_key()))]


def _extract_mover(info: chess.engine.InfoDict | None, mover: chess.Color) -> tuple[int | None, int | None]:
    score = info.get("score") if info else None
    if score is None:
        return None, None
    pov = score.pov(mover)
    return (None, pov.mate()) if pov.is_mate() else (pov.score(), None)


def verification_search(engine, fen: str, uci: str) -> tuple[int | None, int | None]:
    """BR-F's check (2), as the analysis loop runs it (`analysis.analyze_game_plies`'s `_verify`): the position after
    the move at depth BRILLIANT_VERIFY_DEPTH, one search in a new game (python-chess sends `ucinewgame`), the score
    from the mover's side. Raises on an engine failure (the caller stores nothing)."""
    board = chess.Board(fen)
    mover = board.turn
    board.push(chess.Move.from_uci(uci))
    info = engine.analyse(board, chess.engine.Limit(depth=C.BRILLIANT_VERIFY_DEPTH), multipv=1, game=object())
    return _extract_mover(info[0] if isinstance(info, list) else info, mover)


def only_move_proof(engine, ma: MoveAnalysis, depth: int = ONLY_MOVE_DEPTH) -> dict:
    """M1's proof for a ply: every legal move other than the one played, searched at *depth* (each in a new game),
    gives the opponent a forced mate. The stored lines' first moves are searched first (the likeliest to hold), then
    the rest in UCI order; the search stops at the first move that is not mated. Returns
    {"proven", "depth", "searched", "mates": [[uci, san, mate in N], ...], "refuted_by": uci | None,
    "refuted_score": [cp, mate] | None}. Raises on an engine failure (the caller stores nothing)."""
    board = chess.Board(ma.fen_before)
    played = chess.Move.from_uci(ma.played_uci)
    others = [m for m in board.legal_moves if m != played]
    first = []
    for ln in ma.lines or ():
        u = (ln.get("uci") or [None])[0]
        if u and u != ma.played_uci and chess.Move.from_uci(u) in others and u not in first:
            first.append(u)
    order = [chess.Move.from_uci(u) for u in first] + sorted((m for m in others if m.uci() not in first),
                                                             key=lambda m: m.uci())
    mates: list[list] = []
    out = {"proven": False, "depth": depth, "searched": 0, "mates": mates, "refuted_by": None, "refuted_score": None}
    for m in order:
        san = board.san(m)
        pos = board.copy(stack=False)
        pos.push(m)
        out["searched"] += 1
        if pos.is_game_over():          # a mate or a stalemate of the mover's: not mated
            out["refuted_by"], out["refuted_score"] = m.uci(), None
            return out
        info = engine.analyse(pos, chess.engine.Limit(depth=depth), multipv=1, game=object())
        score = (info[0] if isinstance(info, list) else info).get("score")
        pov = score.pov(pos.turn) if score is not None else None     # the opponent's side
        if pov is None or not pov.is_mate() or pov.mate() <= 0:
            cp, mate = _extract_mover(info[0] if isinstance(info, list) else info, board.turn)
            out["refuted_by"], out["refuted_score"] = m.uci(), [cp, mate]
            return out
        mates.append([m.uci(), san, pov.mate()])
    out["proven"] = bool(others)
    return out


def stored_proof(ma: MoveAnalysis) -> dict | None:
    """M1's stored proof for a ply (`avoids_mate_json`), or None when none was searched."""
    raw = getattr(ma, "avoids_mate_json", None)
    return json.loads(raw) if raw else None


def only_move_sentence(ma: MoveAnalysis) -> str | None:
    """"The only move that avoids mate." for a brilliant ply whose stored proof holds, while
    `ONLY_MOVE_AVOIDS_MATE` is on (off until the owner's read, review/reads/BRIL-3-only-move.md); None otherwise."""
    if not C.ONLY_MOVE_AVOIDS_MATE or ma.classification != "brilliant":
        return None
    proof = stored_proof(ma)
    return ONLY_MOVE_SENTENCE if proof and proof.get("proven") else None


@dataclass
class RunResult:
    run_id: int
    candidates: list[int] = field(default_factory=list)     # plies BR-F asked a search for, none stored
    verify: dict[int, tuple[int | None, int | None]] = field(default_factory=dict)
    proofs: dict[int, dict] = field(default_factory=dict)
    brilliants: list[int] = field(default_factory=list)      # brilliant plies after the searches
    searches: int = 0                                        # engine searches run
    seconds: float = 0.0                                     # time in engine searches
    seconds_by_kind: dict[str, float] = field(default_factory=lambda: {"brf": 0.0, "m1": 0.0})
    failed: bool = False                                     # a search failed: not stamped, read again later


def compute_run(plies: list[MoveAnalysis], final_lines: list[dict] | None,
                ratings: tuple[int | None, int | None] | None, run_id: int, engine,
                *, interrupted: Callable[[], bool] = lambda: False) -> RunResult:
    """The searches one run needs (no database access). *plies* ordered by ply, as stored."""
    res = RunResult(run_id)
    asked: list[int] = []

    def record(m: MoveAnalysis):
        stored = labelling.stored_verify(m)
        if stored is None:
            asked.append(m.ply)
        return stored

    first = labelling.label_game(plies, final_lines, ratings=ratings, verify=record)
    res.candidates = sorted(set(asked))
    by_ply = {m.ply: m for m in plies}
    for ply in res.candidates:
        if interrupted():
            res.failed = True
            return res
        t = time.monotonic()
        try:
            res.verify[ply] = verification_search(engine, by_ply[ply].fen_before, by_ply[ply].played_uci)
        except Exception:
            res.failed = True
        dt = time.monotonic() - t
        res.searches += 1
        res.seconds += dt
        res.seconds_by_kind["brf"] += dt

    def verify(m: MoveAnalysis):
        return res.verify.get(m.ply) or labelling.stored_verify(m)

    # a second pass only when a search was stored: otherwise it reads exactly what the first read
    labelled = labelling.label_game(plies, final_lines, ratings=ratings, verify=verify) if res.verify else first
    res.brilliants = [m.ply for m in labelled if m.classification == "brilliant"]
    for ply in res.brilliants:
        if stored_proof(by_ply[ply]) is not None and getattr(by_ply[ply], "avoids_mate_depth", None) == ONLY_MOVE_DEPTH:
            continue
        if interrupted():
            res.failed = True
            return res
        t = time.monotonic()
        try:
            proof = only_move_proof(engine, by_ply[ply])
            res.proofs[ply] = proof
            res.searches += proof["searched"]
        except Exception:
            res.failed = True
        dt = time.monotonic() - t
        res.seconds += dt
        res.seconds_by_kind["m1"] += dt
    return res


def apply(con: sqlite3.Connection, res: RunResult) -> int:
    """Write one run's result in one transaction (*con* in autocommit, isolation_level None): the searches, the run
    relabelled from its stored rows, the proofs, and the run's key unless a search failed. Returns how many labels
    changed. A run replaced meanwhile (no longer complete at this version) is skipped."""
    from zugzwang.core import relabel
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT classifier_version, completed_at FROM analysis_runs WHERE id=?",
                          (res.run_id,)).fetchone()
        if row is None or row[1] is None or row[0] != CLASSIFIER_VERSION:
            con.execute("ROLLBACK")
            return 0
        con.executemany(
            "UPDATE move_analyses SET verify_cp=?, verify_mate=?, verify_depth=? WHERE run_id=? AND ply=?",
            [(cp, mate, C.BRILLIANT_VERIFY_DEPTH, res.run_id, ply) for ply, (cp, mate) in res.verify.items()])
        changed = relabel.relabel_rows(con, res.run_id) if res.verify else 0
        con.executemany(
            "UPDATE move_analyses SET avoids_mate_depth=?, avoids_mate_json=? WHERE run_id=? AND ply=?",
            [(p["depth"], json.dumps(p), res.run_id, ply) for ply, p in res.proofs.items()])
        if not res.failed:
            con.execute("UPDATE analysis_runs SET brilliant_backfill=? WHERE id=?", (backfill_key(), res.run_id))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return changed


def load_run(db, run_id: int):
    """(plies, final lines, ratings) for *run_id* through a `Database` (read only is enough); None if gone."""
    info = db._conn.execute(
        "SELECT r.final_lines_json, g.source, g.pgn FROM analysis_runs r JOIN games g ON g.id = r.game_id "
        "WHERE r.id=?", (run_id,)).fetchone()
    if info is None:
        return None
    plies = db.load_move_analyses(run_id)
    final = json.loads(info[0]) if info[0] else []
    return plies, final, labelling.game_ratings(info[1], info[2])
