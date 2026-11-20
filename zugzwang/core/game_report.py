"""
The game report: what happened in one game, where it turned, and how it ended —
Qt-free, engine-free, and computed from the analysis already stored for the game.

The design and every threshold's evidence are in GAME_REPORT.md. The short form:

- A *swing* is the mover's loss of win probability on one move: the depth-14
  before-search less the depth-14 after-score the move's label reads (GR2-1 / D1,
  B20L, owner 2026-11-13). The game's last move has a swing only on a finished board.
- A *moment* is a swing of at least `SWING`. The report shows the largest
  `SHOWN` of them and says how many there were.
- The *point of no return* is the first position from which every later
  position is decided (`DECIDED` on every stored estimate) for the same side.

This layer selects; it does not grade. It never compares the game to the user's
other games, and every sentence it renders states what the stored analysis says
about this game and nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

import chess

from .. import config as C
from .classification import WPL_GREAT_GAP, win_prob, wpl
from dataclasses import replace

from .compose import _engine_output, explain_ply_full, run_plies
from .explain import stored_ply_row
from .explain_text import (
    CAPTURE_CLAIM_KINDS, ERROR_CLASSES, UNKNOWN_SIDE, _numbered_line, _only_move_first,
    _only_move_second, excuses, material_phrase, rendered_pairs_stored_ply,
)
from .findings import ProvenClaim

# ⚠️ Owner ruling 2026-10-21: do not move SWING or DECIDED without re-running the
# noise-floor and re-analysis probes behind them (GAME_REPORT.md §1.1, §1.3, §1.5:
# `review/scratch/overhaul_stage1.py` section A and `overhaul_stage1_research.py`).
# SWING was 3.3x the depth-10 conservative p99.9 of a move's loss when the move was
# the engine's own best (0.060). Since D1 (owner, 2026-11-13, B20L) a swing reads the
# depth-14 after-score alone, and SWING is 3.02x that estimate's p99.9 with last moves
# excluded (0.0662, `review/scratch/game_report_2/r/r2_floor.out`). DECIDED keeps a
# p99.9 wobble of one search (0.088) inside a clear advantage.
SWING = 0.20
DECIDED = 0.80
SHOWN = 3

# The slow decline (slice 4): in a decided game with no moment at all, the stretch
# where the loser's standing fell furthest, within SLIDE_WINDOW half-moves, stated
# only if it fell by at least SLIDE_MIN. Measured over the 455 such games
# (`review/scratch/slow_decline_window.out`): a 16-half-move window captures a median
# 100 % of the decline (p25 97 %), against 95 % / 79 % for 10. SLIDE_MIN is the
# moment threshold, so "no single move swung it 20 points" and "it fell 20 points
# here" are on the same scale; the fall is between two positions' estimates, so it
# carries two positions' noise (p99 ~0.04 each), not a sum over the window.
SLIDE_WINDOW = 16
SLIDE_MIN = SWING
# GR2-3 (owner, 2026-11-13): a slide may not end before the loser climbs back to this or
# more — the "balanced" band's floor. 18 of 556 slides did (GAME_REPORT.md, B1 defect 1).
SLIDE_RECOVERED = 0.40

# The pieces whose loss names the deciding move (GR2-2): a pawn never does.
_PIECES = frozenset("NBRQ")
_VALUE = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

# GR2-7 (owner, 2026-11-13): a card whose callout names only a pawn, on a swing of at least
# this, says the rating moved far more. A win-probability loss of 0.30 is at least 3.2 pawns
# on the Lichess curve (its steepest slope is 0.092 per 100 cp), so "far more than a pawn"
# is a stored fact, not a judgment. 339 cards on the owner's games (GAME_REPORT.md, B1).
PAWN_QUALIFIER_SWING = 0.30
# Plurals count: "two rooks for the pawn" is not a pawn claim (found reading R3's sample,
# GAME_REPORT.md "Cases behind game_report.py", K1; B1's count of 339 used the singular-only
# pattern).
_PIECE_WORD = re.compile(r"\b(queens?|rooks?|knights?|bishops?)\b")
_PAWN_WORD = re.compile(r"\bpawn\b")


def pawn_qualifier(sentences: list[str], swing: float, band_before: str, band_after: str,
                   whose: str) -> str | None:
    """The qualifier for a card whose callout names a pawn and nothing bigger (no piece, no
    mate) where the swing is PAWN_QUALIFIER_SWING or more; None otherwise. The wording is
    the first of the two offered in review/samples/gr2/r3.md, approved (D2, 2026-11-13)."""
    text = " ".join(sentences)
    if (not text or swing < PAWN_QUALIFIER_SWING or not _PAWN_WORD.search(text)
            or _PIECE_WORD.search(text) or "mate" in text):
        return None
    # Not beside a sentence that qualifies its own claim ("…, though Black was winning
    # anyway", or an excuse): the two would read as a contradiction (GAME_REPORT.md "Cases behind
    # game_report.py", K2).
    if " anyway" in text or any(excuses(t) for t in sentences):
        return None
    return (f"The engine's rating moved far more than a pawn: from {band_before} to "
            f"{band_after} for {whose}.")

# "Found it" (GR2-8, owner 2026-11-13; GAME_REPORT.md B3, R4): W2s needs every stored
# alternative to the hard only move this much worse — each would have been a moment.
FOUND_GAP = SWING
# W4c: the material the game itself gained along the proven line, in pawns, and the user's
# own moves in it (a combination is two or more).
FOUND_MIN_GAIN = 3
FOUND_MIN_OWN_MOVES = 2
# The rules in their order: the first that applies is the game's one "found it".
FOUND_RULES = ("brilliant", "only_move", "combination")
_PIECE_NAMES = {chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook",
                chess.QUEEN: "queen", chess.KING: "king", chess.PAWN: "pawn"}


def _material(board: chess.Board, color: bool) -> int:
    return sum(_VALUE[p.symbol().upper()] * (1 if p.color == color else -1)
               for p in board.piece_map().values())


def brilliant_sentence(fen: str, uci: str) -> str | None:
    """W1: what BRILLIANT.md's rule tested, said: the piece offered and where (B3) and that
    taking it fails (B4). Read off the move; the label is the test. The clause on the engine's
    next two choices went with B5 (BRILLIANT.md "W", 2026-11-19): a nearly-best brilliant has
    a stored alternative within 0.02, so it would be false."""
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    piece = move.promotion or (board.piece_type_at(move.from_square))
    if piece is None or piece == chess.PAWN:
        return None
    return f"A {_PIECE_NAMES[piece]} offered on {chess.square_name(move.to_square)}: taking it fails."


def only_move_found_sentence(ma) -> str | None:
    """W2s: the move played was the stored best, labelled `great`, a stored hard only move,
    and every stored alternative (the 2nd and 3rd lines) is FOUND_GAP or more worse. Said in
    the only-move sentence as ruled (D5): "{X} was the only move that {…}; the next best, {Y},
    {band}." — both clauses read off the stored lines. None where the first clause would not
    be true of the first line ("held the balance" in a position worse than −1.00 or a mate
    against), so the rule fires less rather than says it."""
    if ma.classification != "great" or not ma.hard_only_move or not ma.best_uci \
            or ma.played_uci != ma.best_uci:
        return None
    lines = [ln for ln in (ma.lines or ()) if ln and ln.get("uci")]
    if len(lines) < 2 or lines[0]["uci"][0] != ma.played_uci:
        return None
    w = [_wp(ln.get("cp"), ln.get("mate")) for ln in lines[:3]]
    if any(x is None for x in w) or any(w[0] - x < FOUND_GAP for x in w[1:]):
        return None
    first, second = lines[0], lines[1]
    clause = _only_move_first(first)
    own = {"cp": ma.score_after_cp, "mate": ma.score_after_mate}

    def untrue(line: dict) -> bool:
        return _only_move_first(line) == "held the balance" and (
            line.get("mate") is not None or line.get("cp") is None or line["cp"] <= -100)

    # The first clause must hold of the stored first line and of the move's own depth-14
    # after-score alike (as D5's band is checked): 3 of 143 disagreed on the owner's games
    # (review/scratch/game_report_2/s/r4_measure.out), e.g. "kept the advantage" at +0.64.
    if untrue(first) or untrue(own) or _only_move_first(own) != clause:
        return None
    board = chess.Board(ma.fen_before)
    try:
        x = board.san(chess.Move.from_uci(first["uci"][0]))
        y = board.san(chess.Move.from_uci(second["uci"][0]))
    except ValueError:
        return None
    return f"{x} was the only move that {clause}; the next best, {y}, {_only_move_second(second)}."


# Bands for describing a standing, from one side's point of view.
_BANDS = ((DECIDED, "winning"), (0.60, "better"), (0.40, "balanced"), (1 - DECIDED, "worse"))


NO_SWING_LINE = "No single move swung this game by 20 points or more."


def band(wp: float) -> str:
    for floor, name in _BANDS:
        if wp >= floor:
            return name
    return "losing"


@dataclass(frozen=True)
class _Ply:
    ply: int
    fen: str
    played: str
    best: str | None
    pb: float | None   # mover's win prob before the move, best play
    pa: float | None   # mover's win prob after the played move: the after-move search
    #                    (depth 10), kept for the position estimates (verdicts, graph)
    pa14: float | None = None   # … by the depth-14 after-score (`score_after_*`, ply N+1's
    #                    before-search since version 3): what a moment's swing reads (D1)


def _wp(cp: int | None, mate: int | None) -> float | None:
    if cp is None and mate is None:
        return None
    return win_prob(cp, mate)


def unique_answer(ma) -> bool:
    """The stored best beats the stored second-best by WPL_GREAT_GAP."""
    if not ma.best_uci or ma.second_best_uci is None:
        return False
    pb = _wp(ma.score_before_cp, ma.score_before_mate)
    p2 = _wp(ma.second_best_cp, ma.second_best_mate)
    return pb is not None and p2 is not None and pb - p2 >= WPL_GREAT_GAP


def _search_after(m) -> tuple[int | None, int | None]:
    """The after-move search (depth `max(d−4, 10)`), not the label's after-score.

    Since classifier version 3 `score_after_*` is the depth-14 score of the position the
    move created — the same search as the next ply's before-score — so reading it here
    would collapse the two independent estimates a swing is the more favourable of
    (§1.1) into one. Owner ruling 10 (2026-11-11): the report keeps the two-estimate,
    conservative form with depth 10 as the second estimate; it is `after_search_*`, or
    `score_after_*` on a row labelled before version 3, where that column held it."""
    cp, mate = getattr(m, "after_search_cp", None), getattr(m, "after_search_mate", None)
    if cp is None and mate is None:
        return m.score_after_cp, m.score_after_mate
    return cp, mate


def _plies(moves: Sequence) -> list[_Ply]:
    return [
        _Ply(m.ply, m.fen_before, m.played_uci, m.best_uci or None,
             _wp(m.score_before_cp, m.score_before_mate),
             _wp(*_search_after(m)),
             _wp(m.score_after_cp, m.score_after_mate))
        for m in moves
    ]


def _terminal(board: chess.Board) -> float | None:
    """The side-to-move's exact result on a finished board, or None."""
    if board.is_checkmate():
        return 0.0
    if board.is_stalemate() or board.is_insufficient_material():
        return 0.5
    return None


