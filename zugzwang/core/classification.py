"""
Move classifier. Pure functions, no Qt dependencies.

Score representation throughout:
  - (cp, mate) where exactly one is not None.
  - cp is centipawns from the *side-to-move*'s perspective.
  - mate is signed: +N means mover has mate in N, -N means opponent has mate in N.
"""

from __future__ import annotations

import math
from typing import NamedTuple, Sequence


# Which classifier wrote a run's labels (`analysis_runs.classifier_version`, W22).
# **3** is the revision of CLASSIFICATION.md (owner rulings 2026-11-11, FIXPLAN CLS-V3-1 …
# 11), built on branch `cls/v3`: labels read the depth-14 after-score (`labelling.py`) and
# miss, great and brilliant are redefined as events. It is set here, on the branch that
# writes version-3 labels; the live database is relabelled to 3 only in stage 6, on the
# owner's approval.
#
# **2** is `classify()` as of the I3 backfill (`c9fc256`, 2026-09-21), which stamped 2 on
# every run it rewrote. The one later change to this file (`8c2126e`, W6+N1) widened
# `best_uci` to accept None and left the body untouched, so 2 is still true of every
# label written today. Bump it with any change that can alter a label, and say in the
# commit which rows it affects. NULL in the column means "written before the write path
# stamped one" — every run from I3 until 2026-11-07 (W9, W22).
CLASSIFIER_VERSION = 12  # 12: FIX-B9, brilliant T1 on: BR-F's "already lost" also catches a piece lost on the
                         # opponent's next move after its best retreat or where it stands (12. Nxb6 is not
                         # brilliant; 18. Nxb5 stays), 2026-11-27. 11: BRIL-3, brilliant BR-F on: a sacrifice B4 and B4b do not prove, sound by the engine's
                         # evaluation (a piece down 5 plies into its own line, the depth-22 search stored per ply
                         # holding within 0.02, no failure shape, the material not already lost), 2026-11-27; a
                         # ply without a stored search keeps version 10's label until the backfill runs. T1 off (on in 12).
                         # 10: BRIL-2, brilliant BR-A/C on: the 0.90 ceiling and the 0.30 floor read the
                         # mover's rating curve (the PGN rating; none: the current curve), 2026-11-26 (every
                         # live run carried 8; 9 was never relabelled live). 9: BRIL-1, brilliant D2 (not for capturing the piece that threatened at least what
                         # the move gives up) and BR-D (B2: not the only legal move), 2026-11-25 (every live
                         # run carried 8). 8: BOOK-PREFIX, book is a prefix: once a ply fails the book rule, no later
                         # ply of the game is book (owner ruling 10, 2026-11-20 fourth; every live run
                         # carried 7). 7: X1, brilliant excludes an immune piece behind a pin, a lost position
                         # (wp before < 0.30) and a cost above WPL_EXCELLENT (2026-11-19; every live
                         # run carried 6). 6: W, brilliant "nearly best" and B5 dropped (2026-11-19; every
                         # live run carried 5). 5: K1, J1 only for a material event, never a missed mate (2026-11-14;
                         # every live run carried 4). 4: brilliant B4b (G1, H2), F1's measure in
                         # labelling (H3), and J1 (a delayed capture is not a miss), 2026-11-13


# ── Constants (overridable via config) ───────────────────────────────────────

# Win-probability sigmoid constant (Lichess calibration)
_WP_K = 0.00368208

# Evaluations are clamped to ±this many centipawns before the sigmoid, and a
# forced mate is mapped to exactly this value. Two consequences, both wanted:
#
#   - Mate is the ceiling, so converting a large advantage *into* a forced mate
#     can never register as a loss. Without the clamp, +2000 cp scores higher
#     than mate and finding the mate would be scored as a small error.
#   - Mate distance does not enter at all. A forced mate is a forced win however
#     long it takes, so turning mate-in-3 into mate-in-9 is not a mistake.
#
# 1000 cp is Lichess's bound; it puts every winning position at wp ≈ 0.975
# rather than at exactly 1.0, which leaves room to measure a real collapse.
WP_CP_CLAMP = 1000

