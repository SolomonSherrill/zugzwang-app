"""Exact-boundary tests for the move classifier (Phase 2, priority 1).

The existing test_classification.py asserts loose ranges ("in (good, inaccuracy)").
This module pins every WPL threshold at/just-below/just-above, exercises the Miss
preconditions independently, and documents two cross-module inconsistencies found
in the audit (R2: win_prob mate-sign; R4: accuracy constant) as xfail.

cp is fed as a float so we can place win-probability loss exactly on a threshold:
win_prob(cp_for_wp(w)) == w to float precision, so a move from wp_before to
wp_after has loss == wp_before - wp_after exactly.
"""

import math

import pytest

from zugzwang.core.classification import (
    classify,
    win_prob,
    wpl,
    MISS_MIN_WP_AFTER,
    WPL_EXCELLENT,
    WPL_GOOD,
    WPL_INACCURACY,
    WPL_MISTAKE,
    WPL_GREAT_GAP,
    WP_CP_CLAMP,
    _WP_K,
)

# A loss step small enough to sit inside any threshold gap (gaps are >= 0.03)
# yet large enough to survive sigmoid round-trip float error (~1e-15).
DELTA = 1e-3


def cp_for_wp(wp: float) -> float:
    """Inverse of the win-prob sigmoid: centipawns giving win_prob(cp) == wp."""
    return math.log(wp / (1.0 - wp)) / _WP_K


def _ladder(loss: float) -> str:
    """Classify a non-best, non-winning move whose WPL is exactly *loss*.

    before is balanced (wp 0.5, cp 0 — below the 300cp 'winning' line so the Miss
    branch never fires); after is wp 0.5 - loss; played != best.
    """
    return classify(
        played_uci="a1a2",
        best_uci="b1b2",
        score_before_cp=0.0,
        score_before_mate=None,
        score_after_cp=cp_for_wp(0.5 - loss),
        score_after_mate=None,
        second_best_uci=None,
        second_best_cp=None,
        second_best_mate=None,
        is_book=False,
    )


# ── win_prob ──────────────────────────────────────────────────────────────────

# F2 replaced "mate is 1.0" with "mate is the clamp" — see the WP_CP_CLAMP note
# in classification.py. Mate remains the ceiling of the scale; it is simply no
# longer a saturated one, which is what let a real collapse be measured.

def test_win_prob_mate_positive_is_the_clamp():
    assert win_prob(None, 1) == win_prob(WP_CP_CLAMP, None)
    assert win_prob(None, 99) == win_prob(WP_CP_CLAMP, None)


def test_win_prob_mate_negative_is_the_clamp():
    assert win_prob(None, -1) == win_prob(-WP_CP_CLAMP, None)


def test_win_prob_mate_is_the_ceiling():
    # No centipawn score may outrank a forced mate. Before the clamp, +2000 cp
    # scored above mate, so converting the advantage into mate was a small loss.
    assert win_prob(5000, None) <= win_prob(None, 1)
    assert win_prob(-5000, None) >= win_prob(None, -1)


def test_win_prob_cp_none_is_half():
    assert win_prob(None, None) == 0.5


def test_win_prob_cp_zero_is_half():
    assert win_prob(0, None) == 0.5


def test_win_prob_monotonic_in_cp():
    assert win_prob(-50, None) < win_prob(0, None) < win_prob(50, None)


def test_win_prob_mate_zero_is_a_win_for_mover():
    # mate == 0 means the mover has just delivered mate, so it is their win.
    # `mate > 0` alone scored it as a loss; F2's `mate >= 0` fixes it. Was xfail
    # while the two win-prob functions disagreed on this boundary.
    assert win_prob(None, 0) == win_prob(None, 1)


# ── wpl ───────────────────────────────────────────────────────────────────────

def test_wpl_zero_when_no_drop():
    assert wpl(0, None, 0, None) == 0.0


def test_wpl_clamped_nonnegative_when_position_improves():
    assert wpl(-200, None, 200, None) == 0.0


def test_wpl_exact_value():
    loss = wpl(0.0, None, cp_for_wp(0.35), None)
    assert loss == pytest.approx(0.15, abs=1e-9)


