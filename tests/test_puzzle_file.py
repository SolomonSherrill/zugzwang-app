"""COACH-1 F: the puzzle set in its own database file (FIX-B6 decided item 6)."""
import csv
import sqlite3

from zugzwang.core.database import Database, puzzles_path
from zugzwang.core.puzzle_core import import_puzzles_file, staging_path

HEADER = ["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes",
          "GameUrl", "OpeningTags"]
FEN = "r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24"


def _csv(path, ids, rating=1500):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for i in ids:
            w.writerow([i, FEN, "f2g3 e6e7 b2b1 b3c1", rating, 80, 90, 100, "fork middlegame", "", ""])


def _old_layout(path, ids):
    """A database as FIX-B6 left it: the set inside the main file, an attempt and a rating."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE puzzles (id TEXT PRIMARY KEY, fen TEXT NOT NULL, moves_uci TEXT NOT NULL,
            rating INTEGER NOT NULL, rating_deviation INTEGER NOT NULL DEFAULT 80,
            popularity INTEGER NOT NULL DEFAULT 0, nb_plays INTEGER NOT NULL DEFAULT 0,
            themes TEXT NOT NULL DEFAULT '', game_url TEXT, opening_tags TEXT, imported_at TEXT NOT NULL);
        CREATE INDEX idx_puzzles_rating ON puzzles(rating);
        CREATE VIRTUAL TABLE puzzle_themes_fts USING fts5(themes, content='puzzles', content_rowid='rowid');
    """)
    con.executemany("INSERT INTO puzzles (id, fen, moves_uci, rating, themes, imported_at) VALUES (?,?,?,?,?,?)",
                    [(i, FEN, "f2g3 e6e7", 1400 + n, "fork short" if n % 2 else "pin long", "2026-11-23")
                     for n, i in enumerate(ids)])
    con.execute("INSERT INTO puzzle_themes_fts(puzzle_themes_fts) VALUES('rebuild')")
    con.execute("INSERT INTO meta VALUES ('puzzles_count', ?)", (str(len(ids)),))
    con.commit()
    con.close()


def test_the_file_sits_beside_the_database(tmp_path):
    assert puzzles_path(tmp_path / "zugzwang.db") == tmp_path / "zugzwang-puzzles.db"
    Database(tmp_path / "zugzwang.db").close()
    assert (tmp_path / "zugzwang-puzzles.db").exists()


def test_an_existing_set_moves_without_a_download_and_keeps_rating_attempts_sessions(tmp_path):
    db = tmp_path / "zugzwang.db"
    ids = [f"p{n:03d}" for n in range(200)]
    _old_layout(db, ids)
    d = Database(db)                                  # runs the move (v22)
    d.save_puzzle_rating(1666.0, 70.0, 0.06)
    sid = d.save_puzzle_session(mode="rated", time_limit_s=None)
    d.save_puzzle_attempt(puzzle_id="p001", session_id=sid, mode="rated", solved=True, failed=False,
                          used_hint=False, gave_up=False, solve_time_s=4.0, rating_before=1500.0,
                          rating_after=1510.0)
    d.close()
    con = sqlite3.connect(db)
    assert con.execute("SELECT 1 FROM sqlite_master WHERE name IN ('puzzles', 'puzzle_themes_fts')").fetchall() == []
    con.execute("ATTACH DATABASE ? AS pz", (str(puzzles_path(db)),))
    assert sorted(r[0] for r in con.execute("SELECT id FROM pz.puzzles")) == ids
    con.close()
    d = Database(db)                                  # a second open moves nothing
    assert d.count_puzzles_for_themes(["fork"], 2000, 2000) == 100
    assert {p.id for p in d.select_puzzles(user_rating=2000, rating_range=2000, themes=["pin"], exclude_recent=0, limit=500)} == set(ids[0::2])
    assert d.get_puzzle_rating()[0] == 1666.0
    assert d._conn.execute("SELECT count(*) FROM puzzle_attempts").fetchone()[0] == 1
    assert d._conn.execute("SELECT count(*) FROM puzzle_sessions").fetchone()[0] == 1
    d.close()


def test_the_move_gives_the_pages_back(tmp_path):
    db = tmp_path / "zugzwang.db"
    _old_layout(db, [f"p{n:05d}" for n in range(20000)])
    before = db.stat().st_size
    Database(db).close()
    assert db.stat().st_size < before / 4


def test_an_update_replaces_the_file_and_the_main_database_does_not_grow(tmp_path):
    db = tmp_path / "zugzwang.db"
    d = Database(db)
    d.close()
    first = tmp_path / "a.csv"
    _csv(first, [f"a{n:04d}" for n in range(3000)])
    assert list(import_puzzles_file(first, db))[-1][0] == "done"
    main_after_first = db.stat().st_size
    second = tmp_path / "b.csv"
    _csv(second, [f"b{n:04d}" for n in range(3000)], rating=1700)
    events = list(import_puzzles_file(second, db))
    assert events[-1][0] == "done"
    stats = events[-1][1]
    assert stats["previous"] == 3000 and stats["removed"] == 3000 and stats["count"] == 3000
    assert db.stat().st_size <= main_after_first       # the set never enters the main file
    assert not staging_path(db).exists()
    d = Database(db)
    assert tuple(d._conn.execute("SELECT min(id), count(*) FROM puzzles").fetchone()) == ("b0000", 3000)
    d.close()


def test_the_app_swaps_the_file_on_its_own_connection(tmp_path):
    db = tmp_path / "zugzwang.db"
    d = Database(db)
    f = tmp_path / "a.csv"
    _csv(f, ["x1", "x2"])
    events = list(import_puzzles_file(f, db, install=lambda new, _t: d.replace_puzzles_file(new)))
    assert events[-1][0] == "done"
    assert d._conn.execute("SELECT count(*) FROM puzzles").fetchone()[0] == 2
    assert d.count_puzzles_for_themes(["fork"], 2000, 2000) == 2
    d.close()


def test_a_cancelled_import_leaves_the_set_and_no_staging_file(tmp_path):
    db = tmp_path / "zugzwang.db"
    Database(db).close()
    f = tmp_path / "a.csv"
    _csv(f, ["k1"])
    list(import_puzzles_file(f, db))
    big = tmp_path / "b.csv"
    _csv(big, [f"n{n:05d}" for n in range(12000)])
    events = list(import_puzzles_file(big, db, is_cancelled=lambda: True))
    assert events[-1] == ("cancelled",)
    assert not staging_path(db).exists()
    d = Database(db)
    assert [r[0] for r in d._conn.execute("SELECT id FROM puzzles")] == ["k1"]
    d.close()


def test_a_read_only_connection_does_not_hold_the_puzzle_file(tmp_path):
    db = tmp_path / "zugzwang.db"
    Database(db).close()
    ro = Database(db, read_only=True)
    assert [r[1] for r in ro._conn.execute("PRAGMA database_list")] == ["main"]
    ro.close()