# WPL (win-probability loss) thresholds
WPL_EXCELLENT  = 0.02
WPL_GOOD       = 0.05
WPL_INACCURACY = 0.10
# ⚠️ A deliberate divergence from Lichess (owner ruling 2, 2026-11-11, FIXPLAN CLS-V3-2).
# Lichess's bands are winning-chance deltas 0.1 / 0.2 / 0.3 on the [−1, 1] scale, i.e.
# 0.05 / 0.10 / 0.15 in win probability (`lila/modules/tree/src/main/Advice.scala`,
# verified 2026-11-11). Ours agree on inaccuracy and mistake and put the blunder line at
# 0.20, not 0.15: a loss in (0.15, 0.20] is a `mistake` here and a blunder on Lichess.
# Measured on the audit corpus with the depth-14 after-score: 3,964 plies
# (CLASSIFICATION.md B). Kept on purpose; do not "fix" it to 0.15 without a ruling.
WPL_MISTAKE    = 0.20

# Walked into mate (F1), tightened by owner ruling 3 (2026-11-11, FIXPLAN CLS-V3-3): a move
# into a forced mate is not a blunder by that rule where the mover was already below this
# win probability before the move, or where the move cost WPL_GOOD or less — a mate the
# position had already priced. Such a move takes its label from the ladder instead.
WALKED_INTO_MATE_MIN_WP_BEFORE = 0.05

# Min win-probability gap between best and 2nd-best for Great classification
WPL_GREAT_GAP  = 0.15

# Miss is an event (owner rulings 4–7, 2026-11-11, FIXPLAN CLS-V3-4 … 7). Version 2 called
# any large loss from a winning position (≥ +300 cp, WPL ≥ 0.15) a miss while the mover kept
# ≥ 0.40; 83.9 % of those named an event the board did not show (a win drifting to level).
# Now a miss is: the best move wins a piece or more, or mates, by force (gate P's claim on
# the depth-14 pair, `labelling.missed_win`), or a mate in 4 or fewer is missed in a decided
# position; or mate in one was forfeited — and in every case the played move is not the
# engine's own (finding 14) and the mover is at least level afterwards. Drift is labelled
# by cost (ruling 5); a missed win that also throws the game below level is a blunder or
# mistake by cost (ruling 6).
#
# Ruling 6 (2026-11-11): "a miss leaves the mover at least level (0.50) afterwards". Was
# MISS_STILL_WINNING_WP = 0.40. Refined by ruling R1 (2026-11-11, second round, FIXPLAN
# CLS-V3-R1): 0.45 — a missed forcing win that leaves the mover just short of level is a
# miss; a fall to clearly worse stays a blunder. 0.45 is about −0.54 pawns.
MISS_MIN_WP_AFTER = 0.45

# What "wins a piece or more" means on gate P's claim: pawns' worth kept (CLASSIFICATION.md
# C3, V1b). A minor piece is 3.
MISS_MIN_MATERIAL = 3.0

# Ruling 7: a missed mate in this many or fewer, in a decided position, is a miss (provided
# the played move no longer has a forced mate — AUDIT-4: a slower mate misses nothing).
MISS_DECIDED_MATE_MAX = 4

# Ruling T2 (2026-11-12, third round, FIXPLAN CLS-V3-T2): a critical-move miss needs the
# played move to cost more than this (WPL_GOOD) — on the depth-14 after-score a move that
# cost 0.05 or less kept the evaluation, so "the only move that holds" is false of it.
CRITICAL_MISS_MIN_WPL = WPL_GOOD


