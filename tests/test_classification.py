"""Tests for the move classification system."""

import math
import pytest

from zugzwang.core.classification import (
    classify,
    win_prob,
    wpl,
    WP_CP_CLAMP,
    WPL_EXCELLENT,
    WPL_GOOD,
    WPL_INACCURACY,
    WPL_MISTAKE,
)


# ── win_prob ──────────────────────────────────────────────────────────────────

def test_wp_mate_for_mover():
    # Mate is the top of the scale, but the scale stops just short of 1.0 (F2):
    # at exactly 1.0 every subsequent move can only lose, so converting a large
    # advantage into a forced mate scored as an error.
    assert win_prob(None, 3) == win_prob(WP_CP_CLAMP, None)
    assert win_prob(None, 3) > 0.97

def test_wp_mate_against_mover():
    assert win_prob(None, -2) == win_prob(-WP_CP_CLAMP, None)
    assert win_prob(None, -2) < 0.03

def test_wp_is_flat_in_mate_distance():
    # A forced mate is a forced win however long it takes, so mate-in-3 and
    # mate-in-9 must be the same number. Anything monotonic in distance would
    # score "found a slower mate" as a mistake.
    assert win_prob(None, 3) == win_prob(None, 9) == win_prob(None, 99)

def test_wp_zero_cp():
    assert abs(win_prob(0, None) - 0.5) < 0.01

def test_wp_large_positive():
    assert win_prob(1000, None) > 0.97

def test_wp_large_negative():
    assert win_prob(-1000, None) < 0.03


# ── wpl ───────────────────────────────────────────────────────────────────────

def test_wpl_best_move_is_zero():
    # Played the best move — no loss
    assert wpl(20, None, 20, None) == 0.0

def test_wpl_always_nonnegative():
    # Even if played is somehow "better", WPL clamps to 0
    assert wpl(-100, None, 100, None) == 0.0


# ── classify — Book ───────────────────────────────────────────────────────────

def test_book_move():
    result = classify(
        played_uci="e2e4", best_uci="e2e4",
        score_before_cp=20, score_before_mate=None,
        score_after_cp=20, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=True,
    )
    assert result == "book"


# ── classify — Best / Great ───────────────────────────────────────────────────

def test_best_move():
    result = classify(
        played_uci="e2e4", best_uci="e2e4",
        score_before_cp=20, score_before_mate=None,
        score_after_cp=20, score_after_mate=None,
        second_best_uci="d2d4", second_best_cp=18, second_best_mate=None,
        is_book=False,
    )
    assert result == "best"

def test_great_move():
    # Best move with second-best being much worse (Mistake+ level gap)
    result = classify(
        played_uci="g1f3", best_uci="g1f3",
        score_before_cp=30, score_before_mate=None,
        score_after_cp=30, score_after_mate=None,
        second_best_uci="d2d4",
        # Make second-best significantly worse so wp gap >= 0.15
        second_best_cp=-300, second_best_mate=None,
        is_book=False,
        great_eligible=True,
    )
    assert result == "great"


def test_great_needs_the_move_to_be_eligible():
    # *CLS-V3 ruling 8 (2026-11-11), replaced by T7 (2026-11-12).* test_great_move above
    # used to assert `great` from the gap alone; it now also passes `great_eligible` (not an
    # obvious recapture, more than one legal move — `labelling.great_eligible`; under ruling
    # 8 it was `great_hard`). The same gap on an ineligible move is `best`.
    assert classify(
        played_uci="g1f3", best_uci="g1f3",
        score_before_cp=30, score_before_mate=None,
        score_after_cp=30, score_after_mate=None,
        second_best_uci="d2d4", second_best_cp=-300, second_best_mate=None,
        is_book=False,
    ) == "best"

def test_only_legal_move_is_best():
    result = classify(
        played_uci="e1e2", best_uci="e1e2",
        score_before_cp=-500, score_before_mate=None,
        score_after_cp=-500, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
        only_legal_move=True,
    )
    assert result == "best"


# ── classify — Excellent / Good / Inaccuracy / Mistake ───────────────────────