def swings(plies: list[_Ply], final: chess.Board | None) -> list[float | None]:
    """Loss per move, mover's POV; None where it cannot be measured.

    GR2-1 as ruled in D1 (owner, 2026-11-13; GAME_REPORT.md "R2", B20L): the depth-14
    before-search less the depth-14 after-score — one estimate, the label's own, so the
    card falls where the move list shows the badge. Until then the swing was the kinder
    of the depth-10 after-search and the next before-search (§1.1; option A).

    §1.1's first rule is kept: the game's last move has a swing only on a finished board,
    read exactly. Its stored after-score is the final position's own search, and 8 of the
    12 engine-best losses of 0.20 or more at depth 14 were last moves (`r2_floor.out`);
    without them 0.20 is 3.02x the depth-14 p99.9 (0.0662).
    """
    out: list[float | None] = []
    for i, p in enumerate(plies):
        last = i == len(plies) - 1
        if p.pb is None:
            out.append(None)
            continue
        if last:
            t = _terminal(final) if final is not None else None
            # the board after the move; the mover is the other side
            out.append(p.pb - (1.0 - t) if t is not None else None)
            continue
        out.append(None if p.pa14 is None else p.pb - p.pa14)
    return out


def moments(plies: list[_Ply], sw: list[float | None]) -> list[int]:
    """Every ply that qualifies as a moment, largest swing first.

    The engine's own top choice never qualifies: it is the move the loss is
    measured against, so a swing there is search disagreement (game 1793).
    """
    out = [i for i, s in enumerate(sw)
           if s is not None and s >= SWING
           and not (plies[i].best and plies[i].played == plies[i].best)]
    out.sort(key=lambda i: -sw[i])
    return out


def white_estimates(plies: list[_Ply], final: chess.Board | None) -> list[list[float]]:
    """Every stored estimate of each position's win prob for White. Position j is
    the position after j plies; a finished final board is scored exactly."""
    est: list[list[float]] = [[] for _ in range(len(plies) + 1)]
    for i, p in enumerate(plies):
        white = " w " in p.fen
        if p.pb is not None:
            est[i].append(p.pb if white else 1.0 - p.pb)
        if p.pa is not None:
            est[i + 1].append(p.pa if white else 1.0 - p.pa)
    if final is not None:
        t = _terminal(final)
        if t is not None:
            est[-1] = [t if final.turn == chess.WHITE else 1.0 - t]
    return est


def verdicts(est: list[list[float]]) -> list[str | None]:
    """'white' / 'black' when every estimate of a position is decided for that
    side; None (in doubt) otherwise, including when there is no estimate."""
    out: list[str | None] = []
    for e in est:
        if e and all(x >= DECIDED for x in e):
            out.append("white")
        elif e and all(x <= 1.0 - DECIDED for x in e):
            out.append("black")
        else:
            out.append(None)
    return out


def point_of_no_return(v: list[str | None]) -> tuple[int, str] | None:
    """(first position from which every position is decided for one side, side)."""
    if not v or v[-1] is None:
        return None
    side = v[-1]
    k = len(v) - 1
    while k > 0 and v[k - 1] == side:
        k -= 1
    return k, side


def slide(
    low: list[float | None], high: list[float | None], end: int, start: int = 0
) -> tuple[int, int, float] | None:
    """(start, stop, fall): the largest fall in the loser's standing within
    SLIDE_WINDOW half-moves, stopping at or before *end*; the shortest such window on
    a tie. None when no window falls by SLIDE_MIN.

    Conservative the same way moments are: a fall is measured from the loser's
    *lowest* estimate of the start position to their *highest* estimate of the end,
    so two searches that disagree about a position cannot manufacture a slide; and
    every position inside the window must be scored.
    *low* / *high* are those per-position extremes (None where unscored).

    The window starts at or after *start*: the loser's last peak before the point of
    no return, where the decline that ended there began — the span the window was
    measured against (`slow_decline_window.out`, "peak -> point of no return").
    Without it the search reached back to swings later reversed: an early blunder
    handed straight back outranked the real drift.
    """
    best: tuple[int, int, float] | None = None
    last = min(end, len(low) - 1)
    for ja in range(start, last + 1):
        if low[ja] is None or high[ja] is None:
            continue
        for jb in range(ja + 1, min(last, ja + SLIDE_WINDOW) + 1):
            # Contiguous only: a window may not cross an unscored position, because a
            # fall measured across moves nobody scored could be one move (game 1484's
            # window first crossed an unscored book stretch).
            if low[jb] is None or high[jb] is None:
                break
            fall = low[ja] - high[jb]
            if best is None or fall > best[2] + 1e-9 or (
                abs(fall - best[2]) <= 1e-9 and jb - ja < best[1] - best[0]
            ):
                best = (ja, jb, fall)
    return best if best is not None and best[2] >= SLIDE_MIN else None


def _last_stretch(v: list[str | None], side: str) -> tuple[int, int] | None:
    """The last run of consecutive positions decided for *side*."""
    end = next((j for j in range(len(v) - 1, -1, -1) if v[j] == side), None)
    if end is None:
        return None
    start = end
    while start > 0 and v[start - 1] == side:
        start -= 1
    return start, end