def win_prob(cp: int | None, mate: int | None) -> float:
    """Convert (cp, mate) score to [0,1] win probability for the side to move."""
    if mate is not None:
        # mate == 0 means the mover has just delivered mate, so it is a win for
        # them, not a loss. `mate > 0` alone scored it 0.0.
        #
        # This is a deliberate divergence from scalachess, whose `Mate.signum`
        # is `if value > 0 then 1 else -1` and so maps mate == 0 to a *loss*.
        # Lichess never stores that value; we do, and it means the opposite.
        cp = WP_CP_CLAMP if mate >= 0 else -WP_CP_CLAMP
    elif cp is None:
        return 0.5
    cp = max(-WP_CP_CLAMP, min(WP_CP_CLAMP, cp))
    return 1.0 / (1.0 + math.exp(-_WP_K * cp))


def wpl(
    score_before_cp: int | None,
    score_before_mate: int | None,
    score_after_cp: int | None,
    score_after_mate: int | None,
) -> float:
    """Win-probability loss: how much the move cost the mover."""
    wp_best = win_prob(score_before_cp, score_before_mate)
    wp_after = win_prob(score_after_cp, score_after_mate)
    return max(0.0, wp_best - wp_after)


def _can_be_great(loss: float, cp: int | None, mate: int | None) -> bool:
    """Whether a move is even eligible for `great`, before the gap test runs.

    The gap between best and second-best is a fact about the *position*: it says
    the position offered one good option and no other. It says nothing about the
    move that was played. Those come apart in two ways, and the gap test alone
    praised both:

      - The move was the engine's top choice and still lost half a win
        probability. This happens when the before/after searches disagree, which
        at a finite depth they routinely do — 4 stored plies carry `great` with
        WPL >= 0.20, the worst at 0.4749, and two of them walk into forced mate.
      - The position was already lost past the clamp, where every option scores
        the same floor. A "gap" there is an artefact of one line being searched
        further, not a choice the player got right.

    So `great` additionally requires that the move itself was at least Good, and
    that there was still something left to play for.
    """
    if loss > WPL_GOOD:
        return False
    return win_prob(cp, mate) > win_prob(-WP_CP_CLAMP, None)


def _has_score(cp: int | None, mate: int | None) -> bool:
    """True if this side of the move was actually evaluated.

    `win_prob` maps (None, None) to 0.5, so an unscored ply would otherwise look
    like a dead-equal position rather than a missing measurement.
    """
    return cp is not None or mate is not None


def _walked_into_mate(score_after_mate: int | None) -> bool:
    """True if the played move gave the opponent a forced mate."""
    return score_after_mate is not None and score_after_mate < 0


def _allows_mate_in_one(score_after_mate: int | None) -> bool:
    """True if the played move lets the opponent mate on the next move (owner ruling R3)."""
    return score_after_mate is not None and score_after_mate == -1


def _announced_mate_against(score_before_mate: int | None) -> bool:
    """True if the engine announced a forced mate against the mover before the move — a
    mate, not a clamped score (owner ruling T5, 2026-11-12: "a clamped −10.00 or worse with
    no mate is not a forced mate")."""
    return score_before_mate is not None and score_before_mate < 0


def _still_mating_after_move(score_after_mate: int | None) -> bool:
    """True if the mover still has a forced mate after the move they played."""
    return score_after_mate is not None and score_after_mate > 0


def _already_lost_before_move(cp: int | None, mate: int | None) -> bool:
    """True if the mover was already at the losing floor before they moved.

    The score for the position *before* the move is the engine's own best line,
    so if that line was already lost, whatever the player then did did not cause
    it.

    This asks the question on the *clamped* scale rather than looking for an
    announced mate, because WP_CP_CLAMP is what decides which positions are the
    same position. A before-score of −1200 cp has exactly the win probability of
    a forced mate against, so a raw `mate is not None` test splits two cases F2
    ruled identical: the player at −1200 who walks into mate was charged a
    blunder, while the one who stays at −912 is `excellent`, on a WPL change of
    zero either way.
    """
    return win_prob(cp, mate) <= win_prob(-WP_CP_CLAMP, None)


