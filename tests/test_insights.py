"""Insights aggregation tests (Phase 2, priority 4 — R6).

Covers the per-game accuracy AVG at the DB layer, the source filter (local
games excluded), colour/since filters, the interval gating that decides whether
_shape_summary may name a weakest opening, and the Divider-based phase split.
"""

import pytest

from zugzwang.core.database import Database, InsightsFilter
from zugzwang.core.insights import _shape_openings, _shape_summary

from tests.runs import mark_complete  # noqa: E402


# ── DB-layer opening performance ─────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "ins.db")


def _game(db, *, color="white", result="1-0", opening="Sicilian Defense",
          eco="B20", source="lichess", played_at="2026-01-01T00:00:00+00:00"):
    return db.save_game(
        played_at=played_at,
        player_color=color,
        skill_level=0,
        result=result,
        termination="checkmate",
        move_count=20,
        pgn='[Event "x"]\n\n1. e4 c5 *',
        final_fen="8/8/8/8/8/8/8/8 w - - 0 1",
        opening_eco=eco,
        opening_name=opening,
        source=source,
    )


def _analyze(db, game_id, *, white_acc=None, black_acc=None, depth=14):
    run_id = db.save_analysis_run(game_id=game_id, engine_name="SF", depth=depth)
    return mark_complete(db, run_id, white_accuracy=white_acc, black_accuracy=black_acc)


def test_opening_accuracy_is_per_game_mean(db):
    # 1 game @ 80% + 9 games @ 40%, all same opening, player always White.
    # Per-game AVG = (80 + 9*40) / 10 = 44.0  (NOT ply-weighted).
    _analyze(db, _game(db), white_acc=80.0)
    for _ in range(9):
        _analyze(db, _game(db), white_acc=40.0)

    rows = db.insights_opening_performance()
    assert len(rows) == 1
    eco, name, games, acc, win, draw, loss = rows[0]
    assert games == 10
    assert acc == pytest.approx(44.0)


def test_opening_accuracy_uses_player_color_column(db):
    # Player was Black; only black_accuracy should feed the average.
    _analyze(db, _game(db, color="black", result="0-1"), white_acc=10.0, black_acc=90.0)
    rows = db.insights_opening_performance()
    assert rows[0][3] == pytest.approx(90.0)


def test_local_games_excluded_from_insights(db):
    _analyze(db, _game(db, source="lichess"), white_acc=70.0)
    _analyze(db, _game(db, source="local"), white_acc=10.0)  # must be ignored
    rows = db.insights_opening_performance()
    assert len(rows) == 1
    assert rows[0][2] == 1          # only the lichess game counted
    assert rows[0][3] == pytest.approx(70.0)


def test_win_loss_draw_are_player_pov(db):
    # White wins, Black loses, draw — all same opening, player POV.
    _analyze(db, _game(db, color="white", result="1-0"), white_acc=50.0)
    _analyze(db, _game(db, color="black", result="1-0"), black_acc=50.0)  # player lost
    _analyze(db, _game(db, color="white", result="1/2-1/2"), white_acc=50.0)
    eco, name, games, acc, win, draw, loss = db.insights_opening_performance()[0]
    assert (win, draw, loss) == (1, 1, 1)


def test_color_filter(db):
    _analyze(db, _game(db, color="white"), white_acc=60.0)
    _analyze(db, _game(db, color="black", result="0-1"), black_acc=80.0)
    rows = db.insights_opening_performance(InsightsFilter(color="white"))
    assert len(rows) == 1
    assert rows[0][3] == pytest.approx(60.0)


def test_since_filter(db):
    _analyze(db, _game(db, played_at="2025-01-01T00:00:00+00:00"), white_acc=20.0)
    _analyze(db, _game(db, played_at="2026-06-01T00:00:00+00:00"), white_acc=90.0)
    rows = db.insights_opening_performance(InsightsFilter(since="2026-01-01T00:00:00+00:00"))
    assert rows[0][2] == 1
    assert rows[0][3] == pytest.approx(90.0)


def test_unanalyzed_games_absent_from_opening_performance(db):
    _game(db)  # saved but never analysed -> no analysis_runs row -> excluded
    assert db.insights_opening_performance() == []


def test_overview_counts_analyzed_vs_pending(db):
    _analyze(db, _game(db), white_acc=50.0)
    _game(db)  # unanalysed
    ov = db.insights_overview()
    assert ov == {"total": 2, "analyzed": 1, "pending": 1, "excluded": 0}


# ── Games against Stockfish are excluded, but not silently ───────────────────