# ── ladder boundaries: excellent / good / inaccuracy / mistake / blunder ──────

# The cut is `loss <= threshold` (inclusive lower side). Thresholds are spaced
# >= 0.03 apart, so DELTA=1e-3 below/above unambiguously straddles each cut.
# (Exact-at-threshold isn't asserted: the sigmoid round-trip in cp_for_wp carries
# ~1e-15 float error that can tip an exact-boundary value either way, and stored
# cp is integer anyway — the below/above pair pins the cut location.)

def test_excellent_below_threshold():
    assert _ladder(WPL_EXCELLENT - DELTA) == "excellent"


def test_just_above_excellent_is_good():
    assert _ladder(WPL_EXCELLENT + DELTA) == "good"


def test_good_below_threshold():
    assert _ladder(WPL_GOOD - DELTA) == "good"


def test_just_above_good_is_inaccuracy():
    assert _ladder(WPL_GOOD + DELTA) == "inaccuracy"


def test_inaccuracy_below_threshold():
    assert _ladder(WPL_INACCURACY - DELTA) == "inaccuracy"


def test_just_above_inaccuracy_is_mistake():
    assert _ladder(WPL_INACCURACY + DELTA) == "mistake"


def test_mistake_below_threshold():
    assert _ladder(WPL_MISTAKE - DELTA) == "mistake"


def test_just_above_mistake_is_blunder():
    assert _ladder(WPL_MISTAKE + DELTA) == "blunder"


# ── Great gap (best move, weak second-best) ──────────────────────────────────

def _great(gap: float) -> str:
    """best == played; second-best is *gap* win-prob worse than the position."""
    return classify(
        played_uci="g1f3",
        best_uci="g1f3",
        score_before_cp=0.0,            # wp_best 0.5, not winning
        score_before_mate=None,
        score_after_cp=0.0,             # played the best move, no loss
        score_after_mate=None,
        second_best_uci="b1c3",
        second_best_cp=cp_for_wp(0.5 - gap),
        second_best_mate=None,
        is_book=False,
        # CLS-V3 ruling 8, then T7: the move is eligible (T7: not an obvious recapture, more
        # than one legal move; ruling 8 passed `great_hard`), so the gap boundary is what
        # these tests pin; before ruling 8, the gap alone made `great`.
        great_eligible=True,
    )


def test_great_above_gap():
    assert _great(WPL_GREAT_GAP + DELTA) == "great"


def test_just_below_gap_is_best_not_great():
    assert _great(WPL_GREAT_GAP - DELTA) == "best"