def book_holds(
    is_book: bool,
    score_before_cp: int | None,
    score_before_mate: int | None,
    score_after_cp: int | None,
    score_after_mate: int | None,
) -> bool:
    """The book rule on one ply: the move is in the book and is unscored or costs at most
    `WPL_INACCURACY`. `classify` labels such a ply `book` (after brilliant), and a game's
    book prefix ends at the first ply that fails it (BOOK-PREFIX, owner ruling 10,
    2026-11-20 fourth)."""
    if not is_book:
        return False
    if not (_has_score(score_before_cp, score_before_mate)
            and _has_score(score_after_cp, score_after_mate)):
        return True
    return wpl(score_before_cp, score_before_mate,
               score_after_cp, score_after_mate) <= WPL_INACCURACY


def classify(
    *,
    played_uci: str,
    # None means the engine never named a best move, which is a different claim
    # from "the best move was the one played". Both `is_best` below and the
    # blunder gate's `played_uci != best_uci` read it, so substituting the played
    # move for an absent one manufactures agreement that was never computed.
    best_uci: str | None,
    score_before_cp: int | None,
    score_before_mate: int | None,
    score_after_cp: int | None,
    score_after_mate: int | None,
    second_best_uci: str | None,
    second_best_cp: int | None,
    second_best_mate: int | None,
    is_book: bool,
    only_legal_move: bool = False,
    forfeited_mate_in_one: bool = False,
    brilliant: bool = False,
    missed_win: bool = False,
    great_eligible: bool = False,
    critical_missed: bool = False,
) -> str:
    """
    Classify a move. Returns one of:
      'book' | 'brilliant' | 'great' | 'best' | 'excellent' |
      'good' | 'inaccuracy' | 'mistake' | 'miss' | 'blunder'
    """
    # Brilliant first (owner ruling 9, 2026-11-11, CLS-V3-9): BRILLIANT.md B1–B5, decided
    # from the stored row and the board by `labelling.brilliant` and passed in. It
    # precedes `book` — "even if it's a book move it's still brilliant" — and cannot meet
    # the `best` rows below (B2 needs five legal moves; B1 excludes a mover who had mate).
    if brilliant:
        return "brilliant"

    # Book membership measures how *common* a move is, not whether it is sound:
    # the Scholar's Mate blunder 3...Nf6, which allows mate in one, is in the
    # book because people keep playing it. So a book move keeps the label only
    # while it also plays acceptably.
    #
    # Unscored plies keep it unconditionally. Every book ply analysed before this
    # gate existed was stored with NULL evals, and `win_prob(None, None)` is 0.5
    # — treating that as a real evaluation would score those rows against a
    # fabricated dead-equal position. Absent data means "cannot judge", not "was
    # fine", so the label stands until an eval actually exists.
    #
    # Book is a prefix (BOOK-PREFIX, version 8): *is_book* is the book probe only while
    # every earlier ply of the game passed this rule; the caller decides that
    # (`labelling.label_game`, the analysis loops), since it needs the game.
    if book_holds(is_book, score_before_cp, score_before_mate,
                  score_after_cp, score_after_mate):
        return "book"
    # Not in the book, or played badly enough to be worth flagging — fall through and
    # let the normal ladder name it.

    if only_legal_move:
        return "best"

    # Delivered checkmate — mate == 0 from the mover's perspective means the
    # opponent is already mated; always Best regardless of eval swing.
    if score_after_mate is not None and score_after_mate == 0:
        return "best"

    loss = wpl(score_before_cp, score_before_mate, score_after_cp, score_after_mate)

    # Mate in one was on the board and the player played something else. Both
    # halves are decided by the rules, not by the evaluation — see
    # `forfeited_mate_in_one`. F2's flat ceiling maps a
    # forced mate to WP_CP_CLAMP, so forfeiting mate-in-one for a still-winning
    # +794 cp costs 0.026 win probability. That is correct on the
    # win-probability scale and far below the miss threshold, which is how 48
    # such plies came to read `excellent` — a true statement about the score
    # and an absurd one to show a player.
    #
    # Scoped strictly to mate in one, and deliberately not extended: mate in two
    # or beyond cannot be established from the position alone, only by search,
    # and admitting search results here would reintroduce exactly the
    # mate-distance sensitivity the flat ceiling exists to remove.
    #
    # For the same reason it does not fire while the mover still has a forced
    # mate after the move. That player delayed mate; they did not give it up, and
    # under the flat ceiling a longer mate is not a worse position. Only the loss
    # of the mate is a real event.
    #
    # Only fires while the player is still winning afterwards. A move that
    # forfeits mate *and* throws the game away is already priced by WPL, and
    # `miss` would be an upgrade. That test needs a real eval: without one there
    # is nothing to ask, and `win_prob(None, None)` is 0.5 — a fabricated
    # dead-equal position, not a measurement.
    if (
        forfeited_mate_in_one
        and _has_score(score_after_cp, score_after_mate)
        and not _still_mating_after_move(score_after_mate)
        and win_prob(score_after_cp, score_after_mate) >= MISS_MIN_WP_AFTER
        and played_uci != best_uci
    ):
        return "miss"

    # Walked into forced mate → Blunder, but only if the mate was avoidable.
    # Two ways it was not: the position was already a forced loss whatever the
    # player did, or they played the engine's own top choice (which happens when
    # the before/after searches disagree at a finite depth). Charging a blunder
    # in either case blames the player for the position rather than the move.
    #
    # Ruling 3 (2026-11-11): nor where the mate was already priced — the mover was below
    # WALKED_INTO_MATE_MIN_WP_BEFORE before the move, or the move cost WPL_GOOD or less.
    # A −9 position that becomes "mate in 9" was a blunder at WPL 0.017 before this; 866
    # such plies on the audit corpus (CLASSIFICATION.md B). They fall to the ladder.
    #
    # Ruling R3 (2026-11-11, second round, FIXPLAN CLS-V3-R3) refines ruling 3 for mate in
    # one: allowing mate in one is a blunder unless the opponent already had a forced mate
    # before the move — owner: "if it's m3 and you make it m1, not necessarily a blunder".
    # Ruling T5 (2026-11-12, third round, FIXPLAN CLS-V3-T5) narrows that exception to an
    # *announced* forced mate (`score_before_mate` < 0): "a clamped −10.00 or worse with no
    # mate is not a forced mate". So a move into mate in one is excused only by a mate the
    # engine had already announced, and not by the clamp guard F2 applies to longer mates
    # (49 plies on the audit corpus moved from −10.00 or worse into mate in one).
    if _walked_into_mate(score_after_mate) and played_uci != best_uci and (
        (_allows_mate_in_one(score_after_mate)
         and not _announced_mate_against(score_before_mate))
        or (not _already_lost_before_move(score_before_cp, score_before_mate)
            and win_prob(score_before_cp, score_before_mate) >= WALKED_INTO_MATE_MIN_WP_BEFORE
            and loss > WPL_GOOD)
    ):
        return "blunder"

    # Miss, the event (rulings 4–7; see MISS_MIN_WP_AFTER). `missed_win` is decided from
    # the board and the stored lines by `labelling.missed_win`; the label also needs the
    # played move not to be the engine's (finding 14: `miss` on the engine's first choice
    # is impossible), a real after-score, no forced mate surviving the move, and the mover
    # at least level afterwards. Below level the ladder names it (ruling 6).
    #
    # Ruling R2 (2026-11-11, second round, FIXPLAN CLS-V3-R2): the critical move missed —
    # the best move was the only one that held (the great gap to the stored second line)
    # and hard to find (`labelling.critical_missed`) — is a miss under the same conditions.
    # The floor is R1's 0.45. Ruling T2 (2026-11-12, third round, FIXPLAN CLS-V3-T2): the
    # played move must also cost more than WPL_GOOD — where the depth-14 after-score says
    # it kept the evaluation, "the only move that holds" is false. (T3 and T8 narrow
    # `critical_missed` itself, in `labelling`.)
    if (
        (missed_win or (critical_missed and loss > CRITICAL_MISS_MIN_WPL))
        and played_uci != best_uci
        and _has_score(score_after_cp, score_after_mate)
        and not _still_mating_after_move(score_after_mate)
        and win_prob(score_after_cp, score_after_mate) >= MISS_MIN_WP_AFTER
    ):
        return "miss"

    is_best = played_uci == best_uci

    if is_best:
        # Great: best move in a position where the second option was a Mistake —
        # and where the move played was actually good. See `_can_be_great`.
        #
        # And (owner ruling T7, 2026-11-12, third round, FIXPLAN CLS-V3-T7, which replaces
        # ruling 8's "hard to find"): not an obvious recapture, with more than one legal
        # move — `labelling.great_eligible`, a board fact passed in. Owner: "the ONLY thing
        # that needed to be removed was obvious recaptures. i don't think the move
        # NECESSARILY has to be hard to find."
        if great_eligible and second_best_uci is not None and _can_be_great(
            loss, score_before_cp, score_before_mate
        ):
            wp_best = win_prob(score_before_cp, score_before_mate)
            wp_second = win_prob(second_best_cp, second_best_mate)
            if wp_best - wp_second >= WPL_GREAT_GAP:
                return "great"
        return "best"

    # Threshold ladder
    if loss <= WPL_EXCELLENT:
        return "excellent"
    if loss <= WPL_GOOD:
        return "good"
    if loss <= WPL_INACCURACY:
        return "inaccuracy"
    if loss <= WPL_MISTAKE:
        return "mistake"
    return "blunder"


