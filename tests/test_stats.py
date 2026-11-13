"""The statistics the Insights phase verdict decides with (core/stats.py)."""

import pytest

from zugzwang.core.stats import benjamini_hochberg, normal_two_sided_p


# ── p-values ─────────────────────────────────────────────────────────────────

def test_normal_p_matches_the_familiar_quantiles():
    assert normal_two_sided_p(1.959964) == pytest.approx(0.05, rel=1e-4)
    assert normal_two_sided_p(2.575829) == pytest.approx(0.01, rel=1e-4)
    assert normal_two_sided_p(0.0) == pytest.approx(1.0)


# ── Benjamini-Hochberg ───────────────────────────────────────────────────────

def test_bh_keeps_nothing_when_every_p_is_large():
    assert benjamini_hochberg([0.4, 0.6, 0.9], 0.05) == [False, False, False]


def test_bh_keeps_the_clearly_real_one():
    assert benjamini_hochberg([0.001, 0.4, 0.9], 0.05) == [True, False, False]


def test_bh_is_stricter_than_testing_each_alone():
    # Twenty tests, one at p = 0.04: significant alone, not once corrected.
    pvalues = [0.04] + [0.5] * 19
    assert not any(benjamini_hochberg(pvalues, 0.05))


def test_bh_steps_up_rather_than_stopping_at_the_first_failure():
    # 0.02 fails its own threshold (2/4*0.05 = 0.025 passes, 3/4 -> 0.0375);
    # the largest passing rank is what lets the middle values through.
    pvalues = [0.001, 0.02, 0.03, 0.9]
    assert benjamini_hochberg(pvalues, 0.05) == [True, True, True, False]


def test_bh_on_an_empty_family():
    assert benjamini_hochberg([], 0.05) == []