def _move_label(fen: str, san: str) -> str:
    """'23.Qxb7' / '23…Qxb7', numbered from the position's own FEN: a game can
    start from a set-up position, where ply parity says nothing (game 162)."""
    b = chess.Board(fen)
    return f"{b.fullmove_number}{'.' if b.turn == chess.WHITE else '…'}{san}"


def _move_number(fen: str) -> int:
    return chess.Board(fen).fullmove_number


def _san(fen: str, uci: str | None) -> str | None:
    if not uci:
        return None
    try:
        b = chess.Board(fen)
        return b.san(chess.Move.from_uci(uci))
    except ValueError:
        return None


def _pct(wp: float) -> str:
    return f"{round(100 * wp)} %"


# A clock under this fraction of the starting time is "low" for the time-trouble line.
# A presentation threshold, not a finding: the report says when it happened and how
# many moments came after, and never that the clock caused anything.
LOW_CLOCK = 0.10


def parse_time_control(tc: str | None) -> tuple[int, int] | None:
    """(base seconds, increment) for a real-time control like "600" or "180+2";
    None for daily ("1/86400"), unknown ("-", "?") or absent."""
    if not tc:
        return None
    m = re.fullmatch(r"(\d+)(?:\+(\d+))?", tc.strip())
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def time_spent(
    clocks: Sequence[float | None], base: int, inc: int, white_first: bool = True
) -> list[float | None]:
    """Seconds spent on each move, from the clock left after it.

    `previous own clock - this clock + increment`. Holds on 142 358 of 142 398
    clocked plies (`review/scratch/game_report_clocks.out`); the 40 exceptions are
    all no-increment games where a clock *rose* — time added mid-game, which the
    tags cannot tell apart from thinking time. Those come back None rather than as
    a negative or a clamped number.
    """
    last = [float(base), float(base)]
    out: list[float | None] = []
    for i, c in enumerate(clocks):
        side = (i % 2) if white_first else 1 - (i % 2)
        if c is None:
            out.append(None)
            continue
        spent = last[side] - c + inc
        out.append(round(spent, 1) if spent >= -0.05 else None)
        last[side] = c
    return out


def opening_exit(moves: Sequence[tuple[str, str]], book) -> dict | None:
    """Where the game left the book, as one of four cases (GAME_REPORT.md §1.4).

    *moves* is (fen before, uci) for every move of the game, from the PGN — not the
    stored `is_book` flag, which is stale on 176 plies (W10). The exit is the first
    move that is not a book move:

    - `deviated`      the book had moves here and another was played. The only case
                      in which anyone "left" anything.
    - `no_book_move`  the book has nothing for this position, before its horizon:
                      the line is past what the book covers.
    - `book_ended`    the same at or past `BOOK_HORIZON_PLY`: the book simply ends.
    - `all_book`      every move was a book move.

    None when there is no book (W8) or the book has nothing for the starting
    position (a game from a set-up position): there is no opening to describe.
    """
    if book is None or not book.has_book or not moves:
        return None
    for i, (fen, uci) in enumerate(moves):
        board = chess.Board(fen)
        alts = book.book_moves_by_weight(board)
        move = chess.Move.from_uci(uci)
        if move in alts:
            continue
        if i == 0 and not alts:
            return None
        case = ("deviated" if alts
                else "book_ended" if i >= C.BOOK_HORIZON_PLY else "no_book_move")
        return {
            "case": case,
            "ply": i,
            "side": "white" if board.turn == chess.WHITE else "black",
            "label": _move_label(fen, board.san(move)),
            "bookSans": [board.san(m) for m in alts[:3]],
            # The last book move, which the no-move and ended cases name.
            "lastBookLabel": _move_label(moves[i - 1][0], chess.Board(moves[i - 1][0]).san(
                chess.Move.from_uci(moves[i - 1][1]))) if i > 0 else None,
            "moveNumber": board.fullmove_number,
        }
    return {"case": "all_book", "ply": None, "side": None, "label": None,
            "bookSans": [], "lastBookLabel": None, "moveNumber": None}


def _or_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " or " + items[-1]


def opening_sentence(op: dict, you: str | None, standing: str | None) -> str:
    """One sentence per case. `standing` is the band the position stood in, from the
    report's point of view, or None when that position was never scored."""
    names = {"white": "White", "black": "Black"}

    def who(side: str) -> str:
        if you is None:
            return names[side]
        return "You" if side == you else "Your opponent"

    def with_(band_name: str | None) -> str:
        if band_name is None:
            return ""
        if band_name == "balanced":
            return ", with the position balanced"
        subject = "you" if you is not None else names["white"]
        return f", with {subject} {band_name}"

    case = op["case"]
    if case == "deviated":
        return (f"{who(op['side'])} left the book at {op['label']} — the book has "
                f"{_or_list(op['bookSans'])} here{with_(standing)}.")
    if case == "no_book_move":
        return (f"The book has no move after {op['lastBookLabel']}: the line is past "
                f"what it covers{with_(standing)}.")
    if case == "book_ended":
        return (f"The game was in book until move {op['moveNumber']}, where the book "
                f"ends{with_(standing)}.")
    return "Every move of the game was a book move."


def clock_text(seconds: float) -> str:
    """'3:41', '0:09'; whole seconds, which is what a reader compares."""
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


# ── R5: the headline (GR2-12, -13; templates D4, owner 2026-11-13) ────────────

_DRAW_REASONS = {"stalemate": "stalemate", "insufficient material": "insufficient material",
                 "repetition": "repetition", "agreement": "agreement",
                 "fifty-move rule": "the fifty-move rule"}
_LETTER_WORDS = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen"}
# The app's own games say "abandoned" (core/game.py) for what imports call "abandonment".
# E5 (owner, 2026-11-13): the app's own agreed draw (`GameSession.draw_agreed`) is agreement.
# The import path's bare "draw" names no reason and stays "Drawn at move N." (D4).
_TERMINATION_ALIASES = {"abandoned": "abandonment", "draw_agreed": "agreement"}
CONVERSION_MIN_MOVES = 5