# ── Accuracy ─────────────────────────────────────────────────────────────────
#
# Lichess's accuracy model, with one deliberate divergence. Lichess scores a
# game from a single chain of position evaluations: the "after" of ply i *is*
# the "before" of ply i+1, so one number serves both. Our engine path searches
# the two positions separately and at different depths, so we have no such
# chain. Option B (see ARCHITECTURE.md): per-move accuracy is computed from the
# before/after pair we actually measured — the same pair `classify` sees, so the
# accuracy and the badge on a ply can never contradict each other — while the
# volatility weights slide over the chain of *before* scores, which is a
# genuine sequence of position evaluations at a consistent depth. The cost is
# that our numbers are not comparable with Lichess's on the same game.

# Fitted curve mapping win-probability loss (as a percentage) to accuracy.
# Full precision: truncating these is what let three different copies of this
# formula drift apart.
_ACC_A = 103.1668100711649
_ACC_K = 0.04354415386753951
_ACC_B = -3.166924740191411

# Lichess credits every move a flat point to allow for the analysis itself
# being imperfect. It is not a rounding artefact; it lifts the whole curve.
_ACC_UNCERTAINTY_BONUS = 1.0

# Volatility weight = standard deviation of a window of the eval chain, so a
# move made in a sharp position counts for more than one made in a dead one.
_ACC_WINDOW_MIN = 2
_ACC_WINDOW_MAX = 8
_ACC_WEIGHT_MIN = 0.5
_ACC_WEIGHT_MAX = 12.0


