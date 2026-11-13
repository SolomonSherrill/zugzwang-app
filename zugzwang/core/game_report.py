"""
The game report: what happened in one game, where it turned, and how it ended —
Qt-free, engine-free, and computed from the analysis already stored for the game.

The design and every threshold's evidence are in GAME_REPORT.md. The short form:

- A *swing* is the mover's loss of win probability on one move, measured against
  the more favourable of the two independent stored searches of the resulting
  position, so one search that undervalues a position cannot create a swing.
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

from .compose import explain_ply_full, run_plies
from .explain import stored_ply_row
from .explain_text import ERROR_CLASSES, UNKNOWN_SIDE, excuses, rendered_pairs_stored_ply

# ⚠️ Owner ruling 2026-10-21: do not move SWING or DECIDED without re-running the
# noise-floor and re-analysis probes behind them (GAME_REPORT.md §1.1, §1.3, §1.5:
# `review/scratch/overhaul_stage1.py` section A and `overhaul_stage1_research.py`).
# SWING is 3.3x the depth-10 conservative p99.9 of a move's loss when the move was
# the engine's own best (0.060), and no such move reaches it. DECIDED keeps a
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

# Bands for describing a standing, from one side's point of view.
_BANDS = ((DECIDED, "winning"), (0.60, "better"), (0.40, "balanced"), (1 - DECIDED, "worse"))


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
    #                    (depth 10), the conservative second estimate (owner ruling 10)


def _wp(cp: int | None, mate: int | None) -> float | None:
    if cp is None and mate is None:
        return None
    return win_prob(cp, mate)


# The repeated-pattern line (slice 6). One phrase per (kind, subject) the measurement
# found it would name (`review/scratch/pattern_line_measure.out`, 3 221 games: these five
# cover all 722 lines). A kind not listed here produces no line rather than a generic
# phrase that might misdescribe it.
PATTERN_PHRASES = {
    ("hangs_piece", "played"): "You dropped material to a capture",
    ("missed_material", "played"): "You missed a chance to win material",
    ("walks_into_mate", "played"): "You allowed a forced mate",
    ("missed_mate", "played"): "You missed a forced mate",
    ("fork", "best"): "You missed a fork",
}

# The two pattern lines that say the user made the same mistake N times (owner ruling
# AUDIT-6, 2026-11-11): they count only moves the run labels an error, whose sentence the
# Review callout shows, and whose sentence does not excuse the move (`explain_text.excuses`).
# Under two such moves, the line does not exist.
ERROR_PATTERNS = frozenset({("hangs_piece", "played"), ("missed_material", "played")})

_COUNT_WORDS = {2: "twice", 3: "three times", 4: "four times", 5: "five times"}
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five"}


def _times(n: int) -> str:
    return _COUNT_WORDS.get(n, f"{n} times")


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


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
             _wp(*_search_after(m)))
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
    """Conservative loss per move, mover's POV; None where it cannot be measured.

    A move needs two searches of its result, or a finished board after it. The
    game's last move has only one search, and 6 of the 7 engine-best moves scoring
    a raw loss >= 0.20 were last moves (GAME_REPORT.md §1.1).
    """
    out: list[float | None] = []
    for i, p in enumerate(plies):
        last = i == len(plies) - 1
        if p.pb is None:
            out.append(None)
            continue
        ests = [] if p.pa is None else [p.pa]
        nxt = plies[i + 1] if not last else None
        if nxt is not None and nxt.pb is not None and nxt.ply == p.ply + 1:
            ests.append(1.0 - nxt.pb)
        if last and final is not None:
            t = _terminal(final)
            if t is not None:
                ests = [1.0 - t]   # the board after the move; the mover is the other side
        enough = len(ests) >= 2 or (last and final is not None and _terminal(final) is not None)
        out.append(p.pb - max(ests) if enough and ests else None)
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
    # A loss of SWING or more seen by only one search: not a moment (the two-search
    # rule cannot confirm it), but not evidence that nothing happened either. Game
    # 1308: 5.Nxe5?? (+0.03 -> -5.91), unmeasurable because the reply was a book move
    # left unscored by a pre-F4a run. Where one exists, the report does not claim "no
    # single move" anything, and does not call the game a slow decline.
    unconfirmed = [
        i for i, p in enumerate(plies)
        if sw[i] is None and p.pb is not None and p.pa is not None
        and p.pb - p.pa >= SWING and not (p.best and p.played == p.best)
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
    # filled by the cards and reused by the pattern line: the explain rules are most of
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

    def build_cards(shown: list[int]) -> tuple[list[dict], list[list[int]]]:
        cards = []
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

    def finish() -> dict:
        """Cards for the largest moments plus any moment a story line names: the
        move that threw a win away matters more than a later swing in a position
        already lost (game 1797), and a sentence naming a move with no card
        sends the reader looking for it."""
        cards, groups = build_cards(sorted(set(shown) | named))
        report["moments"]["shown"] = cards
        report["moments"]["groups"] = groups
        pattern = repeated_pattern()
        if pattern is not None:
            report["pattern"] = pattern
            lines.append(pattern.pop("line"))
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
        return report

    def repeated_pattern() -> dict | None:
        """One line when a finding kind repeats on the user's moves and one of the
        repeats is on a moment card of theirs — the only case where the repetition
        explains the result (GAME_REPORT.md §3, "Themes"). Counted on what the Review
        callout shows (AUDIT-2); the two mistake lines (`ERROR_PATTERNS`) count only
        error-labelled, unexcused moves (AUDIT-6). The kind with the most repeats wins; ties go to the
        order of PATTERN_PHRASES."""
        if you is None:
            return None
        cards = {c["ply"]: c["label"] for c in report["moments"]["shown"] if c["yours"]}
        if not cards:
            return None
        # A pattern needs a repeat on one of the user's cards, so a game whose cards
        # carry no pattern kind is settled without running the rules on every move.
        on_card_kinds = {(f.kind, f.subject) for i in range(len(moves))
                         if plies[i].ply in cards for f, _line in rendered_at(i)}
        if not on_card_kinds & PATTERN_PHRASES.keys():
            return None
        plies_of: dict[tuple[str, str], list[int]] = {}
        for i in range(len(moves)):
            if (" w " in plies[i].fen) != (you == "white"):
                continue
            for f, line in rendered_at(i):
                if (f.kind, f.subject) in ERROR_PATTERNS and (
                        moves[i].classification not in ERROR_CLASSES or excuses(line)):
                    continue
                bucket = plies_of.setdefault((f.kind, f.subject), [])
                if plies[i].ply not in bucket:
                    bucket.append(plies[i].ply)
        order = list(PATTERN_PHRASES)
        best = None
        for key in order:
            hits = plies_of.get(key, [])
            on_cards = [p for p in hits if p in cards]
            if len(hits) >= 2 and on_cards and (best is None or len(hits) > len(best[1])):
                best = (key, hits, on_cards)
        if best is None:
            return None
        (kind, subject), hits, on_cards = best
        labels = [cards[p] for p in on_cards]
        tail = (f"{labels[0]}, one of them, is a moment below." if len(labels) == 1
                else f"{_and_list(labels)}, {_NUMBER_WORDS.get(len(labels), len(labels))} "
                     f"of them, are moments below.")
        return {
            "kind": kind, "subject": subject, "plies": hits, "onCards": on_cards,
            "line": f"{PATTERN_PHRASES[(kind, subject)]} {_times(len(hits))} in this game; {tail}",
        }

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
        "pattern": None,
        "lines": [],
    }
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
        lines.append("No single move swung this game by 20 points or more.")
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

    # ── point of no return ────────────────────────────────────────────────────
    winner = "white" if result == "1-0" else "black" if result == "0-1" else None
    pnr = point_of_no_return(v)
    if winner is not None and pnr is not None and pnr[1] == winner:
        k, side = pnr
        by = k - 1 if k >= 1 and (k - 1) in ranked else None
        if by is not None:
            named.add(by)
        report["decided"] = {"position": k, "side": side, "byPly": by}
        standing = (f"{name[side]} was winning" if you is None
                    else "you were winning" if side == you else "your opponent was winning")
        if by is not None:
            label = _move_label(plies[by].fen, _san(plies[by].fen, plies[by].played) or plies[by].played)
            lines.append(f"The game was decided at {label}: from there {standing} to the end.")
        else:
            # "No single move decided it" is reserved for a game with genuinely no
            # moment — none confirmed, none seen by one search only (owner ruling,
            # 2026-10-21). With moments elsewhere, the claim would read as a verdict on
            # the whole game.
            no_moment = not ranked and not any(i < k for i in unconfirmed)
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
            no_moment = not ranked and not any(i < k for i in unconfirmed)
            loser = "black" if side == "white" else "white"
            mine = [[x if loser == "white" else 1.0 - x for x in e] for e in est]
            low = [min(e) if e else None for e in mine]
            high = [max(e) if e else None for e in mine]
            scored = [j for j in range(k + 1) if low[j] is not None]
            peak = max(scored, key=lambda j: (low[j], j)) if scored else 0
            found = slide(low, high, k, start=peak)
            if found is not None and not no_moment:
                a, b, _fall = found
                inside = [i for i in set(ranked) | set(unconfirmed) if a <= i < b]
                if inside:
                    report["slideGated"] = {"from": a, "to": b, "blockedBy": sorted(inside)}
                    found = None
            if found is not None:
                a, b, _fall = found
                report["slide"] = {"from": a, "to": b, "side": loser,
                                   "fromWp": round(low[a], 4), "toWp": round(high[b], 4),
                                   "scope": "game" if no_moment else "stretch"}
                ma, mb = move_no(a), move_no(b)
                if no_moment:
                    whose = (name[loser] if you is None else "you" if loser == you
                             else "your opponent")
                    when = f"at move {ma}" if ma == mb else f"between moves {ma} and {mb}"
                    lines.append(
                        f"It slid {when}, from {_pct(low[a])} to {_pct(high[b])} for {whose}."
                    )
                else:
                    # Scoped to the stretch: moments exist elsewhere in this game.
                    position = (f"{name[loser]}'s position" if you is None
                                else "your position" if loser == you
                                else "your opponent's position")
                    when = f"At move {ma}" if ma == mb else f"Between moves {ma} and {mb}"
                    lines.append(
                        f"{when} {position} slipped from {_pct(low[a])} to "
                        f"{_pct(high[b])}."
                    )
    elif winner is not None and not est[-1]:
        # 34 games: resigned or abandoned inside an unscored book stretch.
        lines.append("The game ended before the engine had scored a position near the "
                     "end, so there is no verdict on how it ended.")
    elif winner is not None:
        # Ended off the board: the final position was not decided for the winner.
        loser = "black" if winner == "white" else "white"
        final_est = est[-1]
        if final_est:
            # The estimate kindest to the actual result: the claim is that the
            # loser still stood this well, so take the least they could have had.
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
                                          "peak": round(peak, 4), "peakAt": peak_j, "byPly": went})
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
                report["fortune"].append({"kind": "saved", "from": a, "to": b, "byPly": let_go})
                tail = (f" Your opponent let it go at "
                        f"{_move_label(plies[let_go].fen, _san(plies[let_go].fen, plies[let_go].played) or '')}."
                        if let_go is not None else "")
                lines.append(
                    f"You were losing {span(a, b)} and {'won' if outcome == 'won' else 'drew'}." + tail
                )
    return finish()
