"""Accuracy: the per-move curve and the whole-game aggregation (F3 / I7 / R2).

Before F3 there were three copies of the per-move curve on two different
win-probability scales, and the game figure was a flat arithmetic mean. There
is now one of each, in core.classification, and these tests exist to keep it
that way.
"""

import math

import pytest

from zugzwang.core.classification import (
    PlyScore,
    WP_CP_CLAMP,
    game_accuracy,
    move_accuracy_pct,
    win_prob,
    wpl,
)


# ── Per-move curve ───────────────────────────────────────────────────────────

def test_perfect_move_is_exactly_100():
    assert move_accuracy_pct(0.0) == 100.0


def test_improving_the_position_is_100():
    # wpl floors a negative loss at zero, which is where Lichess's
    # `if after >= before then 100` short-circuit lands.
    assert move_accuracy_pct(wpl(0, None, 300, None)) == 100.0


def test_total_collapse_clamps_to_zero():
    assert move_accuracy_pct(1.0) == 0.0


def test_monotonic_decreasing_in_loss():
    accs = [move_accuracy_pct(x) for x in (0.0, 0.05, 0.1, 0.2, 0.4)]
    assert accs == sorted(accs, reverse=True)


def test_uncertainty_bonus_is_applied():
    """Lichess adds a flat point for imperfect analysis; omitting it scored
    every non-perfect move a point low."""
    loss = 0.10
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * loss * 100.0) \
        - 3.166924740191411
    assert move_accuracy_pct(loss) == pytest.approx(raw + 1.0, abs=1e-9)


def test_full_precision_constants():
    """Guards against the truncation that let the three old copies drift."""
    assert move_accuracy_pct(0.10) == pytest.approx(64.57982845372067, abs=1e-12)


# ── Win-probability scale (R2) ───────────────────────────────────────────────

def test_accuracy_runs_on_the_clamped_scale():
    """Lichess's accuracy pipeline feeds `forceAsCp` through a ±1000 ceiling,
    which is the same clamped scale F2 gave win_prob. A mate must therefore not
    read as 100%, or converting a big edge into mate scores as a loss."""
    assert win_prob(None, 3) < 1.0
    assert win_prob(None, 3) == win_prob(WP_CP_CLAMP, None)


def test_finding_mate_from_a_won_position_costs_nothing():
    assert move_accuracy_pct(wpl(2000, None, None, 1)) == 100.0


def test_delivered_mate_is_a_win_for_the_mover():
    """mate == 0 is our storage for 'the mover just mated'. scalachess's
    Mate.signum would read it as a loss; we deliberately do not."""
    assert win_prob(None, 0) == win_prob(None, 5)


# ── Whole-game aggregation ───────────────────────────────────────────────────

def _flat_game(n: int, cp: int = 20) -> list[PlyScore]:
    """n plies that neither side ever mishandles."""
    return [
        PlyScore("white" if i % 2 == 0 else "black", cp, None, cp, None)
        for i in range(n)
    ]


def test_flawless_game_is_100():
    acc = game_accuracy(_flat_game(40))
    assert acc["white"] == pytest.approx(100.0)
    assert acc["black"] == pytest.approx(100.0)


def test_empty_game_has_no_accuracy():
    assert game_accuracy([]) == {"white": None, "black": None}


def test_colour_with_no_scored_plies_is_none():
    plies = [PlyScore("white", 20, None, 20, None),
             PlyScore("black", None, None, None, None)]
    assert game_accuracy(plies)["black"] is None


def test_one_blunder_only_costs_the_player_who_made_it():
    plies = _flat_game(40)
    plies[10] = PlyScore("white", 600, None, -600, None)
    acc = game_accuracy(plies)
    assert acc["white"] < 100.0
    assert acc["black"] == pytest.approx(100.0)


def test_harmonic_half_punishes_one_catastrophe_over_many_small_errors():
    """The mean of a weighted and a harmonic mean is the whole point of the
    Lichess aggregation: a flat average would rate these two games the same."""
    one_disaster = _flat_game(40)
    one_disaster[10] = PlyScore("white", 600, None, -600, None)

    many_small = _flat_game(40)
    for i in (10, 12, 14, 16, 18, 20, 22, 24):
        many_small[i] = PlyScore("white", 120, None, 40, None)

    assert game_accuracy(one_disaster)["white"] < game_accuracy(many_small)["white"]


def test_zero_accuracy_move_does_not_divide_by_zero():
    """The harmonic mean floors each term at 1.0, as Lichess's does."""
    plies = _flat_game(20)
    plies[4] = PlyScore("white", 1000, None, -1000, None)
    assert game_accuracy(plies)["white"] is not None