def test_best_without_second_best_is_best():
    r = classify(
        played_uci="g1f3", best_uci="g1f3",
        score_before_cp=0.0, score_before_mate=None,
        score_after_cp=0.0, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert r == "best"


# ── Miss is an event (CLS-V3 rulings 4–7, 2026-11-11) ─────────────────────────
#
# *Changed by the rulings.* This section used to pin the version-2 magnitude miss:
# `_was_winning` at +300 cp (test_was_winning_cp_boundary, test_was_winning_mate_sign),
# "+300 and a big drop with ≥ 0.40 left is a miss, +299 is a blunder"
# (test_miss_requires_was_winning), the 0.40 floor (test_miss_wp_after_floor_is_040),
# the MISS_MIN_WPL loss bar (test_miss_requires_min_wpl), and "had mate in 2, played
# something fine → miss" (test_miss_from_forced_mate_given_up). Rulings 4–6 replace all of
# it: a miss needs the event (`missed_win`, decided from the board by `labelling`), the
# played move not the engine's, and the mover at least 0.45 afterwards (R1; was 0.50); a drop
# with no event is labelled by cost.

def _miss_case(before_cp, after_wp, *, missed_win=False, played="a1a2", best="b1b2"):
    return classify(
        played_uci=played, best_uci=best,
        score_before_cp=before_cp, score_before_mate=None,
        score_after_cp=cp_for_wp(after_wp), score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, missed_win=missed_win,
    )


def test_drift_without_an_event_is_labelled_by_cost():
    # Ruling 5: +300 to dead level with nothing missed by force — a blunder by cost.
    assert _miss_case(300, 0.50) == "blunder"
    assert _miss_case(300, 0.62) == "mistake"


def test_a_missed_win_is_a_miss_when_the_mover_stays_level():
    assert _miss_case(300, 0.50, missed_win=True) == "miss"


def test_miss_wp_after_floor_is_045():
    # Ruling 6 as refined by R1 (2026-11-11, second round): at least 0.45 afterwards,
    # inclusive; below it the ladder names it. *Changed by R1:* was
    # test_miss_wp_after_floor_is_050 — floor 0.50, 0.50 − δ a blunder, 0.45 a blunder.
    assert MISS_MIN_WP_AFTER == 0.45
    assert _miss_case(600, 0.50, missed_win=True) == "miss"
    assert _miss_case(600, 0.50 - DELTA, missed_win=True) == "miss"
    assert _miss_case(600, 0.45 + DELTA, missed_win=True) == "miss"   # cp_for_wp(0.45) rounds under
    assert _miss_case(600, 0.45 - DELTA, missed_win=True) == "blunder"
    assert _miss_case(600, 0.40, missed_win=True) == "blunder"   # a miss under version 2


def test_a_missed_win_on_the_engines_own_move_is_never_a_miss():
    # Finding 14 (CLASSIFICATION.md A6): `miss` on the engine's first choice.
    assert _miss_case(600, 0.60, missed_win=True, played="b1b2") != "miss"


def test_giving_up_a_mate_in_two_is_not_a_miss_by_itself():
    # Version 2 called this a miss (had mate, played a non-mating move, 0.55 left). Mate
    # in two is not a rule fact; without gate P's event or a decided-position short mate
    # (`missed_win`) the move is labelled by cost.
    r = classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=2,
        score_after_cp=cp_for_wp(0.55), score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    )
    assert r == "blunder"
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=2,
        score_after_cp=cp_for_wp(0.55), score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, missed_win=True,
    ) == "miss"


# ── Always-Blunder: walked into mate ─────────────────────────────────────────

def test_walked_into_mate_is_blunder_even_from_winning():
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=800, score_before_mate=None,
        score_after_cp=None, score_after_mate=-1,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False,
    ) == "blunder"


# ── Precedence: book > only-legal > checkmate-delivered > brilliant > ladder ──
#
# The book gate still runs first, but since F4a it no longer wins unconditionally:
# it wins while the ply is unscored, or while it was scored and played acceptably.
# A scored book ply that walked into mate falls through to the ladder.

def test_an_unscored_book_move_wins_over_everything():
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=None, score_before_mate=None,
        score_after_cp=None, score_after_mate=None,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=True,
    ) == "book"


def test_a_scored_book_move_does_not_win_over_walking_into_mate():
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=800, score_before_mate=None,
        score_after_cp=None, score_after_mate=-1,
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=True,
    ) == "blunder"


def test_only_legal_beats_checkmate_and_ladder():
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=0, score_before_mate=None,
        score_after_cp=cp_for_wp(0.1), score_after_mate=None,  # blunder-sized
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, only_legal_move=True,
    ) == "best"


# *Changed by CLS-V3 ruling 9 (2026-11-11):* test_checkmate_delivered_is_best_over_
# brilliant_hook asserted that delivering mate short-circuits before the version-2
# detector callback was consulted; test_brilliant_hook_overrides_ladder that the callback's
# verdict beat the ladder. The callback is gone: `brilliant` is a flag decided by
# `labelling.brilliant`, which cannot hold for a mating move (B1: the mover had mate
# already), and it still beats the ladder.

def test_brilliant_flag_overrides_ladder():
    assert classify(
        played_uci="a1a2", best_uci="b1b2",
        score_before_cp=0, score_before_mate=None,
        score_after_cp=cp_for_wp(0.1), score_after_mate=None,  # would be blunder
        second_best_uci=None, second_best_cp=None, second_best_mate=None,
        is_book=False, brilliant=True,
    ) == "brilliant"
