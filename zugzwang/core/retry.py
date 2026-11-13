"""
Retry ("Try it") — judging a move the user plays from one of their moments.

Qt-free; it needs an engine, which the caller owns. The design and its evidence are in
GAME_REPORT.md (slice 5). The rule that governs it (owner ruling, 2026-10-21): **err
toward accepting.** A Try that marks a good move wrong teaches something false and the
user cannot tell; one that accepts a slightly inferior move costs much less. Hence:

- a move is accepted when it is within `TRY_TOLERANCE` of the best line;
- its value is the *kinder* of two independent searches — its own line in the
  position's MultiPV, and a search of the position after it — so one search that
  undervalues it cannot reject it (the same two-search rule the moments use, pointed
  the other way).
"""

from __future__ import annotations

from typing import Callable

import chess
import chess.engine

from .. import config as C
from .classification import win_prob

# Owner ruling: "within 0.05 of the best line". In win probability, like everything
# else the report says.
TRY_TOLERANCE = 0.05

# Each of the two searches stops at the live depth or after this many seconds, whichever
# comes first. Uncapped, a Try verdict took a median 2 s but a worst case of 51 s in 20
# positions (`review/scratch/retry_judge_latency.out`) — sharp positions after a blunder,
# where depth 18 explodes. The cap only bites in that tail; the false-reject check was
# re-run with it in place (`retry_judge_check.out`).
TRY_SEARCH_SECONDS = 3.0

# Re-judging at the line (owner ruling (c), 2026-10-21). A move rejected with a loss within
# this margin of TRY_TOLERANCE is judged once more, independently (fresh hash), and accepted
# if either judgement passes. The threshold stays 0.05.
#
# **One-directional, deliberately.** A borderline rejection may flip to accept; a
# borderline acceptance is never re-checked. That asymmetry *is* the err-toward-accepting
# ruling: marking a good move wrong teaches something false, accepting a slightly worse one
# does not. Game 1645's 10…Nxd4 (depth-22 loss 0.039) judged 0.043–0.052 across five runs
# and was rejected 2 of 5 times by a hard line — search noise of about ±0.005 at the line.
#
# **Why not (b), widening to 0.06:** the verdict says "within 5 points", so the displayed
# claim would diverge from the rule; and it relocates the churn to 0.06 rather than removing
# it — a move near the new line flips just as often. Re-judging keeps the rule and the claim
# the same and spends a second search only where the noise lives.
#
# **Measured across the corpus** (2026-10-22, `review/scratch/retry_rejudge_corpus.out`):
# on the stored second-best of every user moment card, the re-judge fired on 85 of 1,209
# first rejections and flipped **29 of 85** — the engine disagrees with itself about a third
# of the time at the line, and without the re-judge those were false rejects. **The safety
# property:** on the moves actually played (0.20+ losses, the control), it fired **0** times
# in 2,623 — no genuine mistake landed within 0.06, so the re-judge cannot rescue a real
# error.
TRY_REJUDGE_MARGIN = 0.01


def _wp(score: chess.engine.PovScore, color: chess.Color) -> float:
    s = score.pov(color)
    return win_prob(s.score(), s.mate())


def judge(
    engine: chess.engine.SimpleEngine,
    fen: str,
    uci: str,
    depth: int = C.ANALYSIS_DEPTH,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> dict | None:
    """Judge *uci* from *fen*. None if cancelled mid-way.

    Returns {accepted, loss, uci, san, bestUci, bestSan, best, value, rejudged, losses},
    where `best` and `value` are the mover's win probability after the best line and after
    the move, and `losses` the loss from each judgement made (one, or two when re-judged).
    """
    first = _judge_once(engine, fen, uci, depth, is_cancelled, fresh=False)
    if first is None:
        return None
    first["rejudged"] = False
    first["losses"] = [first["loss"]]
    if first["accepted"] or first["loss"] > TRY_TOLERANCE + TRY_REJUDGE_MARGIN:
        return first
    second = _judge_once(engine, fen, uci, depth, is_cancelled, fresh=True)
    if second is None:
        return None
    kept = second if second["accepted"] else first
    kept["rejudged"] = True
    kept["losses"] = [first["loss"], second["loss"]]
    return kept


def _judge_once(
    engine: chess.engine.SimpleEngine,
    fen: str,
    uci: str,
    depth: int,
    is_cancelled: Callable[[], bool],
    fresh: bool,
) -> dict | None:
    """One judgement. *fresh* starts a new game (`ucinewgame`), clearing the hash, so a
    re-judgement is independent of the first instead of replaying its search."""
    game = object() if fresh else None
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    if move not in board.legal_moves:
        raise ValueError(f"{uci} is not legal in {fen}")
    mover = board.turn
    san = board.san(move)

    limit = chess.engine.Limit(depth=depth, time=TRY_SEARCH_SECONDS)
    info = engine.analyse(board, limit, multipv=3, game=game)
    if is_cancelled():
        return None
    lines = [(x["pv"][0], _wp(x["score"], mover)) for x in info if x.get("pv")]
    best_move, best = lines[0]
    estimates = [w for m, w in lines if m == move]

    after = board.copy()
    after.push(move)
    if after.is_checkmate():
        estimates.append(1.0)
    elif after.is_stalemate() or after.is_insufficient_material():
        estimates.append(0.5)
    else:
        one = engine.analyse(
            after, chess.engine.Limit(depth=max(depth - 1, 1), time=TRY_SEARCH_SECONDS),
            game=game,
        )
        if is_cancelled():
            return None
        estimates.append(_wp(one["score"], mover))

    value = max(estimates)
    loss = max(0.0, best - value)
    return {
        "accepted": move == best_move or loss <= TRY_TOLERANCE,
        "loss": round(loss, 4),
        "uci": uci,
        "san": san,
        "bestUci": best_move.uci(),
        "bestSan": board.san(best_move),
        "best": round(best, 4),
        "value": round(value, 4),
    }