def _game_from_white_pov(values: list[int], error_at: int) -> list[PlyScore]:
    """Plies that hold a given White-perspective eval, with one White error.

    Every ply but `error_at` is loss-free, so the only thing distinguishing two
    games built this way is where the error sits relative to the volatility.
    """
    plies = []
    for i, v in enumerate(values):
        mover = "white" if i % 2 == 0 else "black"
        sign = 1 if mover == "white" else -1
        if i == error_at:
            plies.append(PlyScore(mover, sign * 100, None, sign * -50, None))
        else:
            plies.append(PlyScore(mover, sign * v, None, sign * v, None))
    return plies


def test_volatility_weighting_costs_more_in_a_sharp_position():
    """The same error twice over, once amid swinging evals and once in a dead
    position. Both games hold the identical multiset of per-move accuracies, so
    a flat mean — or the harmonic half alone — cannot tell them apart."""
    swinging = [400 if i % 2 == 0 else -400 for i in range(30)]
    values = swinging + [20] * 30

    in_the_storm = game_accuracy(_game_from_white_pov(values, error_at=10))
    in_the_calm = game_accuracy(_game_from_white_pov(values, error_at=40))

    assert in_the_storm["white"] < in_the_calm["white"]


def test_unscored_ply_drops_its_window_rather_than_reading_as_equal():
    """win_prob maps (None, None) to 0.5; counting that would invent a
    dead-equal position and read the surrounding plies as huge swings."""
    plies = _flat_game(40)
    plies[20] = PlyScore("white", None, None, None, None)
    acc = game_accuracy(plies)
    assert acc["white"] == pytest.approx(100.0)
    assert acc["black"] == pytest.approx(100.0)


def test_short_game_does_not_crash_on_window_padding():
    for n in (1, 2, 3, 5):
        acc = game_accuracy(_flat_game(n))
        assert acc["white"] is not None


# ── Conformance with Lichess (lila modules/analyse/src/test) ─────────────────
#
# Our option-B divergence is about *which* numbers feed the formula, not the
# formula itself: given a true chain of position evals — after(i) == before(i+1)
# — option B reduces exactly to Lichess's algorithm. So Lichess's own fixtures
# are a valid check, and the one that would catch a mistake in the windowing,
# the weighting or the harmonic blend. Tolerances are Lichess's own.

def _from_chain(cps: list[int], start: str = "white") -> dict[str, float | None]:
    """Build plies from a White-perspective eval chain, Lichess-style.

    `cps[i]` is the eval after ply i; Lichess prepends Cp.initial = 15 as the
    evaluation of the starting position.
    """
    chain = [15] + list(cps)
    other = "black" if start == "white" else "white"
    plies = []
    for i in range(len(cps)):
        mover = start if i % 2 == 0 else other
        sign = 1 if mover == "white" else -1
        plies.append(
            PlyScore(mover, sign * chain[i], None, sign * chain[i + 1], None)
        )
    return plies


@pytest.mark.parametrize("name,cps,exp_white,exp_black,tol", [
    ("two good moves",             [15, 15],             100, 100, 1),
    ("white blunders first move",  [-900, -900],          10, 100, 5),
    ("black blunders first move",  [15, 900],            100,  10, 5),
    ("both blunder first move",    [-900, 0],             10,  10, 5),
    ("20 perfect moves",           [15] * 20,            100, 100, 1),
    ("20 perfect + white blunder", [15] * 20 + [-900],    50, 100, 5),
    ("21 perfect + black blunder", [15] * 21 + [900],    100,  50, 5),
    ("5 average (65 cpl) each",    [-50, 15] * 5,         76,  76, 8),
    ("50 average (65 cpl) each",   [-50, 15] * 50,        76,  76, 8),
    ("50 mediocre (150 cpl) each", [-135, 15] * 50,       54,  54, 8),
    ("50 terrible (500 cpl) each", [-435, 15] * 50,       20,  20, 8),
])
def test_matches_lichess_fixtures(name, cps, exp_white, exp_black, tol):
    acc = game_accuracy(_from_chain(cps))
    assert acc["white"] == pytest.approx(exp_white, abs=tol)
    assert acc["black"] == pytest.approx(exp_black, abs=tol)


def test_black_moving_first_is_scored_as_black():
    """Lichess's fixtures cover this because a phase slice can begin on either
    colour; our volatility chain has to stay White-perspective regardless."""
    acc = game_accuracy(_from_chain([15, 15], start="black"))
    assert acc["black"] == pytest.approx(100.0, abs=1.0)


def test_accuracy_never_leaves_the_percentage_range():
    plies = [
        PlyScore("white" if i % 2 == 0 else "black",
                 900 - 100 * i, None, -900 + 50 * i, None)
        for i in range(30)
    ]
    for value in game_accuracy(plies).values():
        assert 0.0 <= value <= 100.0
