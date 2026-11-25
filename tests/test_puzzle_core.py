"""Glicko-2 update + CSV import tests (Phase 2, priority 5)."""

import sqlite3

import pytest

import zugzwang.config as C
from zugzwang.core.database import Database, puzzles_path
from zugzwang.core.puzzle_core import (
    alternate_final_mates,
    glicko2_update,
    import_puzzles_csv,
)


# ── glicko2_update ───────────────────────────────────────────────────────────

def test_win_against_higher_rated_raises_rating():
    new_r, new_rd, new_vol = glicko2_update(800, 350, 0.06, 1500, 80, outcome=1.0)
    assert new_r > 800
    assert new_rd < 350          # uncertainty shrinks after a game
    assert new_vol > 0


def test_loss_against_lower_rated_drops_rating():
    new_r, _, _ = glicko2_update(1500, 80, 0.06, 800, 80, outcome=0.0)
    assert new_r < 1500


@pytest.mark.parametrize(
    "rating, rd, puzzle_rating, outcome",
    [
        (100, 350, 3000, 0.0),    # already at floor, lose to a monster
        (3500, 350, 100, 1.0),    # already at ceiling, beat a beginner
        (1500, 350, 1500, 1.0),
        (1500, 350, 1500, 0.0),
        (800, 200, 1200, 1.0),
    ],
)
def test_rating_and_rd_stay_in_bounds(rating, rd, puzzle_rating, outcome):
    new_r, new_rd, new_vol = glicko2_update(
        rating, rd, 0.06, puzzle_rating, 80, outcome=outcome
    )
    assert 100.0 <= new_r <= 3500.0
    assert 30.0 <= new_rd <= 350.0
    assert new_vol > 0


def test_rd_converges_toward_floor_over_many_games():
    rating, rd, vol = 1500.0, 350.0, 0.06
    for _ in range(50):
        rating, rd, vol = glicko2_update(rating, rd, vol, 1500, 80, outcome=1.0)
        assert rd >= 30.0
    assert rd < 150.0  # many games -> much tighter than the initial 350


# ── import_puzzles_csv ───────────────────────────────────────────────────────

_HEADER = "PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags"


def _row(pid, rating="1500", rd="80", pop="90", nb="100", themes="fork"):
    fen = "8/8/8/8/8/8/8/8 w - - 0 1"
    return f"{pid},{fen},e2e4 e7e5,{rating},{rd},{pop},{nb},{themes},,"


def _write_csv(path, rows):
    path.write_text("\n".join([_HEADER, *rows]) + "\n", encoding="utf-8")


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "puz.db"
    Database(p)  # creates the puzzles + puzzle_themes_fts schema the import needs
    return p


def _puzzle_count(db_path):
    conn = sqlite3.connect(str(puzzles_path(db_path)))
    try:
        return conn.execute("SELECT COUNT(*) FROM puzzles").fetchone()[0]
    finally:
        conn.close()


def _run(csv_path, db_path, is_cancelled=lambda: False):
    return list(import_puzzles_csv(csv_path, db_path, is_cancelled))


def test_import_inserts_valid_rows(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, [_row("aaa"), _row("bbb")])
    events = _run(csv_path, db_path)
    assert events[-1] == ("done", 2)
    assert _puzzle_count(db_path) == 2