def test_overview_discloses_the_games_it_leaves_out(db):
    _analyze(db, _game(db, source="chesscom"), white_acc=70.0)
    _game(db, source="local")
    _game(db, source="local")
    ov = db.insights_overview()
    assert (ov["total"], ov["excluded"]) == (1, 2)


def test_including_local_games_counts_them_and_excludes_nothing(db):
    _analyze(db, _game(db, source="chesscom"), white_acc=70.0)
    _analyze(db, _game(db, source="local"), white_acc=10.0)
    ov = db.insights_overview(InsightsFilter(include_local=True))
    assert (ov["total"], ov["analyzed"], ov["excluded"]) == (2, 2, 0)
    rows = db.insights_opening_performance(InsightsFilter(include_local=True))
    assert rows[0][2] == 2
    assert rows[0][3] == pytest.approx(40.0)


def test_the_excluded_count_obeys_the_other_filters(db):
    # A local game the colour filter rules out is not "excluded by source".
    _game(db, source="local", color="white")
    _game(db, source="local", color="black", result="0-1")
    assert db.insights_overview(InsightsFilter(color="white"))["excluded"] == 1


# ── _shape_openings ──────────────────────────────────────────────────────────

def test_shape_openings_most_played_first_and_drops_none_acc():
    rows = [
        ("C50", "Italian", 5, 40.0, 2, 0, 3),
        ("B20", "Sicilian", 6, 70.0, 4, 1, 1),
        ("D00", "NoAcc", 5, None, 1, 0, 4),   # dropped (acc is None)
    ]
    out = _shape_openings(rows)
    assert [o["name"] for o in out] == ["Sicilian", "Italian"]
    assert out[1]["winRate"] == pytest.approx(40.0)  # 2/5


def test_openings_are_not_ranked_by_how_well_they_went():
    # Frequency, not accuracy: the screen describes what the player plays and
    # does not claim to know which opening is their weakest.
    rows = [
        ("C50", "Often but poorly", 40, 55.0, 10, 5, 25),
        ("B20", "Rarely but well", 3, 95.0, 3, 0, 0),
    ]
    assert [o["name"] for o in _shape_openings(rows)] == [
        "Often but poorly", "Rarely but well"
    ]


def test_the_summary_makes_no_claim_about_any_one_opening():
    summary = _shape_summary(
        overview={"analyzed": 2, "total": 2},
        trend=[{"accuracy": 40.0, "opening": "A"}, {"accuracy": 60.0, "opening": "B"}],
        results={"overall": {"winRate": 50.0}},
    )
    assert "weakestOpening" not in summary
    assert "strongestOpening" not in summary


# ── _shape_summary ───────────────────────────────────────────────────────────

def test_summary_avg_accuracy_from_trend():
    summary = _shape_summary(
        overview={"analyzed": 2, "total": 2},
        trend=[{"accuracy": 40.0, "opening": "A"}, {"accuracy": 60.0, "opening": "A"}],
        results={"overall": {"winRate": 50.0}},
    )
    assert summary["avgAccuracy"] == pytest.approx(50.0)


def test_summary_avg_accuracy_none_when_no_trend():
    summary = _shape_summary(
        overview={"analyzed": 0, "total": 0},
        trend=[],
        results={"overall": {"winRate": 0.0}},
    )
    assert summary["avgAccuracy"] is None


# ── Phase fallback for games with no stored FENs ─────────────────────────────

from zugzwang.core.insights import (
    _is_endgame, _phase_of, _phase_buckets, _phase_verdict, _rate_diff,
    _shape_phase_quality,
)

_START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_QUEENLESS = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"


def test_starting_position_is_not_an_endgame():
    assert not _is_endgame(_START)


def test_a_queenless_position_is_an_endgame():
    assert _is_endgame(_QUEENLESS)


def test_one_queen_left_is_not_a_queenless_endgame():
    # Only one side traded: a large imbalance, not a simplified position.
    assert not _is_endgame("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")


def test_queens_on_but_light_material_is_an_endgame():
    assert _is_endgame("4k2q/pppppppp/8/8/8/8/PPPPPPPP/R3K2Q w - - 0 1")


def test_missing_fen_falls_back_to_ply_boundaries():
    assert _phase_of(10, None) == "opening"
    assert _phase_of(40, None) == "middlegame"
    assert _phase_of(60, None) == "endgame"


# ── Phases come from Divider, which reads the whole game ─────────────────────

def _plies(placements, *, color="white", cls="good"):
    """Rows as insights_phase_quality yields them: every ply of one game."""
    return [(1, i, cls, f"{p} w - - 0 1", color) for i, p in enumerate(placements)]


