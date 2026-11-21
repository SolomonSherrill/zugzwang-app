"""Read-only figures for the redesigned Review (UI-BUILD B3; DESIGN.md "Review: report").

Nothing here is new judgement: every figure is an existing rule applied to stored data.

- **Phases** are each game's own division (`core/divider.py`, transcribed from Lichess), over
  the board before each ply, exactly as Insights divides a game (`insights._phase_buckets`
  reads `move_analyses.fen_before`). Never move numbers (DESIGN.md, ruling 14).
- **Accuracy by phase** is the stored game accuracy's own formula
  (`classification.game_accuracy`: Lichess's per-move curve, volatility weights over the
  whole game, the blend of weighted and harmonic means) with the moves grouped by phase. The
  weights come from the whole game's eval chain, so a phase's figure is the game figure
  restricted to its moves; all three phases together give back the stored accuracy.
- **Tactical errors** (owner ruling 3; ruling 1 of 2026-11-20, third): an error is tactical
  only when gate P proves a forcing line for it, read through `compose._engine_output` (gate P
  less the claims the audit rulings silence, i.e. what the Review screen itself may show).
  An error without one has no kind: the word "Positional" is never printed. The errors are the
  plies labelled mistake, miss or blunder; the Report reads "Tactical errors: N of M".
- **Clocks**: the PGN's `[%clk]` after each move and the time spent on it
  (`game_report.time_spent`), when the game has clocks.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import chess

from .classification import (PlyScore, _blend, _has_score, _volatility_weights,
                             _white_pov_pct, move_accuracy_pct, wpl)
from .compose import _engine_output
from .divider import divide, phase_at
from .findings import ProvenClaim
from .game_report import parse_time_control, time_spent

PHASES = ("opening", "middlegame", "endgame")
#: The labels counted as errors in the Report's "Tactical errors: N of M" row (M counts these).
ERROR_CLASSES = ("mistake", "miss", "blunder")


def division(fens_before: Sequence[str]) -> tuple[int | None, int | None]:
    """(first middlegame ply, first endgame ply) over the boards before each ply."""
    return divide([f.split(" ", 1)[0] for f in fens_before])


def phase_of_plies(fens_before: Sequence[str]) -> list[str]:
    middle, end = division(fens_before)
    return [phase_at(i, middle, end) for i in range(len(fens_before))]


def accuracy_by_phase(scores: Sequence[PlyScore], phases: Sequence[str]
                      ) -> dict[str, dict[str, float | None]]:
    """`game_accuracy`, grouped: {colour: {phase: accuracy rounded to 0.1, or None}}."""
    out: dict[str, dict[str, float | None]] = {
        c: {p: None for p in PHASES} for c in ("white", "black")}
    if not scores:
        return out
    chain: list[float | None] = [_white_pov_pct(p.before_cp, p.before_mate, p.mover)
                                 for p in scores]
    last = scores[-1]
    chain.append(_white_pov_pct(last.after_cp, last.after_mate, last.mover))
    weights = _volatility_weights(chain, len(scores))
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for p, weight, phase in zip(scores, weights, phases):
        if weight is None or p.mover not in out:
            continue
        if not (_has_score(p.before_cp, p.before_mate) and _has_score(p.after_cp, p.after_mate)):
            continue
        acc = move_accuracy_pct(wpl(p.before_cp, p.before_mate, p.after_cp, p.after_mate))
        groups.setdefault((p.mover, phase), []).append((acc, weight))
    for (color, phase), pairs in groups.items():
        v = _blend(pairs)
        out[color][phase] = round(v, 1) if v is not None else None
    return out


def error_kinds(rows: Mapping[int, Mapping], final_lines: list[dict] | None) -> list[dict]:
    """Every error ply with its kind: 'tactical' when gate P proves a forcing line (a
    `ProvenClaim`), else None (ruling 3; never 'positional', ruling 1 of 2026-11-20)."""
    out = []
    for ply in sorted(rows):
        row = rows[ply]
        cls = row.get("classification")
        if cls not in ERROR_CLASSES:
            continue
        proven = isinstance(_engine_output(rows, ply, final_lines), ProvenClaim)
        out.append({"ply": ply, "side": "white" if " w " in row["fen_before"] else "black",
                    "classification": cls, "kind": "tactical" if proven else None})
    return out


def error_counts(errors: Sequence[Mapping]) -> dict[str, dict[str, int]]:
    """{colour: {"tactical": N, "errors": M}}: "Tactical errors: N of M"."""
    counts = {c: {"tactical": 0, "errors": 0} for c in ("white", "black")}
    for e in errors:
        counts[e["side"]]["errors"] += 1
        if e["kind"] == "tactical":
            counts[e["side"]]["tactical"] += 1
    return counts


def clock_series(clocks: Sequence[float | None], time_control: str | None, white_first: bool
                 ) -> dict:
    """The clock after each move and the seconds spent on it; empty when the game has none."""
    tc = parse_time_control(time_control)
    has = tc is not None and any(c is not None for c in clocks)
    if not has:
        return {"timeControl": None, "base": None, "increment": None, "clocks": [], "spent": []}
    assert tc is not None
    return {"timeControl": time_control, "base": tc[0], "increment": tc[1],
            "clocks": list(clocks), "spent": time_spent(clocks, tc[0], tc[1], white_first)}


def fens_before_moves(board: chess.Board, moves: Sequence[chess.Move]) -> list[str]:
    out = []
    b = board.copy()
    for m in moves:
        out.append(b.fen())
        b.push(m)
    return out