def _mk(played_cp, best_cp):
    """Classify a move given cp values from mover's POV (no mate)."""
    return classify(
        played_uci="a1a2", best_uci="b1b2",  # different → not Best
        score_before_cp=best_cp, score_before_mate=None,
        score_after_cp=played_cp, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )

def test_excellent():
    # 10cp loss near balanced: small WPL
    r = _mk(best_cp=30, played_cp=20)
    assert r == "excellent"

def test_good():
    r = _mk(best_cp=50, played_cp=20)
    assert r in ("good", "inaccuracy")   # depends on exact threshold

def test_inaccuracy_range():
    # Force a moderate WPL by going from +100 to -50 (large-ish but not huge)
    r = _mk(best_cp=100, played_cp=-50)
    assert r in ("inaccuracy", "mistake")

def test_mistake():
    # Significant drop from 0 to -300
    r = _mk(best_cp=0, played_cp=-300)
    assert r in ("mistake", "blunder", "miss")

def test_blunder():
    r = _mk(best_cp=0, played_cp=-700)
    assert r == "blunder"


# ── classify — Blunder (lopsided position) ────────────────────────────────────

def test_lopsided_drop_rated_correctly():
    # 200cp drop from +800 to +600 — should NOT be a blunder
    r = _mk(best_cp=800, played_cp=600)
    assert r in ("excellent", "good")

def test_balanced_200cp_drop_is_mistake_or_worse():
    # 200cp drop from 0 to -200 — should be Mistake or Blunder
    r = _mk(best_cp=0, played_cp=-200)
    assert r in ("mistake", "blunder")


# ── classify — Mate scenarios ─────────────────────────────────────────────────

def test_walked_into_mate():
    result = classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=50, score_before_mate=None,
        score_after_cp=None, score_after_mate=-3,   # opponent has mate-in-3
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert result == "blunder"