class PlyScore(NamedTuple):
    """One ply's measured evals, from the mover's perspective."""

    mover: str  # "white" | "black"
    before_cp: int | None
    before_mate: int | None
    after_cp: int | None
    after_mate: int | None


def move_accuracy_pct(loss: float) -> float:
    """Per-move accuracy in [0, 100] from a win-probability loss fraction.

    Lichess short-circuits to 100 when the move improved the position; `wpl`
    already floors the loss at zero, which lands in the same place — a zero
    loss puts the curve at 100 before the bonus is even applied.
    """
    raw = _ACC_A * math.exp(-_ACC_K * loss * 100.0) + _ACC_B
    return max(0.0, min(100.0, raw + _ACC_UNCERTAINTY_BONUS))


def _white_pov_pct(cp: int | None, mate: int | None, mover: str) -> float | None:
    """Win percent for White, from a mover-perspective score.

    The volatility window measures how much an evaluation moves, so it has to
    run over a consistently signed sequence; alternating perspectives would
    read every ply as a swing. Negating is exact rather than approximate: the
    sigmoid is symmetric and the clamp is two-sided, so 1 - wp(x) == wp(-x).
    """
    if not _has_score(cp, mate):
        return None
    wp = win_prob(cp, mate)
    return 100.0 * (wp if mover == "white" else 1.0 - wp)


