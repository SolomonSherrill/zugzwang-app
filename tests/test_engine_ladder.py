"""The level → UCI_Elo ladder (F5).

Level numbers are only meaningful if each one plays stronger than the one below
it. The shipped ladder failed that: it was piecewise, repeated Elo 1800 at two
levels, and inverted in the middle band. These tests pin the properties that
make the ordering true, so a future tweak to the endpoints cannot quietly
reintroduce a flat or backwards step.

They assert ordering, not human equivalence — see skill_to_elo's docstring.
"""

import pytest

from zugzwang.config import (
    ENGINE_ELO_MAX,
    ENGINE_ELO_MIN,
    SKILL_MAX,
    SKILL_MIN,
    skill_to_elo,
)


def test_only_the_top_level_is_unlimited():
    assert skill_to_elo(SKILL_MAX) is None
    for skill in range(SKILL_MIN, SKILL_MAX):
        assert skill_to_elo(skill) is not None


def test_ladder_is_strictly_increasing():
    elos = [skill_to_elo(s) for s in range(SKILL_MIN, SKILL_MAX)]
    for lower, higher in zip(elos, elos[1:]):
        assert higher > lower


def test_no_two_levels_share_an_elo():
    elos = [skill_to_elo(s) for s in range(SKILL_MIN, SKILL_MAX)]
    assert len(set(elos)) == len(elos)


def test_ladder_spans_the_engines_whole_range():
    # Outside these bounds Stockfish clamps, which would flatten the ends.
    assert skill_to_elo(SKILL_MIN) == ENGINE_ELO_MIN
    assert skill_to_elo(SKILL_MAX - 1) == ENGINE_ELO_MAX


@pytest.mark.parametrize("skill", range(SKILL_MIN, SKILL_MAX))
def test_every_level_is_within_engine_bounds(skill):
    assert ENGINE_ELO_MIN <= skill_to_elo(skill) <= ENGINE_ELO_MAX