def test_missed_forced_mate_still_winning():
    # Had mate-in-3, played a non-mating move but still clearly winning (+400cp).
    # *Changed by CLS-V3 rulings 4 and 7 (2026-11-11):* this asserted `miss` from the
    # numbers alone. A missed mate in ≤ 4 is a miss when the board shows it — the
    # decided position's stored line mates by force (`labelling.missed_win`); the
    # classifier is told so by `missed_win`. Without it the move is labelled by cost.
    kw = dict(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=3,   # had mate
        score_after_cp=400, score_after_mate=None,    # still winning
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert classify(**kw, missed_win=True) == "miss"
    assert classify(**kw) == "mistake"

def test_missed_forced_mate_collapsed_to_losing():
    # Had mate-in-3, played something that loses — catastrophic WPL → Blunder
    result = classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=3,
        score_after_cp=-600, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert result == "blunder"

def test_mate_slower_still_best():
    # Had mate-in-2, played mate-in-5 — still a "best" (both are wins)
    result = classify(
        played_uci="a1a2", best_uci="a1a2",   # same move → Best
        score_before_cp=None, score_before_mate=2,
        score_after_cp=None, score_after_mate=5,   # still mate (opponent POV)
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert result == "best"


# ── F1: walking into mate is only a blunder when the mate was avoidable ──────
#
# The rule used to fire on score_after_mate < 0 alone, before any check that the
# move was inferior. On the real database that labelled 4 382 plies 'blunder',
# of which only 1 513 had actually walked into an avoidable mate; the other
# 2 869 were the engine's own top move, or were played from a position already
# lost to a forced mate, or both. See review/baselines/pre-F1.json.


def _mate_case(**over):
    """A move that ends with the opponent holding mate-in-3."""
    args = dict(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=50, score_before_mate=None,
        score_after_cp=None, score_after_mate=-3,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    args.update(over)
    return classify(**args)


def test_every_legal_move_loses_to_mate_is_not_a_blunder():
    """The engine's own best line was already a forced loss, so there was no
    move that avoided mate. Blaming this one is blaming the position."""
    assert _mate_case(score_before_cp=None, score_before_mate=-4) != "blunder"


def test_only_legal_move_into_mate_is_not_a_blunder():
    """Forced recapture into mate. There was literally nothing else to play."""
    assert _mate_case(only_legal_move=True) == "best"


def test_engine_top_move_into_mate_is_not_a_blunder():
    """played == best. The before/after searches disagreed at finite depth; the
    player did exactly what the engine asked."""
    assert _mate_case(played_uci="a1a2", best_uci="a1a2") != "blunder"


def test_already_lost_and_the_move_shortens_the_mate():
    """Mate-in-8 against, played into mate-in-1. Faster, but lost either way."""
    assert _mate_case(
        score_before_cp=None, score_before_mate=-8, score_after_mate=-1,
    ) != "blunder"


def test_already_lost_and_the_move_lengthens_the_mate():
    """Mate-in-1 against, played into mate-in-8 — the best practical try, and
    certainly not a blunder."""
    assert _mate_case(
        score_before_cp=None, score_before_mate=-1, score_after_mate=-8,
    ) != "blunder"


def test_already_at_the_losing_floor_in_cp_is_not_a_blunder():
    """F16. The gate used to look for an *announced* mate, so a player sitting
    at −1200 cp was charged a blunder when the mate was finally named, while one
    who stayed at −912 was 'excellent'. Both have a WPL of exactly zero: F2
    clamps at ±1000, so −1200 and mate-against are the same position, and the
    gate has to ask that on the clamped scale. 406 stored plies, all one way."""
    assert win_prob(-1200, None) == win_prob(-WP_CP_CLAMP, None)
    assert _mate_case(score_before_cp=-1200) != "blunder"


def test_the_losing_floor_gate_does_not_swallow_a_merely_bad_position():
    """−400 is well above the clamp, so it measures a real loss and handing over
    mate from there is still a blunder. The fix is a floor, not an amnesty for
    anyone who was worse.

    *Changed by owner ruling 3 (2026-11-11, CLS-V3-3).* This used −900 and asserted
    `blunder`; −900 is below 0.05 win probability, and the move costs 0.011, so under
    the ruling the mate was already priced and the ladder names it — see
    `test_ruling3_*` below. The guard keeps its point at a position that is bad but
    not already priced."""
    assert _mate_case(score_before_cp=-400) == "blunder"


def test_ruling3_a_mate_from_below_005_is_not_a_blunder_by_f1():
    """CLS-V3-3: −900 (win probability 0.035) into a forced mate costs 0.011."""
    assert win_prob(-900, None) < 0.05
    assert _mate_case(score_before_cp=-900) == "excellent"


def test_ruling3_a_mate_costing_005_or_less_is_not_a_blunder_by_f1():
    """CLS-V3-3: before at 0.06–0.07 win probability (above 0.05), the mate costs
    under WPL_GOOD — the ladder names it `good`, not `blunder`."""
    cp = -720
    assert 0.05 <= win_prob(cp, None) and wpl(cp, None, None, -3) <= 0.05
    assert _mate_case(score_before_cp=cp) == "good"


def test_ruling3_a_mate_costing_more_than_005_is_still_a_blunder():
    cp = -600
    assert wpl(cp, None, None, -3) > 0.05
    assert _mate_case(score_before_cp=cp) == "blunder"


def test_r3_allowing_mate_in_one_from_a_lost_position_is_a_blunder():
    """CLS-V3-R3: −900 (below 0.05) into mate in one costs 0.011, which ruling 3 alone
    excused; mate in one is a blunder unless a forced mate already existed. The real case
    (a stored ply; its platform id is in the private repository): 12.a5 at −7.22 allowing
    12…Qd1#, `good` under ruling 3."""
    assert win_prob(-900, None) < 0.05 and wpl(-900, None, None, -1) <= 0.05
    assert _mate_case(score_before_cp=-900, score_after_mate=-1) == "blunder"
    assert _mate_case(score_before_cp=-722, score_after_mate=-1) == "blunder"


def test_r3_mate_in_three_made_mate_in_one_is_not_a_blunder():
    """CLS-V3-R3, the owner's example: "if it's m3 and you make it m1, not necessarily a
    blunder" — the forced mate already existed, so the ladder names the move."""
    assert _mate_case(score_before_cp=None, score_before_mate=-3,
                      score_after_mate=-1) != "blunder"


def test_r3_leaves_ruling_3_for_longer_mates():
    """Mate in two from −900 is still priced by ruling 3."""
    assert _mate_case(score_before_cp=-900, score_after_mate=-2) == "excellent"


def test_avoidable_mate_is_still_a_blunder():
    """The regression guard. Position was fine, a better move existed, and the
    player handed over a forced mate."""
    assert _mate_case() == "blunder"


def test_winning_position_thrown_into_mate_is_still_a_blunder():
    assert _mate_case(score_before_cp=600) == "blunder"


def test_mate_rule_does_not_fire_without_a_mate_after():
    """Sanity: a negative *before* mate must not by itself suppress anything."""
    assert _mate_case(
        score_before_cp=None, score_before_mate=-4,
        score_after_cp=-50, score_after_mate=None,
    ) != "blunder"


# ── classify — Miss vs Blunder distinction ────────────────────────────────────

def test_miss_requires_prior_advantage():
    # Was NOT winning before move (balanced position), so large drop → Blunder not Miss
    result = classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=50, score_before_mate=None,   # balanced, not winning
        score_after_cp=-400, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert result == "blunder"

def test_miss_from_large_advantage():
    # Was winning (+400), dropped to barely winning (+50).
    # *Changed by CLS-V3 ruling 5 (2026-11-11):* this asserted `miss`. Drift is labelled
    # by cost — owner: "completely winning to level is a blunder; a miss should be a
    # tactic or a critical move that was missed". With a missed tactic it is a miss.
    kw = dict(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=400, score_before_mate=None,
        score_after_cp=50, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert classify(**kw) == "blunder"
    assert classify(**kw, missed_win=True) == "miss"


# ── classify — brilliant (CLS-V3 ruling 9) ────────────────────────────────────
#
# *Changed by ruling 9 (2026-11-11).* test_brilliant_detector_called and
# test_brilliant_detector_can_return_brilliant pinned the version-2 `brilliant_detector`
# callback (a live engine search in analysis.py, consulted after `best`). The rule is now
# BRILLIANT.md B1–B5 decided from stored data by `labelling.brilliant` and passed as a
# flag, ahead of `book`; the case set is in tests/test_brilliant.py.

def test_the_brilliant_flag_makes_brilliant():
    assert classify(
        played_uci="e2e4", best_uci="e2e4",
        score_before_cp=20, score_before_mate=None,
        score_after_cp=20, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, brilliant=True,
    ) == "brilliant"


def test_brilliant_precedes_book():
    # Ruling 9: "even if it's a book move it's still brilliant".
    kw = dict(played_uci="e2e4", best_uci="e2e4", score_before_cp=20,
              score_before_mate=None, score_after_cp=20, score_after_mate=None,
              second_best_uci=None, second_best_cp=None, second_best_mate=None, is_book=True)
    assert classify(**kw) == "book"
    assert classify(**kw, brilliant=True) == "brilliant"


# ── F4a: the book label is gated on WPL, but only when the ply was scored ────
#
# Book membership measures how common a move is, not whether it is sound. The
# sampled worst case (review/baselines/f4-book-probe.json) is the Scholar's Mate
# blunder, which the app labelled 'book' while it allowed mate in one.
#
# The NULL-score carve-out is what keeps this safe on history: every book ply
# analysed before F4a was stored with no evals, and win_prob(None, None) is 0.5,
# so gating them would judge ~19 797 rows against a fabricated equal position.

# r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3
SCHOLARS_MATE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3"


def _scholars(**over):
    """3...Nf6??, which allows 4.Qxf7#. A book move by popularity."""
    args = dict(
        played_uci="g8f6", best_uci="g7g6",
        score_before_cp=44, score_before_mate=None,
        score_after_cp=None, score_after_mate=-1,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=True,
    )
    args.update(over)
    return classify(**args)


def test_a_scored_book_move_that_allows_mate_is_a_blunder():
    assert _scholars() == "blunder"


def test_the_same_position_with_no_evals_is_still_book():
    """The historical-row guarantee. Identical ply, scores absent — the label
    must not move, because there is nothing to judge it against."""
    assert _scholars(
        played_uci="g8f6", best_uci="g8f6",
        score_before_cp=None, score_before_mate=None,
        score_after_cp=None, score_after_mate=None,
    ) == "book"


def test_a_half_scored_book_move_is_still_book():
    """One side missing is not enough to compute a loss. Falling through here
    would score the ply against win_prob(None, None) == 0.5."""
    assert _scholars(score_after_cp=None, score_after_mate=None) == "book"
    assert _scholars(score_before_cp=None, score_before_mate=None) == "book"


def test_a_sound_book_move_keeps_the_label():
    assert _scholars(
        played_uci="e7e5", best_uci="e7e5",
        score_before_cp=20, score_before_mate=None,
        score_after_cp=15, score_after_mate=None,
    ) == "book"


def test_the_book_gate_sits_at_inaccuracy_not_good():
    """Decision 3: gated at WPL_INACCURACY. A move that is merely 'good' or
    'inaccuracy'-level stays book; only worse than that loses the label."""
    before = 0
    # WPL just inside the gate → still book
    inside = _scholars(
        played_uci="a2a3", best_uci="b1c3",
        score_before_cp=before, score_before_mate=None,
        score_after_cp=-55, score_after_mate=None,   # wpl ≈ 0.0503
    )
    assert inside == "book"
    # and comfortably past it → judged normally
    outside = _scholars(
        played_uci="a2a3", best_uci="b1c3",
        score_before_cp=before, score_before_mate=None,
        score_after_cp=-300, score_after_mate=None,  # wpl ≈ 0.25
    )
    assert outside != "book"


def test_an_unscored_book_move_stays_book_even_when_played_is_not_best():
    """Historical rows store best_uci == played_uci, but a re-analysis (F4b)
    could fill scores and disagree. Until it does, absence wins."""
    assert _scholars(
        played_uci="g8f6", best_uci="g7g6",
        score_before_cp=None, score_before_mate=None,
        score_after_cp=None, score_after_mate=None,
    ) == "book"


# ── F2: mate is the ceiling of the win-prob scale, not a saturated 1.0 ────────
#
# Mate used to map to exactly 1.0 and cp was unbounded. Two bugs fell out: any
# move after a forced mate could only lose win probability, and +2000 cp scored
# *above* mate so converting the advantage into mate registered as an error.
# Clamping both to WP_CP_CLAMP makes mate the top of the scale and drops mate
# distance from the measurement entirely.

def _f2(before, after, *, played="a1a2", best="b1b2"):
    """Classify with (cp, mate) tuples for before/after, mover's POV."""
    return classify(
        played_uci=played, best_uci=best,
        score_before_cp=before[0], score_before_mate=before[1],
        score_after_cp=after[0], score_after_mate=after[1],
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )


def test_f2_slower_mate_is_not_a_mistake():
    # mate-in-3 -> mate-in-9 for the same side. A forced win either way.
    assert wpl(None, 3, None, 9) == 0.0
    assert _f2((None, 3), (None, 9)) in ("excellent", "best")


def test_f2_throwing_away_a_forced_mate_is_a_clear_error():
    # mate-in-3 -> +200 cp. Still better for the mover, but a genuine loss of a
    # forced win, so it must not be waved through as "good".
    assert wpl(None, 3, 200, None) > WPL_MISTAKE
    assert _f2((None, 3), (200, None)) in ("miss", "mistake", "blunder")


def test_f2_converting_a_big_advantage_into_mate_costs_nothing():
    # +900 cp -> mate. Without the clamp this was a small loss; it must be zero,
    # and it must not be inflated into a "great" move either.
    assert wpl(900, None, None, 1) == 0.0
    assert _f2((900, None), (None, 1)) in ("excellent", "best")


def test_f2_mate_for_you_to_mate_against_you_is_a_blunder():
    # The full span of the scale, and the one case where F1's gating also fires.
    assert wpl(None, 3, None, -1) > 0.9
    assert _f2((None, 3), (None, -1)) == "blunder"


def test_f2_the_mate_rule_and_the_miss_rule_agree_rather_than_stack():
    # Both F1's walked-into-mate rule and the was-winning collapse branch match
    # this position. They return the same label, so the move is named once.
    assert _f2((None, 3), (None, -1)) == "blunder"
    # Take F1's rule out of play by making the played move the engine's own choice.
    # *Changed by CLS-V3 (2026-11-11):* version 2's was-winning collapse branch called
    # this a blunder; rulings 4–6 retire that branch and the ruled precedence labels the
    # engine's own move `best` (or `great`), never an error — a loss on it is search
    # disagreement (CLASSIFICATION.md F, row 7).
    assert _f2((None, 3), (None, -1), played="a1a2", best="a1a2") == "best"


# ── F2b (retired by CLS-V3, 2026-11-11) ───────────────────────────────────────
#
# *Removed by rulings 4–6.* Four tests pinned `_miss_threshold` — MISS_MIN_WPL lowered
# for a clamped before-score and derived from WP_CP_CLAMP
# (test_miss_threshold_is_lowered_for_a_forced_mate, …_for_a_clamped_cp_score,
# …_is_untouched_below_the_clamp, test_miss_threshold_offset_is_derived_from_the_clamp).
# The magnitude miss they calibrated no longer exists, and neither does the threshold.


def test_missing_mate_in_one_for_a_still_winning_position_is_a_miss():
    # Real stored ply (id 2383): 21...Qe2# was on the board, 21...Qxb3 played,
    # leaving +423 cp. WPL 0.1495 — under the old flat threshold this read as an
    # ordinary mistake.
    # *Changed by CLS-V3 (2026-11-11):* this reached `miss` through the version-2
    # magnitude rule (WPL 0.1495 over the clamped threshold). Under rulings 4–6 it is a
    # miss because mate in one was forfeited (the rule fact the test describes), with the
    # mover at +423 (≥ 0.50); without that flag, by cost, it is a mistake.
    kw = dict(
        played_uci="b2b3", best_uci="e5e2",
        score_before_cp=None, score_before_mate=1,
        score_after_cp=423, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert classify(**kw, forfeited_mate_in_one=True) == "miss"
    assert classify(**kw) == "mistake"


def test_an_unclamped_winning_position_keeps_the_full_threshold():
    # +900 -> +463 is WPL 0.129: inside the corrected band but not clamped, so
    # it must stay on the ladder rather than become a Miss.
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=900, score_before_mate=None,
        score_after_cp=463, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    ) == "mistake"


# ── F19: `great` is about the move, not just the position ─────────────────────
#
# The gap test alone asks only whether the *position* offered one good option.
# These cases all satisfy it and none of them deserve praise.


def _great_case(**over):
    """Best move in a position whose second-best option was far worse.

    *CLS-V3 ruling 8, then T7:* passes `great_eligible=True` (ruling 8: `great_hard=True`),
    so the tests below keep testing the gap and `_can_be_great`; before ruling 8, the gap
    alone made `great`."""
    args = dict(
        played_uci="a1a2", best_uci="a1a2",
        score_before_cp=50, score_before_mate=None,
        score_after_cp=50, score_after_mate=None,
        second_best_uci="b1b2", second_best_cp=-900, second_best_mate=None,
        is_book=False, great_eligible=True,
    )
    args.update(over)
    return classify(**args)


def test_wide_gap_and_a_good_move_is_still_great():
    assert _great_case() == "great"


def test_great_requires_the_move_itself_to_be_good():
    # Real stored ply (id 47016): -402 cp, played the engine's own top move,
    # and it walked into mate in 8. WPL 0.1608. The gap test called it Great.
    assert _great_case(
        score_before_cp=-402, score_after_cp=None, score_after_mate=-8,
    ) == "best"


def test_great_not_awarded_from_an_already_lost_position():
    # Past the clamp every option scores the same floor, so a "gap" there is an
    # artefact of one line being searched further, not a choice got right.
    assert _great_case(
        score_before_cp=None, score_before_mate=-2,
        score_after_cp=None, score_after_mate=-2,
    ) == "best"


def test_great_downgrades_to_best_not_to_an_error():
    # The move was still the engine's first choice. Losing the Great label must
    # not push it onto the error ladder. (-402 -> -700 is WPL 0.115.)
    assert _great_case(score_before_cp=-402, score_after_cp=-700) == "best"


def test_great_survives_a_loss_inside_the_good_band():
    # The bar is WPL_GOOD, not zero: -402 -> -500 is 0.0485 and still Great.
    assert _great_case(score_before_cp=-402, score_after_cp=-500) == "great"


# ── F20: forfeiting mate in one ───────────────────────────────────────────────


def _forfeit_case(**over):
    """Mate in one was available; the player took a still-winning move instead."""
    args = dict(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=1,
        score_after_cp=794, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, forfeited_mate_in_one=True,
    )
    args.update(over)
    return classify(**args)


def test_forfeiting_mate_in_one_while_still_winning_is_a_miss():
    # Real stored ply (id 37552): Qh1# was on the board, a6 played, +794 cp
    # left. WPL 0.0264 — two rungs below the miss threshold, so on the eval
    # alone this read `good`. The rule says otherwise.
    assert _forfeit_case() == "miss"


def test_forfeiting_mate_in_one_and_collapsing_stays_a_blunder():
    # Already priced by WPL. `miss` would be an upgrade.
    assert _forfeit_case(score_after_cp=None, score_after_mate=-1) == "blunder"


def test_delivering_the_mate_is_not_a_forfeit():
    # The caller decides this by the rules, so an unscored ply cannot be
    # mistaken for a forfeit (real stored ply id 4023: Rf1# on a depth-0 run).
    assert _forfeit_case(
        forfeited_mate_in_one=False, score_after_cp=None, score_after_mate=0,
    ) == "best"


def test_forfeit_gate_needs_a_scored_after_position():
    # No eval means no "still winning" to test; `win_prob(None, None)` is 0.5,
    # which is a fabricated position rather than a measurement. The flag must
    # therefore change nothing at all on an unscored ply.
    unscored = dict(score_after_cp=None, score_after_mate=None)
    assert (_forfeit_case(**unscored)
            == _forfeit_case(forfeited_mate_in_one=False, **unscored))


def test_delaying_mate_is_not_a_forfeit():
    # Real stored ply (id 1363): Qf2# was available, Qd3+ played, still mate in
    # one afterwards. Under the flat ceiling a longer mate is not a worse
    # position, so nothing was actually given up.
    assert _forfeit_case(score_after_cp=None, score_after_mate=1) != "miss"


def test_a_longer_forced_mate_is_still_not_a_forfeit():
    # Same reasoning, stated separately because it is the load-bearing half:
    # the gate keys on "a forced mate remains", never on the distance to it.
    assert _forfeit_case(score_after_cp=None, score_after_mate=5) != "miss"


def test_mate_in_one_rule_does_not_extend_to_mate_in_two():
    # Mate in two cannot be read off the position, only searched for. The flag
    # is therefore never set, and the eval ladder decides alone.
    assert _forfeit_case(
        forfeited_mate_in_one=False, score_before_mate=2,
    ) == "good"


# ── An absent best move is not an agreement ──────────────────────────────────


def _no_best(**over):
    """The engine named no best move: `best_uci` is None, not the played move."""
    args = dict(
        played_uci="a1a2", best_uci=None,
        score_before_cp=20, score_before_mate=None,
        score_after_cp=10, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    args.update(over)
    return classify(**args)


def test_absent_best_move_does_not_award_best():
    # Before this, both analysis paths passed the played move as `best_uci` when
    # the engine had not named one, so `is_best` was true by construction.
    assert _no_best() != "best"


def test_absent_best_move_does_not_suppress_blunder():
    # The other reader of `best_uci` is the walked-into-mate gate, which spares
    # the player when they played the engine's own choice. An unnamed best move
    # is not that, and the substitution was silently granting the exemption.
    assert _no_best(
        score_before_cp=200, score_before_mate=None,
        score_after_cp=None, score_after_mate=-2,
    ) == "blunder"


def test_absent_best_move_cannot_be_great():
    # `great` needs the played move to be the best one. With none named there is
    # no such claim to make, however wide the gap to second best.
    assert _no_best(
        second_best_uci="b1b2", second_best_cp=-900, second_best_mate=None,
    ) != "great"