def _population_stdev(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _volatility_weights(
    chain: Sequence[float | None], ply_count: int
) -> list[float | None]:
    """One weight per ply, from the spread of the eval chain around it.

    The window is short, so the first few plies have no full window behind
    them. Lichess left-pads with repeated copies of the opening window rather
    than shrinking it, which keeps every ply on the same scale; the padding
    count is what makes the weight list line up with the ply list.
    """
    size = max(_ACC_WINDOW_MIN, min(_ACC_WINDOW_MAX, ply_count // 10))
    pad = max(0, min(size, len(chain)) - 2)
    windows: list[Sequence[float | None]] = [chain[:size]] * pad
    if len(chain) <= size:
        windows.append(chain)
    else:
        windows.extend(chain[i:i + size] for i in range(len(chain) - size + 1))

    weights: list[float | None] = []
    for w in windows:
        # A gap anywhere in the window makes its spread unmeasurable, and the
        # ply it covers drops out of the average entirely. Scoring it against a
        # partial window would read a missing eval as a calm position.
        if any(v is None for v in w):
            weights.append(None)
            continue
        sd = _population_stdev([v for v in w if v is not None])
        weights.append(max(_ACC_WEIGHT_MIN, min(_ACC_WEIGHT_MAX, sd)))
    return weights


def _blend(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Mean of the volatility-weighted mean and the harmonic mean.

    The harmonic half is what makes a single catastrophe cost more than a
    string of small errors of the same total size. Its `max(1.0, ...)` floor
    is Lichess's: a 0% move would otherwise divide by zero.
    """
    if not pairs:
        return None
    total_weight = sum(w for _, w in pairs)
    if total_weight == 0:
        return None
    weighted = sum(a * w for a, w in pairs) / total_weight
    harmonic = len(pairs) / sum(1.0 / max(1.0, a) for a, _ in pairs)
    return (weighted + harmonic) / 2.0


def game_accuracy(plies: Sequence[PlyScore]) -> dict[str, float | None]:
    """Per-colour game accuracy in [0, 100], or None for a colour with no data."""
    if not plies:
        return {"white": None, "black": None}

    chain: list[float | None] = [
        _white_pov_pct(p.before_cp, p.before_mate, p.mover) for p in plies
    ]
    last = plies[-1]
    chain.append(_white_pov_pct(last.after_cp, last.after_mate, last.mover))

    weights = _volatility_weights(chain, len(plies))

    by_color: dict[str, list[tuple[float, float]]] = {"white": [], "black": []}
    for p, weight in zip(plies, weights):
        if weight is None or p.mover not in by_color:
            continue
        if not (_has_score(p.before_cp, p.before_mate)
                and _has_score(p.after_cp, p.after_mate)):
            continue
        accuracy = move_accuracy_pct(
            wpl(p.before_cp, p.before_mate, p.after_cp, p.after_mate)
        )
        by_color[p.mover].append((accuracy, weight))

    return {color: _blend(pairs) for color, pairs in by_color.items()}