def test_phases_are_monotone_across_a_game():
    # Divider fixes where each phase begins; a phase can never be re-entered,
    # which a per-position test would allow as soon as material came back.
    rows = _plies([_START] * 4 + ["4k3/8/8/8/8/8/8/4K3"] * 2 + [_START] * 4)
    got = _phase_buckets(rows)[0]
    assert sum(sum(c.values()) for c in got.values()) == 5   # white's moves only
    # Bare kings at index 4 open the endgame. Full material returns at index 6,
    # and those plies stay endgame — a per-position test would call them opening.
    assert got["opening"] == {"good": 2}
    assert got["endgame"] == {"good": 3}
    # No middlegame at all: the endgame began no later than the middlegame would
    # have, which is Lichess's `middle.filter(m => end.forall(m < _))`.
    assert got["middlegame"] == {}


def test_a_game_can_end_before_leaving_the_opening():
    rows = _plies([_START] * 4)
    assert _phase_buckets(rows)[0]["opening"] == {"good": 2}


def test_only_the_players_own_moves_are_counted():
    # Every ply is needed to divide the game; only half of them are the
    # player's, and only those are the player's move quality.
    rows = _plies([_START] * 10, color="black")
    assert sum(sum(c.values()) for c in _phase_buckets(rows)[0].values()) == 5


def test_shape_phase_quality_totals_across_games():
    per_game = [
        {"opening": {"good": 2}, "middlegame": {"blunder": 1}, "endgame": {}},
        {"opening": {"good": 1}, "middlegame": {}, "endgame": {"best": 3}},
    ]
    out = {p["phase"]: p for p in _shape_phase_quality(per_game)}
    assert out["opening"]["total"] == 3
    assert out["middlegame"]["total"] == 1
    assert out["endgame"]["total"] == 3


# ── The phase verdict only speaks when the interval says it may ──────────────

def _games(n, *, mid_blunders, mid_total, end_blunders, end_total):
    """n identical games, so the between-game variance is zero."""
    return [
        {
            "opening": {},
            "middlegame": {"blunder": mid_blunders,
                           "good": mid_total - mid_blunders},
            "endgame": {"blunder": end_blunders, "good": end_total - end_blunders},
        }
        for _ in range(n)
    ]


def test_verdict_names_the_weakest_phase_when_the_gap_is_clear():
    v = _phase_verdict(_games(400, mid_blunders=3, mid_total=20,
                              end_blunders=0, end_total=20))
    assert v["phase"] == "middlegame"
    assert v["comparedTo"] == "endgame"
    assert v["total"] == 8000 and v["comparedTotal"] == 8000


def test_verdict_is_silent_when_the_gap_could_be_zero():
    # One game either way: nothing here separates the phases.
    v = _phase_verdict(_games(2, mid_blunders=1, mid_total=10,
                              end_blunders=1, end_total=10))
    assert v is None


def test_verdict_is_silent_on_a_near_tie_however_many_games():
    v = _phase_verdict(_games(500, mid_blunders=2, mid_total=20,
                              end_blunders=2, end_total=20))
    assert v is None


def test_rate_difference_interval_straddles_zero_for_equal_rates():
    diff, se = _rate_diff(
        _games(300, mid_blunders=1, mid_total=10, end_blunders=1, end_total=10),
        "middlegame", "endgame")
    assert diff - 1.96 * se <= 0.0 <= diff + 1.96 * se


def test_verdict_needs_two_populated_phases():
    assert _phase_verdict([{"opening": {"good": 5}, "middlegame": {},
                            "endgame": {}}]) is None


# ── The move-number chart's last bucket is not a move number ─────────────────

from zugzwang.core.insights import _MOVE_NUMBER_CAP, _shape_move_accuracy


def _scored(ply, color="white"):
    """One ply at (ply), played perfectly, as insights_move_scores yields it."""
    return (ply, color, 20, None, 20, None)


def test_long_games_pile_into_the_final_bucket():
    cap_ply = (_MOVE_NUMBER_CAP - 1) * 2
    rows = [_scored(cap_ply + 2 * i) for i in range(5)]   # moves 40, 41, 42...
    series = _shape_move_accuracy(rows)["all"]
    assert [p["move"] for p in series] == [_MOVE_NUMBER_CAP]
    assert series[0]["samples"] == 5


def test_only_the_final_bucket_is_marked_cumulative():
    rows = [_scored(0), _scored(10), _scored((_MOVE_NUMBER_CAP - 1) * 2)]
    series = _shape_move_accuracy(rows)["all"]
    assert [p["cumulative"] for p in series] == [False, False, True]