def test_import_filters_low_nbplays_boundary(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    # nb_plays: 50 is kept (filter is `< 50`), 49 is dropped.
    _write_csv(csv_path, [_row("keep50", nb="50"), _row("drop49", nb="49")])
    _run(csv_path, db_path)
    conn = sqlite3.connect(str(puzzles_path(db_path)))
    ids = {r[0] for r in conn.execute("SELECT id FROM puzzles").fetchall()}
    conn.close()
    assert ids == {"keep50"}


def test_import_filters_negative_popularity(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, [_row("neg", pop="-1"), _row("zero", pop="0")])
    _run(csv_path, db_path)
    conn = sqlite3.connect(str(puzzles_path(db_path)))
    ids = {r[0] for r in conn.execute("SELECT id FROM puzzles").fetchall()}
    conn.close()
    assert ids == {"zero"}


def test_import_skips_rows_with_bad_rating(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, [_row("good"), _row("bad", rating="not-an-int")])
    events = _run(csv_path, db_path)
    assert events[-1] == ("done", 1)


def test_import_dedups_on_puzzle_id(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, [_row("dup", rating="1500"), _row("dup", rating="2000")])
    _run(csv_path, db_path)
    assert _puzzle_count(db_path) == 1


def test_import_missing_csv_yields_error(tmp_path, db_path):
    events = _run(tmp_path / "nope.csv", db_path)
    assert events == [("error", f"No such file: {tmp_path / 'nope.csv'}")]


def test_import_cancel_reports_and_adds_nothing(tmp_path, db_path):
    csv_path = tmp_path / "p.csv"
    _write_csv(csv_path, [_row("aaa"), _row("bbb")])
    events = _run(csv_path, db_path, is_cancelled=lambda: True)
    assert events == [("cancelled",)]
    assert _puzzle_count(db_path) == 0


# ── alternate_final_mates (F7) ───────────────────────────────────────────────
#
# Lichess accepts any mate on a puzzle's final move. The stored solution names
# one, so exact matching rejects answers Lichess would call correct. The sidecar
# precomputes the full set at fetch time; these pin what that set contains.
#
# Puzzle format: moves_uci[0] is the opponent's setup move, the rest is the
# solution, so every fixture below is "black plays a waiting move, white mates".

# Back rank with two rooks: Ra8# and Re8# both mate.
TWO_MATES_FEN = "6k1/5ppp/8/8/7p/8/8/R3R2K b - - 0 1"
# Only d7d8=N mates; d7d8=Q does not give check from d8 to b7.
UNDERPROMO_FEN = "R7/1k1P4/7p/Q7/K7/8/8/8 b - - 0 1"


def test_every_mate_is_offered_not_just_the_stored_one():
    mates = alternate_final_mates(TWO_MATES_FEN, ["h4h3", "a1a8"])
    assert mates == ["a1a8", "e1e8"]


def test_the_stored_solution_is_always_included():
    """The caller falls back to this list, so leaving out the move the puzzle
    actually ships would reject the intended answer."""
    for stored in ("a1a8", "e1e8"):
        assert stored in alternate_final_mates(TWO_MATES_FEN, ["h4h3", stored])


def test_a_non_mating_final_move_has_no_alternates():
    """Ra7 wins but does not mate. The puzzle is then about a specific idea, so
    no other move is interchangeable with it."""
    assert alternate_final_mates(TWO_MATES_FEN, ["h4h3", "a1a7"]) == []


def test_alternates_are_computed_for_the_final_move_only():
    """Truncating the line so the mate is no longer last must yield nothing —
    otherwise a mid-solution move would start accepting substitutes."""
    assert alternate_final_mates(TWO_MATES_FEN, ["h4h3"]) == []


def test_an_underpromotion_mate_is_returned_in_full():
    """F8 guard. F8 requires the exact promotion piece. Returning full UCIs is
    what lets the caller compare exactly instead of by from/to, so the knight
    here can never be silently satisfied by a queen."""
    mates = alternate_final_mates(UNDERPROMO_FEN, ["h6h5", "d7d8n"])
    assert mates == ["d7d8n"]
    assert "d7d8q" not in mates


def test_a_single_mate_still_returns_itself():
    """Not an empty list — the caller treats empty as 'no mate rule applies'."""
    assert alternate_final_mates(UNDERPROMO_FEN, ["h6h5", "d7d8n"]) == ["d7d8n"]


def test_an_illegal_line_is_rejected_rather_than_raising():
    """Corrupt CSV rows must not take down a whole fetch of puzzles."""
    assert alternate_final_mates(TWO_MATES_FEN, ["h4h3", "a1a4"]) == []
    assert alternate_final_mates(TWO_MATES_FEN, ["zzzz", "a1a8"]) == []


def test_a_puzzle_with_no_solution_move_is_ignored():
    assert alternate_final_mates(TWO_MATES_FEN, []) == []
    assert alternate_final_mates(TWO_MATES_FEN, ["h4h3"]) == []
