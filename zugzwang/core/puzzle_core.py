"""
Pure puzzle logic — no Qt imports.

Extracted from core/puzzles.py so that both the PyQt PuzzleImporter and the
Tauri sidecar can share it. core/puzzles.py re-exports glicko2_update, so
existing imports keep working.

import_puzzles_csv() is a generator that streams the Lichess CSV into SQLite
on its own connection and yields one event tuple per step:

    ("progress", rows_imported, total_estimated)   every commit batch
    ("done", rows_imported)                        after the FTS rebuild
    ("cancelled",)                                 when is_cancelled() turns
                                                   True (puzzle rows wiped)
    ("error", message)                             CSV missing
"""

from __future__ import annotations

import csv
import logging
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import chess

import zugzwang.config as C

logger = logging.getLogger(__name__)

_GLICKO_SCALE = 173.7178   # converts between Glicko-2 internal units and Elo-like scale


# ── Glicko-2 rating update ────────────────────────────────────────────────────

def glicko2_update(
    rating: float,
    rd: float,
    volatility: float,
    puzzle_rating: int,
    puzzle_rd: int,
    outcome: float,            # 1.0 = solved clean, 0.0 = failed
    tau: float = C.PUZZLE_TAU,
) -> tuple[float, float, float]:
    """
    Single-game Glicko-2 update (Glickman 2012).
    Returns (new_rating, new_rd, new_volatility).
    Applied per-puzzle rather than per rating period — same approximation
    used by Lichess for puzzle ratings.
    """
    # Step 1: scale to Glicko-2 internal units
    mu    = (rating - 1500.0) / _GLICKO_SCALE
    phi   = rd / _GLICKO_SCALE
    sigma = volatility
    mu_j  = (puzzle_rating - 1500.0) / _GLICKO_SCALE
    phi_j = puzzle_rd / _GLICKO_SCALE

    # Step 2: auxiliary functions
    def g(p: float) -> float:
        return 1.0 / math.sqrt(1.0 + 3.0 * p * p / (math.pi * math.pi))

    def E(m: float, m_j: float, p_j: float) -> float:
        return 1.0 / (1.0 + math.exp(-g(p_j) * (m - m_j)))

    g_j = g(phi_j)
    e_j = E(mu, mu_j, phi_j)

    # Estimated variance
    v = 1.0 / (g_j * g_j * e_j * (1.0 - e_j))

    # Delta (expected improvement)
    delta = v * g_j * (outcome - e_j)

    # Step 4: update volatility via Illinois root-finding algorithm
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex  = math.exp(x)
        phi2 = phi * phi
        d   = phi2 + v + ex
        return (
            ex * (delta * delta - phi2 - v - ex) / (2.0 * d * d)
            - (x - a) / (tau * tau)
        )

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    f_A, f_B = f(A), f(B)
    for _ in range(100):
        C_val  = A + (A - B) * f_A / (f_B - f_A)
        f_C    = f(C_val)
        if f_C * f_B <= 0:
            A, f_A = B, f_B
        else:
            f_A /= 2.0
        B, f_B = C_val, f_C
        if abs(B - A) < 1e-6:
            break

    sigma_new = math.exp(A / 2.0)

    # Step 5-7: update phi and mu
    phi_star = math.sqrt(phi * phi + sigma_new * sigma_new)
    phi_new  = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    mu_new   = mu + phi_new * phi_new * g_j * (outcome - e_j)

    # Step 8: convert back
    new_rating = _GLICKO_SCALE * mu_new + 1500.0
    new_rd     = _GLICKO_SCALE * phi_new

    # Clamp to sensible bounds
    new_rating = max(100.0, min(new_rating, 3500.0))
    new_rd     = max(30.0,  min(new_rd, 350.0))
    return new_rating, new_rd, sigma_new


# ── CSV import ────────────────────────────────────────────────────────────────

_INSERT_SQL = """
    INSERT OR IGNORE INTO puzzles
        (id, fen, moves_uci, rating, rating_deviation,
         popularity, nb_plays, themes, game_url,
         opening_tags, imported_at)
    VALUES (:id, :fen, :moves_uci, :rating, :rating_deviation,
            :popularity, :nb_plays, :themes, :game_url,
            :opening_tags, :imported_at)
"""


