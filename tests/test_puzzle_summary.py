"""UI-BUILD-2 E2: the Puzzles lobby's read-only figures (core/puzzle_summary.py, `rpc_puzzle_summary`)."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from zugzwang.core import puzzle_summary as PS
from zugzwang.core.database import Database

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_ps", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def att(i, at, mode="rated", sid=None, solved=1, failed=0, before=1500.0, after=1510.0):
    return (i, sid, mode, at, solved, failed, before, after)


def test_solved_counts_only_clean_solves_and_tries_every_attempt():
    attempts = [
        att(1, "2026-11-20T10:00:00+00:00"),
        att(2, "2026-11-20T10:01:00+00:00", failed=1, after=1495.0),   # solved after a miss
        att(3, "2026-11-20T10:02:00+00:00", solved=0, failed=1),        # gave up
    ]
    out = PS.summarize(attempts, [], 1495.0, NOW)
    assert out["tries"] == 3 and out["solved"] == 1


def test_bests_read_finished_sessions_per_rush_length_and_survival():
    sessions = [
        (1, "rush", "2026-11-19T10:00:00+00:00", "2026-11-19T10:03:00+00:00", 180, 12),
        (2, "rush", "2026-11-19T11:00:00+00:00", "2026-11-19T11:03:00+00:00", 180, 15),
        (3, "rush", "2026-11-19T12:00:00+00:00", None, 300, 40),                  # never finished
        (4, "survival", "2026-11-19T13:00:00+00:00", "2026-11-19T13:09:00+00:00", None, 7),
        (5, "rated", "2026-11-19T14:00:00+00:00", "2026-11-19T14:30:00+00:00", None, 20),
    ]
    rush, survival = PS.bests(sessions)
    assert rush == {"180": 15} and survival == 7


def test_loose_attempts_group_by_gap_and_mode():
    a = [
        att(1, "2026-11-18T14:00:00+00:00", before=800.0, after=900.0),
        att(2, "2026-11-18T14:20:00+00:00", before=900.0, after=950.0),
        att(3, "2026-11-18T14:55:00+00:00", before=950.0, after=940.0, failed=1),  # 35 min gap
        att(4, "2026-11-18T14:56:00+00:00", mode="theme", before=940.0, after=960.0),
    ]
    rows = PS.recent_sessions(a, [])
    assert [(r["mode"], r["tried"], r["solved"], r["ratingChange"], r["inferred"]) for r in rows] == [
        ("theme", 1, 1, 20, True),
        ("rated", 1, 0, -10, True),
        ("rated", 2, 2, 150, True),
    ]


def test_stored_sessions_rated_change_and_rush_best_flag():
    sessions = [
        (1, "rated", "2026-11-20T09:00:00+00:00", "2026-11-20T09:30:00+00:00", None, 2),
        (2, "rush", "2026-11-20T10:00:00+00:00", "2026-11-20T10:03:00+00:00", 180, 9),
        (3, "rush", "2026-11-19T10:00:00+00:00", "2026-11-19T10:03:00+00:00", 180, 4),
        (4, "rated", "2026-11-20T11:00:00+00:00", None, None, 0),        # no attempt: left out
        (5, "survival", "2026-11-20T12:00:00+00:00", None, None, 3),     # unfinished: left out
    ]
    attempts = [
        att(1, "2026-11-20T09:01:00+00:00", sid=1, before=1500.0, after=1512.0),
        att(2, "2026-11-20T09:02:00+00:00", sid=1, before=1512.0, after=1500.4, failed=1),
        att(3, "2026-11-20T10:01:00+00:00", mode="rush", sid=2, before=1500.4, after=None),
    ]
    rows = PS.recent_sessions(attempts, sessions)
    assert [r["id"] for r in rows] == [2, 1, 3]
    rush, rated, older = rows
    assert rush["score"] == 9 and rush["best"] is True and rush["timeLimit"] == 180
    assert older["best"] is False
    assert rated["tried"] == 2 and rated["solved"] == 1 and rated["ratingChange"] == 0


def test_rating_row_is_homes_with_the_peak_only_on_the_day():
    attempts = [att(1, "2026-11-20T10:00:00+00:00", before=1500.0, after=1525.0)]
    out = PS.summarize(attempts, [], 1525.0, NOW)
    assert out["rating"]["rating"] == 1525 and out["rating"]["newPeak"] is True
    later = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert PS.summarize(attempts, [], 1525.0, later)["rating"]["newPeak"] is False


def test_recent_sessions_are_limited_to_five_newest_first():
    attempts = [att(i, f"2026-11-{10 + i:02d}T10:00:00+00:00") for i in range(7)]
    rows = PS.recent_sessions(attempts, [])
    assert len(rows) == 5 and rows[0]["startedAt"].startswith("2026-11-16")


def test_rpc_puzzle_summary_reads_the_tables_and_writes_nothing(tmp_path):
    db = Database(tmp_path / "t.db")
    srv = object.__new__(sidecar.Server)
    srv._db = db
    empty = srv.rpc_puzzle_summary(now="2026-11-20T12:00:00+00:00")
    assert empty["rating"] is None and empty["tries"] == 0 and empty["sessions"] == []
    assert empty["rushBest"] == {} and empty["survivalBest"] is None

    sid = db.save_puzzle_session(mode="rush", time_limit_s=180)
    db.save_puzzle_attempt(puzzle_id="p1", session_id=sid, mode="rush", solved=True, failed=False,
                           used_hint=False, gave_up=False, solve_time_s=3.0,
                           rating_before=800.0, rating_after=None)
    db.update_puzzle_session(sid, score=1)
    db.save_puzzle_attempt(puzzle_id="p2", session_id=None, mode="rated", solved=True, failed=False,
                           used_hint=False, gave_up=False, solve_time_s=5.0,
                           rating_before=800.0, rating_after=900.0)
    db.save_puzzle_rating(900.0, 300.0, 0.06)
    counts = lambda: [db._conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                      for t in ("puzzle_attempts", "puzzle_sessions", "puzzle_rating")]
    before = counts()
    out = srv.rpc_puzzle_summary()
    assert counts() == before
    assert out["tries"] == 2 and out["solved"] == 2
    assert out["rushBest"] == {"180": 1}
    assert out["rating"]["rating"] == 900
    assert [s["mode"] for s in out["sessions"]] == ["rated", "rush"]