def headline(report: dict) -> tuple[list[str], dict]:
    """The report's headline: two sentences at most, every clause read off a field of
    *report* (GAME_REPORT.md, "R5 headline — templates", as ruled in D4). A clause whose
    field is absent is left out, never approximated; a sentence with no case that applies is
    not said. Returns (sentences, the case of each sentence) — the cases for the corpus
    counts. A pure function of the report dict: nothing else is read."""
    you = report.get("you")
    name = {"white": "White", "black": "Black"}
    basis = report["basis"]
    cases = {"s1": None, "s2": None, "conversion": False}
    if not basis["complete"]:
        cases["s1"] = "analysis incomplete"
        return ([f"Analysis stops after {basis['analysedPlies']} of {basis['gamePlies']} "
                 "half-moves, so there is no verdict on how the game was decided or how it "
                 "ended."], cases)
    labels = {c["ply"]: c["label"] for c in report["moments"]["shown"]}
    result, last = report.get("result"), report.get("lastMove")
    term = _TERMINATION_ALIASES.get(report.get("termination"), report.get("termination"))
    winner = "white" if result == "1-0" else "black" if result == "0-1" else None
    loser = None if winner is None else ("black" if winner == "white" else "white")
    ending, decided = report.get("ending"), report.get("decided")

    def subject(side: str) -> str:
        return name[side] if you is None else "You" if side == you else "Your opponent"

    def object_(side: str) -> str:
        return name[side] if you is None else "you" if side == you else "them"

    def rated(side: str) -> str:
        if not ending or ending.get("loser") != side:
            return ""
        return (f", in a position the engine rated at {_pct(ending['loserWp'])} for "
                f"{object_(side)}")

    out: list[str] = []
    s1 = None
    at = f"at move {last['number']}" if last else None
    if result == "1/2-1/2" and at:
        reason = _DRAW_REASONS.get(term)
        s1 = f"Drawn by {reason} {at}." if reason else f"Drawn {at}."
        cases["s1"] = f"draw by {term}" if reason else "draw, other termination"
    elif winner and term == "checkmate" and last:
        s1 = (f"{name[winner]} won by checkmate, {last['label']}." if you is None
              else f"You won by checkmate, {last['label']}." if winner == you
              else f"You were checkmated, {last['label']}.")
        cases["s1"] = "checkmate"
    elif winner and term in ("timeout", "abandonment") and at:
        verb = "lost on time" if term == "timeout" else "abandoned the game"
        s1 = f"{subject(loser)} {verb} {at}{rated(loser)}."
        cases["s1"] = term + ("" if rated(loser) else ", no final rating")
    elif winner and term == "resignation" and at:
        tail = "" if decided else rated(loser)
        s1 = f"{subject(loser)} resigned {at}{tail}."
        cases["s1"] = "resigned, decided" if decided else (
            "resigned, not decided" + ("" if tail else ", no final rating"))
    else:
        cases["s1"] = "none (termination " + str(term) + ")"
    if s1:
        out.append(s1)

    lead = next((f for f in report.get("fortune", []) if f["kind"] == "lead_lost"), None)
    saved = next((f for f in report.get("fortune", []) if f["kind"] == "saved"), None)
    sl = report.get("slide")
    s2 = None
    if decided and decided.get("byPly") is not None and decided["byPly"] in labels:
        piece = decided.get("piece") if decided.get("byPiece") else None
        s2 = (f"The game was decided at {labels[decided['byPly']]}"
              + (f", which dropped the {piece}" if piece else ""))
        cases["s2"] = "deciding move" + (", piece" if piece else "")
    elif lead and lead.get("peakMove") is not None:
        s2 = f"You were winning at move {lead['peakMove']} ({_pct(lead['peak'])})"
        if lead.get("byPly") is not None and lead["byPly"] in labels:
            s2 += f"; the lead went at {labels[lead['byPly']]}"
        cases["s2"] = "lead lost"
    elif sl and sl.get("fromMove") is not None:
        when = (f"at move {sl['fromMove']}" if sl["fromMove"] == sl["toMove"]
                else f"between moves {sl['fromMove']} and {sl['toMove']}")
        whose = name[sl["side"]] if you is None else "you" if sl["side"] == you else "your opponent"
        s2 = f"It slid {when}, from {_pct(sl['fromWp'])} to {_pct(sl['toWp'])} for {whose}"
        if sl.get("stepPly") is not None and sl["stepPly"] in labels:
            s2 += f"; the largest step was {labels[sl['stepPly']]}"
        cases["s2"] = "slide"
    elif (decided and decided.get("moveNumber") is not None
          and not (last and decided["moveNumber"] == last["number"])):
        side = decided["side"]
        standing = (f"{name[side]} was winning" if you is None else "you were winning"
                    if side == you else "your opponent was winning")
        s2 = f"From move {decided['moveNumber']} {standing}"
        cases["s2"] = "decided, no move"
    elif (saved and saved.get("fromMove") is not None and saved.get("endedBeforeGame")
          and not (last and saved["fromMove"] == last["number"]
                   and not (saved.get("byPly") is not None and saved["byPly"] in labels))):
        # H4 (owner, 2026-11-13, fourth round): after "decided, no move", so a game that
        # was won from a decided position keeps "From move N you were winning" and its clean
        # conversion; E6's "not said" stays after it, so E1 is not newly silenced there.
        # E1 (owner, 2026-11-13): a game won or drawn after being lost — the old "You were
        # losing … and won / drew" line's own fields; the move only where it is a card. Not
        # said where the losing stretch runs to the end of the game (fired less, read in
        # review/samples/gr2/r5b.md: "You were losing at move 22." in a game that ended at
        # move 21). Nor, as E6, where N is the game's last move and no move is named: it
        # repeats sentence 1. The cases: GAME_REPORT.md, "R5b".
        s2 = f"You were losing at move {saved['fromMove']}"
        if saved.get("byPly") is not None and saved["byPly"] in labels:
            s2 += f"; your opponent let it go at {labels[saved['byPly']]}"
        cases["s2"] = "comeback"
    elif (decided and decided.get("moveNumber") is not None and last
          and decided["moveNumber"] == last["number"]):
        # E6 (owner, 2026-11-13): "From move N … winning." says nothing when N is the
        # game's last move (the two cases ruled on: GAME_REPORT.md, third round, E6).
        cases["s2"] = "decided at the last move, not said"
    elif report.get("noSwing"):
        s2 = "No move by either side cost 20 points"
        cases["s2"] = "nothing decided"
    conv = report.get("conversion")
    # "after that" must point at the decided position, from which the moves are counted: only
    # after a sentence that names it. After a slide it read as the slide's end ("It slid
    # between moves 5 and 13 …, and none of your 11 moves after that" counted from move 21;
    # GAME_REPORT.md "Cases behind game_report.py", K3), so there it is not said.
    if (s2 and cases["s2"] in ("deciding move", "deciding move, piece", "decided, no move")
            and conv and decided and you and decided["side"] == you and winner == you
            and conv["moves"] >= CONVERSION_MIN_MOVES and conv["errors"] == 0):
        s2 += f", and none of your {conv['moves']} moves after that was an error"
        cases["conversion"] = True
    if s2:
        out.append(s2 + ".")
    return out, cases


