"""UI-BUILD-2 C: the redesigned Insights' figures (core/insights_v2.py) and the Daily filter."""
from datetime import datetime, timezone

import pytest

import zugzwang.config as C
from zugzwang.core import insights_v2 as V
from zugzwang.core.database import Database, InsightsFilter, MoveAnalysis
from zugzwang.core.insights import build_insights

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def test_month_keys_end_with_this_month():
    assert V.month_keys(NOW, 3) == ["2026-09", "2026-10", "2026-11"]
    assert V.month_keys(datetime(2026, 1, 5, tzinfo=timezone.utc), 2) == ["2025-12", "2026-01"]


def test_families_and_eco_ranges():
    assert V.family("Sicilian Defense: Najdorf Variation") == "Sicilian Defense"
    assert V.family(None) is None
    assert V.eco_range({"B90", "B20", "B33"}) == "B20–B90"
    assert V.eco_range({"B01"}) == "B01"
    assert V.eco_range({""}) is None


def _g(i, when, color="white", result="1-0", term="checkmate", name="Ruy Lopez: Open", eco="C80",
       acc=80.0, analysed=True):
    return (i, when, color, result, term, eco, name, acc, analysed)


def test_shape_games_months_ends_and_openings(monkeypatch):
    monkeypatch.setattr(C, "INSIGHTS_MIN_OPENING_GAMES", 2)
    games = [
        _g(1, "2026-11-02T10:00:00+00:00"),
        _g(2, "2026-11-03T10:00:00+00:00", result="0-1", term="resignation", acc=70.0, eco="C60",
           name="Ruy Lopez"),
        _g(3, "2026-10-03T10:00:00+00:00", result="1/2-1/2", term="agreement"),
        _g(4, "2026-10-04T10:00:00+00:00", color="black", result="0-1", term="timeout",
           name="Sicilian Defense", eco="B20"),                    # one game: below the floor
        _g(5, "2026-11-04T10:00:00+00:00", analysed=False, acc=None),
    ]
    out = V.shape_games(games, {1: 2, 2: 0, 3: 1}, NOW)
    nov = out["monthly"][-1]
    assert (nov["month"], nov["games"], nov["analysed"], nov["accuracy"]) == ("2026-11", 3, 2, 75.0)
    assert nov["blundersPerGame"] == 1.0                          # 2 + 0 over 2 analysed
    assert nov["winRate"] == 66.7          # won, lost, and the unanalysed game won: every game counts
    ruy = out["openings"]["white"]
    assert [(o["name"], o["eco"], o["games"]) for o in ruy] == [("Ruy Lopez", "C60–C80", 3)]
    assert out["openings"]["black"] == []
    assert ruy[0]["score"] == 50.0                                 # W, L, D
    # wins: games 1 and 5 by mate, game 4 (Black, 0-1) on time; the one loss resigned
    assert out["ends"]["win"]["games"] == 3 and out["ends"]["win"]["mate"] == 66.7
    assert out["ends"]["win"]["time"] == 33.3
    assert out["ends"]["loss"]["games"] == 1 and out["ends"]["loss"]["resigned"] == 100.0
    assert out["ends"]["draw"]["games"] == 1


def test_heat_names_a_best_block_only_with_enough_games():
    few = [_g(i, "2026-11-07T17:30:00+00:00", acc=90.0) for i in range(V.HEAT_MIN_GAMES - 1)]
    out = V.shape_games(few, {}, NOW)
    assert out["heat"]["best"] is None
    assert all(c["accuracy"] is None for c in out["heat"]["cells"])
    enough = [_g(i, "2026-11-07T17:30:00+00:00", acc=90.0) for i in range(V.HEAT_MIN_GAMES)]
    best = V.shape_games(enough, {}, NOW)["heat"]["best"]
    assert best["games"] == V.HEAT_MIN_GAMES and best["accuracy"] == 90.0


def _ply(gid, color, ply, cls, fen):
    return (gid, color, ply, cls, fen, 20, None, -20, None)


def test_move_quality_leaves_book_out_and_counts_the_users_blunders_only():
    plies = [_ply(1, "white", 0, "book", START), _ply(1, "white", 1, "blunder", AFTER_E4),
             _ply(1, "white", 2, "blunder", START), _ply(1, "white", 3, "best", AFTER_E4)]
    mq, by_phase, blunders = V.shape_plies(plies)
    assert mq["you"]["moves"] == 1 and mq["you"]["pct"]["blunder"] == 100.0
    assert mq["opponents"]["moves"] == 2 and mq["opponents"]["pct"]["blunder"] == 50.0
    assert blunders == {1: 1}
    opening = by_phase["phases"][0]
    assert opening["phase"] == "opening" and opening["games"] == 1


def _store(db, ext, speed, tc, depth=14):
    pgn = f'[Event "t"]\n[White "alice"]\n[Black "bob"]\n[TimeControl "{tc}"]\n\n1. e4 e5 1-0\n'
    gid = db.save_game(played_at="2026-11-10T10:00:00+00:00", player_color="white", skill_level=0,
                       result="1-0", termination="resignation", move_count=2, pgn=pgn,
                       final_fen=AFTER_E4, source="chesscom", external_id=ext)
    if speed:
        db._conn.execute("UPDATE games SET speed=? WHERE id=?", (speed, gid))
        db._conn.commit()
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=depth)
    plies = [MoveAnalysis(ply=i, fen_before=f, played_uci=u, best_uci=u, pv_uci=u, score_before_cp=20,
                          score_before_mate=None, score_after_cp=-20, score_after_mate=None,
                          second_best_uci=None, second_best_cp=None, second_best_mate=None,
                          classification="best", is_book=False)
             for i, (f, u) in enumerate([(START, "e2e4"), (AFTER_E4, "e7e5")])]
    db.complete_analysis_run(run, {}, white_accuracy=80.0, black_accuracy=80.0, plies=plies)
    return gid


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "i.db")
    yield d
    d.close()


def test_daily_filter_selects_the_one_over_n_time_controls(db):
    _store(db, "a", "blitz", "180+2")
    daily = _store(db, "b", None, "1/86400")
    _store(db, "c", None, "-")
    rows = db.insights_game_rows(InsightsFilter(speeds=("daily",)))
    assert [r[0] for r in rows] == [daily]
    both = db.insights_game_rows(InsightsFilter(speeds=("blitz", "daily")))
    assert len(both) == 2


def test_build_insights_v2_reads_depth_14_runs_only(db):
    gid = _store(db, "a", "blitz", "180+2")
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=24)
    plies = db.load_move_analyses(db.load_standard_run(gid).id)
    db.complete_analysis_run(run, {}, white_accuracy=99.0, black_accuracy=99.0, plies=plies)
    out = build_insights(db, view="v2", speeds=["daily", "blitz"])
    assert out["view"] == "v2"
    assert out["summary"]["accuracy"] == 80.0 and out["summary"]["analysed"] == 1
    assert out["moveQuality"]["you"]["moves"] == 1                 # one run's plies, not two