def import_puzzles_csv(
    csv_path: Path,
    db_path: Path,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> Iterator[tuple]:
    """Stream the Lichess puzzle CSV into SQLite. Opens its own connection —
    never touches a Database instance. Behaviour is identical to the old
    PuzzleImporter._import loop (row filters, batch size, cancel wipe,
    final FTS rebuild)."""
    if not csv_path.exists():
        yield ("error", f"CSV not found: {csv_path}")
        return

    # Estimate total rows from file size and average row length.
    file_size = csv_path.stat().st_size
    total_est = max(1, int(file_size / 190))  # ~190 bytes/row empirically

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    def _wipe_and_close() -> None:
        conn.execute("DELETE FROM puzzles")
        conn.execute(
            "DELETE FROM meta WHERE key IN"
            " ('puzzles_imported','puzzles_imported_at','puzzles_count')"
        )
        conn.commit()
        conn.close()

    try:
        imported = 0
        batch: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if is_cancelled():
                    _wipe_and_close()
                    yield ("cancelled",)
                    return

                try:
                    pop      = int(row["Popularity"])
                    nb_plays = int(row["NbPlays"])
                except (ValueError, KeyError):
                    continue

                if pop < 0 or nb_plays < 50:
                    continue

                try:
                    rating    = int(row["Rating"])
                    rating_rd = int(row["RatingDeviation"])
                except (ValueError, KeyError):
                    continue

                batch.append({
                    "id":               row["PuzzleId"],
                    "fen":              row["FEN"],
                    "moves_uci":        row["Moves"].strip(),
                    "rating":           rating,
                    "rating_deviation": rating_rd,
                    "popularity":       pop,
                    "nb_plays":         nb_plays,
                    "themes":           row.get("Themes", "").strip(),
                    "game_url":         row.get("GameUrl", "").strip() or None,
                    "opening_tags":     row.get("OpeningTags", "").strip() or None,
                    "imported_at":      now,
                })

                if len(batch) >= C.PUZZLE_IMPORT_BATCH:
                    conn.executemany(_INSERT_SQL, batch)
                    conn.commit()
                    imported += len(batch)
                    batch.clear()
                    yield ("progress", imported, total_est)

        # Final batch
        if batch and not is_cancelled():
            conn.executemany(_INSERT_SQL, batch)
            conn.commit()
            imported += len(batch)

        if is_cancelled():
            _wipe_and_close()
            yield ("cancelled",)
            return

        # Build FTS5 index in one pass (much faster than per-row updates).
        yield ("progress", imported, total_est)
        conn.execute("INSERT INTO puzzle_themes_fts(puzzle_themes_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()
        yield ("done", imported)

    except Exception:
        conn.close()
        raise


# ── Alternate mating moves (F7) ──────────────────────────────────────────────

def alternate_final_mates(fen: str, moves_uci: list[str]) -> list[str]:
    """Every move that delivers mate in place of a puzzle's final solution move.

    Lichess accepts any mate on the last move of a puzzle: if the point is
    "find the mate" and two mates exist, both are correct. The stored solution
    names only one, so matching it exactly rejects answers Lichess would accept.

    Returns the full set of mating moves (including the stored one) when the
    intended final move is itself mate, and [] otherwise — the mate rule applies
    only to the final move, and only when that move actually mates. UCIs are
    returned in full, so a promotion appears as e.g. 'e7e8q' and callers compare
    exactly rather than by from/to.
    """
    if len(moves_uci) < 2:
        return []

    board = chess.Board(fen)
    try:
        for uci in moves_uci[:-1]:
            board.push(chess.Move.from_uci(uci))
        final = chess.Move.from_uci(moves_uci[-1])
    except (ValueError, AssertionError):
        logger.warning("unplayable puzzle line for fen %s", fen)
        return []

    if final not in board.legal_moves:
        return []

    # Only the *final* move gets the alternate-mate rule, and only if the
    # intended move is a mate. A non-mating last move means the puzzle is about
    # something else (winning material, a defensive resource), where a different
    # move is not interchangeable.
    board.push(final)
    intended_is_mate = board.is_checkmate()
    board.pop()
    if not intended_is_mate:
        return []

    mates = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            mates.append(move.uci())
        board.pop()
    return sorted(mates)