def build_report(
    moves: Sequence,
    *,
    game_plies: int,
    result: str,
    termination: str,
    player_color: str | None,
    depth: int,
    clocks: Sequence[float | None] | None = None,
    time_control: str | None = None,
    pgn_moves: Sequence[tuple[str, str]] | None = None,
    book=None,
    final_lines: Sequence[dict] | None = None,
) -> dict:
    """The report for one game, from its stored `MoveAnalysis` rows.

    `final_lines` is the run's `final_lines_json`: the adjacent-ply check needs it to
    verify a capture claim on the game's last move (explain_text.next_ply_contradicts).

    *game_plies* is the game's length from its PGN. A run with fewer rows stops
    short of the game (W12); everything that needs the final position is then
    withheld, and `basis.complete` says so.

    *clocks* is the `[%clk]` time left after each move, from the PGN, and
    *time_control* its `TimeControl` header. Both optional: Lichess and local games
    have no clocks, and the time element is then simply absent.

    *pgn_moves* is (fen before, uci) for every move of the game and *book* the
    `OpeningsBook`; together they give the opening line. Either missing, no line.
    """
    plies = _plies(moves)
    n = len(plies)
    complete = n > 0 and n >= game_plies and all(p.ply == i for i, p in enumerate(plies))
    final: chess.Board | None = None
    if complete:
        final = chess.Board(plies[-1].fen)
        final.push(chess.Move.from_uci(plies[-1].played))

    sw = swings(plies, final)

    tc = parse_time_control(time_control)
    has_clocks = (tc is not None and clocks is not None and len(clocks) >= n
                  and any(c is not None for c in clocks))
    white_first = n == 0 or " w " in plies[0].fen
    spent = time_spent(clocks, tc[0], tc[1], white_first) if has_clocks else []
    ranked = moments(plies, sw)
    # A loss of SWING or more seen by a stored search where no swing can be measured (the
    # last move on an unfinished board, or no after-score): not a moment, but not evidence
    # that nothing happened either. Game
    # 1308: 5.Nxe5?? (+0.03 -> -5.91), unmeasurable because the reply was a book move
    # left unscored by a pre-F4a run. Where one exists, the report does not claim "no
    # single move" anything, and does not call the game a slow decline.
    unconfirmed = [
        i for i, p in enumerate(plies)
        if sw[i] is None and p.pb is not None
        and any(x is not None and p.pb - x >= SWING for x in (p.pa, p.pa14))
        and not (p.best and p.played == p.best)
    ]
    shown = sorted(ranked[:SHOWN])
    named: set[int] = set()   # moments a story line names; each gets a card
    est = white_estimates(plies, final)
    v = verdicts(est)
    you = player_color if player_color in ("white", "black") else None
    pov = you or "white"

    def for_pov(white_wp: float) -> float:
        return white_wp if pov == "white" else 1.0 - white_wp

    # One value per position for the graph: the before-search where there is one,
    # else the after-search of the move that led there. Unscored stays None.
    series: list[float | None] = []
    for j in range(n + 1):
        e = est[j]
        series.append(round(e[0], 4) if e else None)

    # The rule sentences the Review callout shows per ply index, with their findings,
    # filled by the cards (and by the pattern line until R6-5): the explain rules are most of
    # the report's cost (GAME_REPORT.md §14).
    rendered: dict[int, list] = {}
    # With the engine lines: the adjacent-ply check reads the next ply's MultiPV, and
    # the engine-line claim (`compose`) reads the stored lines from `pv_uci`.
    rows_by_ply = {m.ply: {**stored_ply_row(m), "pv_uci": getattr(m, "pv_uci", None) or "",
                           "lines": getattr(m, "lines", None) or [],
                           # T4: the only-move sentence reads the stored T8 property
                           "hard_only_move": getattr(m, "hard_only_move", None)}
                   for m in moves}
    finals = list(final_lines or ())
    # One run for every ply, so whether a ply's callout shows an engine-line claim is
    # computed once (`compose.run_plies` caches it).
    run0 = run_plies(rows_by_ply, moves[0].ply if moves else 0, finals)

    def pairs_at(i: int) -> list:
        """The rule sentences, with their findings, that the Review callout shows for
        this move: none where the callout shows an engine-line claim instead (the
        reversed precedence, `compose`). An unknown side names both players; `None`
        would address the reader."""
        ply = moves[i].ply
        pairs = rendered_pairs_stored_ply(
            rows_by_ply[ply], you or UNKNOWN_SIDE, run=replace(run0, ply=ply))
        if pairs and run0.engine_claim is not None and run0.engine_claim(ply):
            return []
        return pairs

    def rendered_at(i: int) -> list:
        if i not in rendered:
            rendered[i] = pairs_at(i)
        return rendered[i]

    def claims_a_piece(i: int) -> bool:
        """Any claim in the callout for move *i* that the opponent wins a knight, bishop,
        rook or queen because of it, traded or not ("a rook and a pawn for the knight",
        "The bishop on f4 is still hanging")."""
        ply = moves[i].ply
        if run0.engine_claim is not None and run0.engine_claim(ply):
            out = _engine_output(rows_by_ply, ply, finals)
            return (isinstance(out, ProvenClaim) and out.subject == "played"
                    and out.kind == "line_wins_material"
                    and any(t.upper() in _PIECES for t in out.took))
        return any(f.kind in CAPTURE_CLAIM_KINDS and f.subject == "played"
                   and any(pc.piece in _PIECES for pc in f.pieces)
                   for f, _line in rendered_at(i))

    def lost_value(i: int) -> int:
        """The most the callout for move *i* says the opponent wins, in pawns: the
        engine-line claim's pieces taken less given, or the largest piece a capture-claim
        rule sentence names."""
        ply = moves[i].ply
        if run0.engine_claim is not None and run0.engine_claim(ply):
            out = _engine_output(rows_by_ply, ply, finals)
            if isinstance(out, ProvenClaim):
                return (sum(_VALUE[t.upper()] for t in out.took)
                        - sum(_VALUE[t.upper()] for t in out.gave))
            return 0
        return max((_VALUE.get(pc.piece, 0) for f, _line in rendered_at(i)
                    if f.kind in CAPTURE_CLAIM_KINDS and f.subject == "played"
                    for pc in f.pieces), default=0)

    def piece_captures(i: int) -> set[str]:
        """GR2-2 (owner, 2026-11-13): the opponent's captures by which the Review callout
        for this move says they win a piece because of it — the first move of the
        engine-line claim about the played move, where that line takes a knight, bishop,
        rook or queen and gives none back; or the capture a capture-claim rule sentence
        (`CAPTURE_CLAIM_KINDS`, already past the adjacent-ply check) names, where it names
        such a piece. Read off what the callout shows, so the report never names a move
        for a loss the callout does not state. Empty: no such claim."""
        ply = moves[i].ply
        if run0.engine_claim is not None and run0.engine_claim(ply):
            out = _engine_output(rows_by_ply, ply, finals)
            if (isinstance(out, ProvenClaim) and out.subject == "played"
                    and out.kind == "line_wins_material" and out.proof.line
                    and any(t.upper() in _PIECES for t in out.took)
                    and not any(t.upper() in _PIECES for t in out.gave)):
                return {out.proof.line[0]}
            return set()
        return {f.moves["refutation"].uci for f, _line in rendered_at(i)
                if f.kind in CAPTURE_CLAIM_KINDS and f.subject == "played"
                and f.moves.get("refutation") is not None
                and any(pc.piece in _PIECES for pc in f.pieces)}

    name_of = {"white": "White", "black": "Black"}

    def build_cards(shown: list[int]) -> tuple[list[dict], list[list[int]]]:
        cards = []
        carded = set(shown)
        for i in shown:
            p = plies[i]
            mover = "white" if " w " in p.fen else "black"
            before_m, after_m = p.pb, p.pb - sw[i]
            before_w = before_m if mover == "white" else 1.0 - before_m
            after_w = after_m if mover == "white" else 1.0 - after_m
            # One move, one account (owner ruling AUDIT-2, 2026-11-11): the card shows
            # what the Review callout shows for this move — the engine-line claim where
            # there is one, else the rule sentences — and its descriptions, by the same
            # call (`compose.explain_ply_full`).
            full = explain_ply_full(rows_by_ply, p.ply, you or UNKNOWN_SIDE,
                                    final_lines=finals)
            sentences = [text for _src, text in full.shown_claims]
            descriptions = [str(text) for _k, text in full.descriptions]
            reply = None
            if you is not None and mover != you and i + 1 < n and plies[i + 1].ply == p.ply + 1:
                # GR2-6, as amended (owner, 2026-11-13): the user's reply, on every opponent
                # card — "the engine's move" when it was; the engine's move beside it only
                # when the reply is labelled an error; otherwise nothing.
                q = plies[i + 1]
                said = _move_label(q.fen, _san(q.fen, q.played) or q.played)
                if q.best and q.played == q.best:
                    reply = f"You answered {said}, the engine's move."
                elif (q.best and moves[i + 1].classification in ERROR_CLASSES
                      and _san(q.fen, q.best) and (i + 1) not in carded):
                    # D3 (owner, 2026-11-13): not where the reply is the next card of the
                    # same group, which already shows "Best was …".
                    reply = (f"You played {said}; the engine's move was "
                             f"{_move_label(q.fen, _san(q.fen, q.best))}.")
            cards.append({
                "ply": p.ply,
                "side": mover,
                "yours": None if you is None else mover == you,
                "san": _san(p.fen, p.played),
                "bestSan": _san(p.fen, p.best),
                "label": _move_label(p.fen, _san(p.fen, p.played) or p.played),
                "classification": moves[i].classification,
                "swing": round(sw[i], 4),
                "before": round(for_pov(before_w), 4),
                "after": round(for_pov(after_w), 4),
                "bandBefore": band(for_pov(before_w)),
                "bandAfter": band(for_pov(after_w)),
                "sentences": sentences,
                "descriptions": descriptions,
                "reply": reply,
                "qualifier": pawn_qualifier(
                    sentences, sw[i], band(for_pov(before_w)), band(for_pov(after_w)),
                    "you" if you is not None else name_of[pov]),
                # The clock at this move, shown and left to the reader. No claim about
                # pace: moments take a median 1.56x the player's own median move time
                # (stage 1), so "rushed" would be wrong as often as right.
                "spent": spent[i] if has_clocks else None,
                "clockLeft": clocks[i] if has_clocks else None,
                # Retry (slice 5). `unique`: the stored best beats the stored second
                # best by the `great` gap, so with no engine a Try can be judged
                # against the stored best alone. Measured to hold on a fresh depth-18
                # search for 589 of 593 such cards; the 4 exceptions are why a move
                # that is not the stored answer is never called wrong without an
                # engine (GAME_REPORT.md, slice 5).
                "bestUci": p.best,
                "unique": unique_answer(moves[i]),
            })
        # An error and the reply that failed to punish it are one moment on screen.
        groups: list[list[int]] = []
        for c in cards:
            if groups and c["ply"] == groups[-1][-1] + 1:
                groups[-1].append(c["ply"])
            else:
                groups.append([c["ply"]])
        return cards, groups

    def found_it() -> dict | None:
        """GR2-8 (owner, 2026-11-13): at most one "found it" moment per game, the first rule
        that applies — W1 brilliant, else W2s a hard only move every stored alternative to
        which is FOUND_GAP worse, else W4c a combination of two or more of the user's moves
        that the engine proved after the opponent's error and the game followed, move for
        move, to the gain. The first such move in the game within a rule. None where the
        user's side is unknown: the element praises the user."""
        if you is None:
            return None
        mine = [i for i in range(n) if (" w " in plies[i].fen) == (you == "white")]

        def found(i: int, kind: str, sentence: str, **extra) -> dict:
            p = plies[i]
            return {"ply": p.ply, "kind": kind, "side": you,
                    "classification": moves[i].classification,
                    "san": _san(p.fen, p.played),
                    "label": _move_label(p.fen, _san(p.fen, p.played) or p.played),
                    "sentence": sentence, **extra}

        for rule in FOUND_RULES:
            got = {"brilliant": w1, "only_move": w2s, "combination": w4c}[rule](mine, found)
            if got is not None:
                return got
        return None

    def w1(mine, found):
        for i in mine:
            if moves[i].classification == "brilliant":
                text = brilliant_sentence(plies[i].fen, plies[i].played)
                if text:
                    return found(i, "brilliant", text)
        return None

    def w2s(mine, found):
        for i in mine:
            text = only_move_found_sentence(moves[i])
            if text:
                return found(i, "only_move", text)
        return None

    def w4c(mine, found):
        game_uci = [p.played for p in plies]
        for i in range(n - 1):
            if i in mine or moves[i].classification not in ERROR_CLASSES:
                continue
            ply = plies[i].ply
            if run0.engine_claim is None or not run0.engine_claim(ply):
                continue
            claim = _engine_output(rows_by_ply, ply, finals)
            if not isinstance(claim, ProvenClaim) or claim.subject != "played" \
                    or not claim.proof.line:
                continue
            line = list(claim.proof.line)
            start = i if line[0] == plies[i].played else i + 1
            # The game followed the line move for move, to its end.
            if game_uci[start:start + len(line)] != line:
                continue
            board = chess.Board(plies[start].fen)
            user = board.turn if start == i + 1 else not board.turn
            before = _material(board, user)
            own = 0
            for u in line:
                own += board.turn == user
                board.push(chess.Move.from_uci(u))
            if claim.kind == "line_mates":
                if not board.is_checkmate():
                    continue
            elif _material(board, user) - before < FOUND_MIN_GAIN:
                continue
            if own < FOUND_MIN_OWN_MOVES:
                continue
            j = i + 1
            shown_line = line[1:] if start == i else line
            after = _move_label(plies[i].fen, _san(plies[i].fen, plies[i].played) or plies[i].played)
            if len(shown_line) <= C.PV_PRINT_MAX_PLIES:
                moves_text = f": {_numbered_line(plies[j].fen, shown_line)}"
                tail = "" if claim.kind == "line_mates" else \
                    f", winning {material_phrase(claim.took, claim.gave)}"
            else:
                last = chess.Board(plies[j].fen)
                for u in shown_line[:-1]:
                    last.push_uci(u)
                by = f" by move {last.fullmove_number}"
                moves_text = ""
                tail = (f", mating{by}" if claim.kind == "line_mates"
                        else f", winning {material_phrase(claim.took, claim.gave)}{by}")
            what = "the forced mate" if claim.kind == "line_mates" else "the line"
            return found(j, "combination",
                         f"You played {what} the engine proved after {after}{moves_text}{tail}.",
                         afterPly=plies[i].ply, linePlies=len(line), ownMoves=own)
        return None

    def finish() -> dict:
        """Cards for the largest moments plus any moment a story line names: the
        move that threw a win away matters more than a later swing in a position
        already lost (game 1797), and a sentence naming a move with no card
        sends the reader looking for it."""
        cards, groups = build_cards(sorted(set(shown) | named))
        report["moments"]["shown"] = cards
        report["moments"]["groups"] = groups
        report["found"] = found_it()
        # E2 (owner, 2026-11-13): no reply line on an opponent card whose next item is the
        # found-it card beginning with that reply — the card about the user's very next
        # move, with no card of its own between (report.ts `reportItems` puts it there).
        f = report["found"]
        if f is not None:
            carded_plies = {c["ply"] for c in cards}
            for c in cards:
                if (c["reply"] and c["yours"] is False and c["ply"] + 1 == f["ply"]
                        and f["ply"] not in carded_plies):
                    c["reply"] = None
        # R5: context comes after the cards, so its lines point up at them.
        context: list[str] = report["context"]
        if report["opening"] is not None and lines and lines[0] == opening_sentence(
                report["opening"], you, report["opening"].get("band")):
            context.append(lines[0])
        # The per-game repeated-pattern line (slice 6) was removed when the patterns card
        # shipped on Insights (owner ruling R6-5, 2026-11-13; PATTERNS.md §6a).
        low = low_clock()
        if low is not None:
            report["lowClock"] = low
            after = low["momentsAfter"]
            line = (f"Your clock fell under {clock_text(low['threshold'])} at move "
                    f"{_move_number(plies[low['ply']].fen)}.")
            if after:
                line += (f" {after} of your moments below came after that."
                         if after > 1 else " One of your moments below came after that.")
            report["lines"].append(line)
            context.append(line.replace(" moments below came", " moments above came"))
        report["headline"], report["headlineCases"] = headline(report)
        return report

    def low_clock() -> dict | None:
        """The first move of the user's that left their clock under LOW_CLOCK of the
        starting time, within the analysed span. Stated as when, plus how many of the
        user's shown moments came after — a count, not a cause."""
        if not has_clocks or you is None:
            return None
        threshold = LOW_CLOCK * tc[0]
        for i in range(n):
            mover = "white" if " w " in plies[i].fen else "black"
            c = clocks[i]
            if mover == you and c is not None and c < threshold:
                # Strictly after: the move the clock fell on is not "after that"
                # (owner ruling AUDIT-10, 2026-11-11).
                after = sum(1 for m in report["moments"]["shown"]
                            if m["yours"] and m["ply"] > plies[i].ply)
                return {"ply": i, "position": i + 1, "threshold": threshold,
                        "momentsAfter": after}
        return None

    report: dict = {
        "analysed": True,
        "basis": {
            "depth": depth,
            "analysedPlies": n,
            "gamePlies": game_plies,
            "complete": complete,
            "pov": pov,
            "timeControl": time_control if has_clocks else None,
        },
        "series": series,
        "moments": {"total": len(ranked), "shown": [], "groups": []},
        "decided": None,
        "ending": None,
        "fortune": [],
        "lowClock": None,
        "opening": None,
        "slide": None,
        "slideGated": None,
        "slideReversed": None,
        "found": None,
        # R5 (GR2-12, -13): the fields the headline reads, the headline, the context lines.
        "you": player_color if player_color in ("white", "black") else None,
        "result": result,
        "termination": termination,
        "lastMove": None,
        "noSwing": False,
        "conversion": None,
        "headline": [],
        "headlineCases": None,
        "context": [],
        # The story lines as they were before R5: no longer rendered (the headline and
        # the context replace them); kept for the corpus tools and the tests of the
        # verdicts they state.
        "lines": [],
    }
    if n:
        report["lastMove"] = {
            "label": _move_label(plies[-1].fen, _san(plies[-1].fen, plies[-1].played) or plies[-1].played),
            "number": _move_number(plies[-1].fen)}
    lines: list[str] = report["lines"]

    # ── the opening: first, because it comes first ────────────────────────────
    op = opening_exit(pgn_moves or [], book)
    if op is not None:
        # The standing where the sentence points: after the move that left the book,
        # or at the position the book has nothing for. The mean of that position's
        # stored estimates — a description, not a claim about a swing.
        at = None if op["ply"] is None else op["ply"] + (1 if op["case"] == "deviated" else 0)
        standing = None
        if at is not None and at <= n and est[at]:
            standing = band(for_pov(sum(est[at]) / len(est[at])))
        op["band"] = standing
        op["yours"] = None if (you is None or op["side"] is None) else op["side"] == you
        report["opening"] = op
        lines.append(opening_sentence(op, you, standing))
    # The swing rule above is deliberate (§1.1) and stays; but the sentence is a flat
    # statement, and it must not stand beside a badge that says a move lost 20 points or
    # more by its own stored scores (owner ruling AUDIT-8, 2026-11-11). Nothing in its place.
    badged = any(
        m.classification in ("mistake", "miss", "blunder")
        and (m.score_before_cp is not None or m.score_before_mate is not None)
        and (m.score_after_cp is not None or m.score_after_mate is not None)
        and wpl(m.score_before_cp, m.score_before_mate,
                m.score_after_cp, m.score_after_mate) >= SWING
        for m in moves)
    if not ranked and not unconfirmed and not badged:
        report["noSwing"] = True
        lines.append(NO_SWING_LINE)
    if not complete:
        lines.append(
            f"Analysis stops after {n} of {game_plies} half-moves, so there is no "
            "verdict on how the game was decided or how it ended."
        )
        return finish()

    name = {"white": "White", "black": "Black"}

    def move_no(position: int) -> int:
        return _move_number(plies[position].fen if position < n else final.fen())

    def span(a: int, b: int) -> str:
        ma, mb = move_no(a), move_no(b)
        return f"at move {ma}" if ma == mb else f"from move {ma} to move {mb}"

    def who(side: str, *, subject: bool = True) -> str:
        if you is None:
            return name[side]
        if side == you:
            return "you" if not subject else "You"
        return "your opponent" if not subject else "Your opponent"

    def largest_step(a: int, b: int, loser: str) -> int | None:
        """GR2-9 (owner, 2026-11-13): the loser's move inside the slide's window (positions
        a..b) with the largest win-probability loss by its stored scores — the depth-14
        before- and after-scores its label reads — named only when its Review callout shows
        a claim (the card then carries it) and its swing can be measured for the card."""
        best, worst = None, 0.0
        for i in range(a, min(b, n)):
            m = moves[i]
            if (" w " in plies[i].fen) != (loser == "white"):
                continue
            if (m.score_before_cp is None and m.score_before_mate is None) or (
                    m.score_after_cp is None and m.score_after_mate is None):
                continue
            loss = wpl(m.score_before_cp, m.score_before_mate, m.score_after_cp, m.score_after_mate)
            if best is None or loss > worst:
                best, worst = i, loss
        if best is None or sw[best] is None:
            return None
        full = explain_ply_full(rows_by_ply, plies[best].ply, you or UNKNOWN_SIDE,
                                final_lines=finals)
        return best if full.shown_claims else None

    def ended_line(loser: str, termination: str) -> None:
        """How the game ended, with the final position's standing for the loser — the
        estimate kindest to the actual result: the claim is that the loser still stood
        this well, so take the least they could have had."""
        final_est = est[-1]
        lw = min(final_est) if loser == "white" else min(1.0 - x for x in final_est)
        report["ending"] = {"loser": loser, "loserWp": round(lw, 4), "termination": termination}
        verb = {
            "timeout": "lost on time",
            "resignation": "resigned",
            "abandonment": "abandoned the game",
        }.get(termination)
        own = "you" if you == loser else "them"
        if verb:
            lines.append(
                f"{who(loser)} {verb} in a position the engine rated at "
                f"{_pct(lw)} for {own if you else name[loser]}."
            )
        else:
            lines.append(
                f"The game ended ({termination}) with the engine rating the final "
                f"position at {_pct(lw)} for {who(loser, subject=False) if you else name[loser]}."
            )

    def drops_the_piece(i: int) -> bool:
        """GR2-2: move *i* is what lost a piece, by its own callout. Narrowed by reading
        every case on the owner's games (GAME_REPORT.md, R1), each narrowing firing less:

        - labelled an error: a move labelled good or better that "leaves the knight
          hanging" cost under 5 points because the piece was already lost (K4: 12…h5);
        - the same player's previous move did not already lose a piece by its callout
          (K5: 9…g6 had already allowed the rook, so 10…Qf6 did not lose it; K6: "The
          bishop on f4 is still hanging"), and was
          not a capture on the square the piece is now taken on (a recapture, below);
        - where the move itself captures a knight, bishop, rook or queen, the callout's
          loss exceeds it by a piece: 22.gxf3 took a queen while "leaving the bishop on g7
          hanging" (K7), and 10.Qxd2 took a bishop for the rook it lost (K8) — exchanges,
          not a piece dropped; 13…Bxg2 took a bishop and dropped the queen (K9), which
          stands;
        - the opponent's next move is the capture the callout names (below).

        The cases K4–K9 are keyed in GAME_REPORT.md, "Cases behind game_report.py".
        """
        if moves[i].classification not in ERROR_CLASSES or sw[i] is None:
            return False
        board = chess.Board(plies[i].fen)
        took = board.piece_at(chess.Move.from_uci(plies[i].played).to_square)
        if (took is not None and took.symbol().upper() in _PIECES
                and lost_value(i) - _VALUE[took.symbol().upper()] < _VALUE["N"]):
            return False
        prev = i - 2 if i >= 2 and plies[i - 2].ply == plies[i].ply - 2 else None
        if prev is not None and claims_a_piece(prev):
            return False
        # The opponent took it: their next move in the game is the capture the callout
        # names. Where they did not, nothing was lost in the game (13.Qc2 "allows Black to
        # win a queen", and Black played 13…Bc5; GAME_REPORT.md "Cases behind
        # game_report.py", K10).
        nxt = i + 1
        if not (nxt < n and plies[nxt].ply == plies[i].ply + 1
                and plies[nxt].played in piece_captures(i)):
            return False
        # Not a recapture: where the same player's previous move captured on the square
        # the opponent now takes on, the exchange is being completed, not a piece dropped
        # (K11: 13.Nxf6+ took a knight, then 14.Qf4 "left the knight on f6 hanging"; K12:
        # 21…Bxd4, then 22…Qc5; GAME_REPORT.md "Cases behind game_report.py").
        if prev is not None:
            pb = chess.Board(plies[prev].fen)
            pm = chess.Move.from_uci(plies[prev].played)
            if (pb.is_capture(pm) and pm.to_square
                    == chess.Move.from_uci(plies[nxt].played).to_square):
                return False
        return True

    def dropped_piece(i: int) -> str | None:
        """R5's `decided.piece`: the piece the callout's claim says the opponent's next move
        takes — the engine-line claim's one knight, bishop, rook or queen taken, or the one
        such piece a capture-claim rule sentence names for that capture. None where the
        claim names none or more than one: the clause is then left out."""
        ply, nxt = moves[i].ply, plies[i + 1].played
        if run0.engine_claim is not None and run0.engine_claim(ply):
            out = _engine_output(rows_by_ply, ply, finals)
            took = [t.upper() for t in getattr(out, "took", ()) if t.upper() in _PIECES]
            return _LETTER_WORDS[took[0]] if len(took) == 1 else None
        named_pieces = {pc.piece for f, _line in rendered_at(i)
                        if f.kind in CAPTURE_CLAIM_KINDS and f.subject == "played"
                        and f.moves.get("refutation") is not None
                        and f.moves["refutation"].uci == nxt
                        for pc in f.pieces if pc.piece in _PIECES}
        return _LETTER_WORDS[named_pieces.pop()] if len(named_pieces) == 1 else None

    # ── point of no return ────────────────────────────────────────────────────
    winner = "white" if result == "1-0" else "black" if result == "0-1" else None
    pnr = point_of_no_return(v)
    if winner is not None and pnr is not None and pnr[1] == winner:
        k, side = pnr
        by = k - 1 if k >= 1 and (k - 1) in ranked else None
        # "No single move decided it" is reserved for a game with genuinely no moment —
        # none confirmed, none seen by one search only (owner ruling, 2026-10-21). With
        # moments elsewhere, the claim would read as a verdict on the whole game.
        no_moment = not ranked and not any(i < k for i in unconfirmed)
        by_piece = False
        if (by is None and no_moment and not badged and k >= 1
                and (" w " in plies[k - 1].fen) != (side == "white")
                and drops_the_piece(k - 1)):
            # GR2-2 (owner, 2026-11-13): where that clause would stand, but the loser's
            # move into the decided position drops a piece by its own callout, that move
            # decided it (13…Bxg2 dropped the queen; GAME_REPORT.md "Cases behind
            # game_report.py", K9).
            by, by_piece = k - 1, True
        if by is not None:
            named.add(by)
        report["decided"] = {"position": k, "side": side, "byPly": by, "byPiece": by_piece,
                             "piece": dropped_piece(by) if by_piece else None,
                             "moveNumber": move_no(k)}
        if you is not None and side == you:
            # GR2-13: the user's moves from the decided position to the end, and how many
            # of them are labelled an error (inaccuracy, mistake, miss or blunder).
            mine_after = [i for i in range(k, n) if (" w " in plies[i].fen) == (you == "white")]
            report["conversion"] = {
                "moves": len(mine_after),
                "errors": sum(moves[i].classification in ERROR_CLASSES for i in mine_after)}
        standing = (f"{name[side]} was winning" if you is None
                    else "you were winning" if side == you else "your opponent was winning")
        if by is not None:
            label = _move_label(plies[by].fen, _san(plies[by].fen, plies[by].played) or plies[by].played)
            lines.append(f"The game was decided at {label}: from there {standing} to the end.")
        else:
            lines.append(
                f"From move {move_no(k)} {standing}, and it never came back into doubt"
                # Not beside a badge that says a move lost 20 points or more by its own
                # stored scores (owner ruling AUDIT-Q6; the condition is AUDIT-8's).
                + (" — no single move decided it." if no_moment and not badged else ".")
            )
        if by is None:
            # The decline toward the point of no return, when no single move made it.
            # Slow decline (no moment at all, slice 4): said as the game's story.
            # Moments elsewhere (gated slides): computed the same way, then emitted only
            # if no moment and no one-search loss falls inside the window — otherwise
            # that move already explains the stretch, and "slipped" would be wrong.
            loser = "black" if side == "white" else "white"
            mine = [[x if loser == "white" else 1.0 - x for x in e] for e in est]
            low = [min(e) if e else None for e in mine]
            high = [max(e) if e else None for e in mine]
            scored = [j for j in range(k + 1) if low[j] is not None]
            peak = max(scored, key=lambda j: (low[j], j)) if scored else 0
            found = slide(low, high, k, start=peak)
            if found is not None and any(
                    high[j] is not None and high[j] >= SLIDE_RECOVERED
                    for j in range(found[1] + 1, k)):
                # GR2-3 (owner, 2026-11-13): a slide may not end before the loser climbs
                # back to SLIDE_RECOVERED or more on any estimate — the stretch is not
                # what lost the game (GAME_REPORT.md "Cases behind game_report.py", K13).
                # Not shown, and no other
                # window is looked for in its place: firing less, never re-aiming.
                report["slideReversed"] = {"from": found[0], "to": found[1]}
                found = None
            if found is not None and not no_moment:
                a, b, _fall = found
                inside = [i for i in set(ranked) | set(unconfirmed) if a <= i < b]
                if inside:
                    report["slideGated"] = {"from": a, "to": b, "blockedBy": sorted(inside)}
                    found = None
            if found is not None:
                a, b, _fall = found
                step = largest_step(a, b, loser)
                if step is not None:
                    named.add(step)
                report["slide"] = {"from": a, "to": b, "side": loser,
                                   "fromWp": round(low[a], 4), "toWp": round(high[b], 4),
                                   "fromMove": move_no(a), "toMove": move_no(b),
                                   "scope": "game" if no_moment else "stretch",
                                   "stepPly": None if step is None else plies[step].ply}
                step_text = "" if step is None else (
                    " The largest step was "
                    f"{_move_label(plies[step].fen, _san(plies[step].fen, plies[step].played) or plies[step].played)}.")
                ma, mb = move_no(a), move_no(b)
                if no_moment:
                    whose = (name[loser] if you is None else "you" if loser == you
                             else "your opponent")
                    when = f"at move {ma}" if ma == mb else f"between moves {ma} and {mb}"
                    lines.append(
                        f"It slid {when}, from {_pct(low[a])} to {_pct(high[b])} for {whose}."
                        + step_text
                    )
                else:
                    # Scoped to the stretch: moments exist elsewhere in this game.
                    position = (f"{name[loser]}'s position" if you is None
                                else "your position" if loser == you
                                else "your opponent's position")
                    when = f"At move {ma}" if ma == mb else f"Between moves {ma} and {mb}"
                    lines.append(
                        f"{when} {position} slipped from {_pct(low[a])} to "
                        f"{_pct(high[b])}." + step_text
                    )
        # GR2-5 (owner, 2026-11-13): how a decided game ended, when it ended on the clock
        # or by abandonment — said in the sentence the report uses for a game that ended
        # off the board (lost on time at 0:00 with only "From move 42 your opponent was
        # winning"; GAME_REPORT.md "Cases behind game_report.py", K14).
        if termination in ("timeout", "abandonment") and est[-1]:
            ended_line("black" if side == "white" else "white", termination)
    elif winner is not None and not est[-1]:
        # 34 games: resigned or abandoned inside an unscored book stretch.
        lines.append("The game ended before the engine had scored a position near the "
                     "end, so there is no verdict on how it ended.")
    elif winner is not None:
        # Ended off the board: the final position was not decided for the winner.
        if est[-1]:
            ended_line("black" if winner == "white" else "white", termination)

    # ── what it cost: a decided lead lost, or a decided loss saved ───────────
    if you is not None:
        them = "black" if you == "white" else "white"
        outcome = "draw" if result == "1/2-1/2" else "won" if winner == you else "lost" if winner else None
        ranked_set = set(ranked)

        def moment_at(side: str, position: int) -> int | None:
            """The move played from *position*, if it is *side*'s and a moment.
            Named only then: a later error is not what lost a lead that had
            already gone, and the cards show it anyway."""
            if position in ranked_set and (" w " in plies[position].fen) == (side == "white"):
                return position
            return None

        if outcome in ("lost", "draw"):
            s = _last_stretch(v, you)
            if s is not None:
                a, b = s
                peak_j = max(range(a, b + 1), key=lambda j: min(for_pov(x) for x in est[j]))
                peak = min(for_pov(x) for x in est[peak_j])
                went = moment_at(you, b)
                if went is not None:
                    named.add(went)
                report["fortune"].append({"kind": "lead_lost", "from": a, "to": b,
                                          "peak": round(peak, 4), "peakAt": peak_j,
                                          "peakMove": move_no(peak_j), "byPly": went})
                tail = (f" The lead went at "
                        f"{_move_label(plies[went].fen, _san(plies[went].fen, plies[went].played) or '')}."
                        if went is not None else "")
                lines.append(
                    f"You were winning {span(a, b)} "
                    f"({'' if move_no(a) == move_no(b) else 'best '}{_pct(peak)}) and "
                    f"{'lost' if outcome == 'lost' else 'drew'}." + tail
                )
        if outcome in ("won", "draw"):
            s = _last_stretch(v, them)
            if s is not None:
                a, b = s
                let_go = moment_at(them, b)
                if let_go is not None:
                    named.add(let_go)
                # E1's reading (2026-11-13): the stretch ended before the game did — a scored
                # position follows it. Where it runs to the end (won on time, or drawn, still
                # lost) there was no comeback for the headline to tell.
                report["fortune"].append({"kind": "saved", "from": a, "to": b, "byPly": let_go,
                                          "fromMove": move_no(a),
                                          "endedBeforeGame": any(est[j] for j in range(b + 1, n + 1))})
                tail = (f" Your opponent let it go at "
                        f"{_move_label(plies[let_go].fen, _san(plies[let_go].fen, plies[let_go].played) or '')}."
                        if let_go is not None else "")
                lines.append(
                    f"You were losing {span(a, b)} and {'won' if outcome == 'won' else 'drew'}." + tail
                )
    # GR2-4, as amended (owner, 2026-11-13): "No single move swung…" goes where another
    # story line says how the game went — a slide, a point of no return, a lead lost.
    # Where it would be the report's only story line it stays, until the headline (R5).
    if NO_SWING_LINE in lines and (
            report["decided"] is not None or report["slide"] is not None
            or any(f["kind"] == "lead_lost" for f in report["fortune"])):
        lines.remove(NO_SWING_LINE)
    return finish()
