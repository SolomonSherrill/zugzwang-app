"""FRIENDS-1 C, ruling R2: the ChessGoals table as a dated data file; a test per table row."""
import json

import pytest

from zugzwang.core.friends import rating_compare as RC

ROWS = json.loads(RC.DATA_PATH.read_text())["rows"]


def test_the_data_file_is_dated_and_sourced():
    t = RC.table()
    assert t["url"] == "https://chessgoals.com/rating-comparison/"
    assert t["retrieved"] == "2026-11-21"
    assert "ChessGoals" in t["source"]
    assert len(t["rows"]) == 35
    assert RC.credit() == {"source": t["source"], "url": t["url"], "retrieved": "2026-11-21"}


@pytest.mark.parametrize("row", ROWS, ids=[f"chesscom_blitz_{r['chesscom_blitz']}" for r in ROWS])
def test_each_table_row_converts_exactly(row):
    assert RC.lichess_to_chesscom(row["lichess_blitz"], "blitz") == row["chesscom_blitz"]
    assert RC.lichess_to_chesscom(row["lichess_bullet"], "bullet") == row["chesscom_bullet"]
    assert RC.lichess_to_chesscom(row["lichess_rapid"], "rapid") == row["chesscom_rapid"]
    assert RC.lichess_to_chesscom(row["lichess_classical"], "classical") == row["chesscom_rapid"]


def test_between_rows_it_interpolates():
    a, b = ROWS[10], ROWS[11]          # lichess blitz 1620 -> 1300, 1655 -> 1350
    mid = (a["lichess_blitz"] + b["lichess_blitz"]) / 2
    assert RC.lichess_to_chesscom(mid, "blitz") == round((a["chesscom_blitz"] + b["chesscom_blitz"]) / 2)


def test_off_the_table_or_unknown_is_blank():
    assert RC.lichess_to_chesscom(ROWS[0]["lichess_blitz"] - 1, "blitz") is None
    assert RC.lichess_to_chesscom(ROWS[-1]["lichess_blitz"] + 1, "blitz") is None
    assert RC.lichess_to_chesscom(None, "blitz") is None
    assert RC.lichess_to_chesscom(1500, "daily") is None
    assert RC.chesscom_mode("classical") == "rapid"


@pytest.mark.parametrize("tc,mode", [("1+0", "bullet"), ("2+1", "bullet"), ("3+0", "blitz"), ("3+2", "blitz"),
                                     ("5+0", "blitz"), ("5+3", "blitz"), ("10+0", "rapid"), ("10+5", "rapid"),
                                     ("15+10", "rapid"), ("30+0", "rapid")])
def test_the_ten_live_time_controls_map_to_a_chesscom_mode(tc, mode):
    base, inc = tc.split("+")
    assert RC.speed_of(int(base) * 60, int(inc)) == mode
