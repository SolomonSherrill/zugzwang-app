"""UI-BUILD C: Home's read-only figures (core/home_summary.py, `rpc_home_summary`)."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from zugzwang.core import home_summary as HS
from zugzwang.core.database import Database

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("zugzwang_sidecar_main_hs", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def pgn(white="alice", black="bob", we="1500", be="1400", tc="180+2", result="1-0"):
    return (f'[White "{white}"]\n[Black "{black}"]\n[WhiteElo "{we}"]\n[BlackElo "{be}"]\n'
            f'[TimeControl "{tc}"]\n[Result "{result}"]\n\n1. e4 e5 {result}\n')


def test_bucket_reads_speed_or_chesscoms_daily_notation():
    assert HS.bucket("blitz", "180+2") == "blitz"
    assert HS.bucket(None, "1/86400") == "daily"
    assert HS.bucket(None, "-") is None and HS.bucket(None, "?") is None


def test_own_rating_is_the_users_side_and_only_a_real_number():
    h = HS.headers(pgn(we="1500", be="?"))
    assert HS.own_rating(h, "white") == 1500
    assert HS.own_rating(h, "black") is None
    assert HS.own_rating(h, None) is None


def test_ratings_change_over_30_days_and_only_recent_time_controls():
    games = [
        ("2026-10-01T10:00:00+00:00", "chesscom", "blitz", "180+2", 1000),   # before the window
        ("2026-11-10T10:00:00+00:00", "chesscom", "blitz", "180+2", 1020),
        ("2026-11-19T10:00:00+00:00", "chesscom", "blitz", "180+2", 1031),
        ("2026-11-15T10:00:00+00:00", "lichess", "rapid", "600+0", 1600),    # first ever: no change
        ("2026-09-01T10:00:00+00:00", "chesscom", "bullet", "60", 700),      # not played recently
        ("2026-11-15T10:00:00+00:00", "local", None, None, None),
    ]
    rows = HS.rating_rows(games, NOW)
    assert [(r["platform"], r["speed"], r["rating"], r["change"]) for r in rows] == [
        ("chess.com", "blitz", 1031, 31),
        ("Lichess", "rapid", 1600, None),
    ]
    assert rows[0]["series"][0]["rating"] == 1000 and len(rows[0]["series"]) == 3


def test_puzzle_row_changes_from_the_window_start_and_peaks_only_on_the_day():
    attempts = [("2026-11-19T10:00:00+00:00", 1500, 1510), ("2026-11-20T10:00:00+00:00", 1510, 1525)]
    p = HS.puzzle_row(attempts, 1525, NOW)
    # ruling 5 (2026-11-20, third): the first attempt is inside the window, so no change
    assert p["platform"] == "Zugzwang" and p["rating"] == 1525 and p["change"] is None
    assert p["newPeak"] is True
    older = [("2026-09-01T10:00:00+00:00", 1500, 1490)] + attempts
    assert HS.puzzle_row(older, 1525, NOW)["change"] == 35     # current − last rating before the window
    later = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    assert HS.puzzle_row(attempts, 1525, later)["newPeak"] is False
    assert HS.puzzle_row([], 1500, NOW) is None


def test_summarize_counts_accuracy_and_win_rate_as_insights_defines_them():
    rows = [
        (1, "2026-11-19T10:00:00+00:00", "white", "1-0", "checkmate", "chesscom", "blitz", pgn(), "B01", "Scandinavian", 90.0, 80.0, True),
        (2, "2026-11-18T10:00:00+00:00", "black", "1-0", "resignation", "chesscom", "blitz", pgn(), None, None, 70.0, 60.0, True),
        (3, "2026-11-17T10:00:00+00:00", "white", "1/2-1/2", "agreement", "chesscom", "blitz", pgn(), None, None, None, None, False),
        (4, "2026-11-16T10:00:00+00:00", None, "1-0", "checkmate", "imported", None, pgn(), None, None, 50.0, 50.0, True),
        (5, "2026-11-15T10:00:00+00:00", "white", "1-0", "checkmate", "local", None, pgn(), None, None, None, None, False),
    ]
    s = HS.summarize(rows, NOW)
    assert (s["games"], s["analysed"]) == (5, 3)
    assert s["avgAccuracy"] == 75.0           # the user's 90 and 60; unattributed game left out
    assert s["winRate"] == 33.3                # 1 win of 3 attributed results; the Stockfish win left out (ruling 4)
    assert [r["id"] for r in s["recent"]] == [1, 2, 3, 4, 5]
    want = {"outcome": "win", "opponent": "bob", "accuracy": 90.0, "opponentAccuracy": 80.0, "timeControl": "180+2"}
    assert {k: s["recent"][0][k] for k in want} == want
    assert s["recent"][2]["accuracy"] is None


def test_rpc_home_summary_on_an_empty_database(tmp_path):
    srv = object.__new__(sidecar.Server)
    srv._db = Database(tmp_path / "t.db")
    out = srv.rpc_home_summary(now="2026-11-20T12:00:00+00:00")
    assert out["games"] == 0 and out["analysed"] == 0
    assert out["avgAccuracy"] is None and out["winRate"] is None
    assert out["ratings"] == [] and out["recent"] == [] and out["puzzles"] is None
