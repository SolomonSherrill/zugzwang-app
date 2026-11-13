"""VAL-DEATH, the parts that need no engine: the breaker, the supervisor's backoff, and
the v14 migration that stamps existing runs complete only when they are.
The kill tests are in `test_engine_death.py`."""

import json

import chess
import chess.engine
import pytest

from tests.test_engine_death import _plies, _save_games
from zugzwang.core.database import Database, MoveAnalysis
from zugzwang.core.engine_supervisor import DeathBreaker, EngineDied, SupervisedEngine



def test_breaker_trips_past_three_deaths_within_fifty_games():
    breaker = DeathBreaker(max_deaths=3, window=50)
    breaker.game_started()
    for _ in range(3):
        breaker.death()
    assert not breaker.tripped                  # three is the limit, not past it
    breaker.death()
    assert breaker.tripped


def test_breaker_forgets_deaths_older_than_the_window():
    breaker = DeathBreaker(max_deaths=3, window=50)
    breaker.game_started()
    for _ in range(4):
        breaker.death()
    for _ in range(50):
        breaker.game_started()
    assert breaker.recent_deaths() == 0 and not breaker.tripped


def test_supervisor_gives_up_after_the_backoff_and_says_so():
    """A death whose respawn never succeeds is not poison: the engine is gone."""
    class Dead:
        id = {"name": "Stockfish test"}

        def analyse(self, *a, **k):
            raise chess.engine.EngineTerminatedError("engine process died unexpectedly")

        def close(self):
            pass

        transport = type("T", (), {"get_returncode": lambda self: -9})()

    starts = []

    def start():
        starts.append(1)
        if len(starts) > 1:
            raise FileNotFoundError("stockfish: no such file")
        return Dead()

    slept: list[float] = []
    deaths: list[int] = []
    sup = SupervisedEngine(start, backoff=(0.5, 2.0, 5.0), sleep=slept.append,
                           on_death=lambda: deaths.append(1))
    with pytest.raises(EngineDied) as info:
        sup.analyse(chess.Board(), chess.engine.Limit(depth=1))
    assert slept == [0.5, 2.0, 5.0]             # each delay tried, in order
    assert len(starts) == 4 and deaths == [1]
    assert not info.value.poison and "could not be restarted" in str(info.value)


def test_migration_marks_only_whole_runs_complete(tmp_path):
    """v14 on a database from before it: a run holding every ply of its PGN is stamped
    complete; one a dead engine cut short is left incomplete — not rewritten, no longer
    shown, and its game pending again."""
    path = tmp_path / "old.db"
    db = Database(path)
    gids = _save_games(db, ["9000001", "9000002"])
    db._conn.execute("ALTER TABLE analysis_runs DROP COLUMN completed_at")
    for ext, stored in (("9000001", 10), ("9000002", 4)):
        run = db._conn.execute(
            "INSERT INTO analysis_runs (game_id, engine_name, depth, created_at,"
            " payload_json, white_accuracy) VALUES (?, 'Stockfish', 8,"
            " '2026-06-01T00:00:00+00:00', '{}', 75.0)", (gids[ext],)).lastrowid
        for ply in range(stored):
            db._insert_move_analysis(run, MoveAnalysis(
                ply=ply, fen_before="x", played_uci="e2e4", best_uci=None, pv_uci="",
                score_before_cp=0, score_before_mate=None, score_after_cp=0,
                score_after_mate=None, second_best_uci=None, second_best_cp=None,
                second_best_mate=None, classification="best", is_book=False))
    db._conn.commit()
    db.close()

    db = Database(path)                                     # v14 runs on open
    whole, cut = (db._conn.execute(
        "SELECT completed_at FROM analysis_runs WHERE game_id = ?", (gids[e],)).fetchone()[0]
        for e in ("9000001", "9000002"))
    assert whole == "2026-06-01T00:00:00+00:00" and cut is None
    assert db.load_latest_run(gids["9000002"]) is None
    assert [g.external_id for g in db.games_pending_analysis("chesscom", 8)] == ["9000002"]
    (audit,) = db.audit_run_completeness()
    assert (audit.external_id, audit.stored_plies, audit.game_plies, audit.completed) == (
        "9000002", 4, 10, False)
    assert _plies(db, audit.run_id) == 4                    # not rewritten
    record = json.loads(db._conn.execute(
        "SELECT value FROM meta WHERE key = 'completed_at_backfill'").fetchone()[0])
    assert (record["runs"], record["complete"], record["incomplete"]) == (2, 1, 1)
