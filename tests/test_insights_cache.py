"""FIX-B8 D (owner note 11): the Insights cache. The same state reads the stored payload; each thing the payload
depends on (games, complete runs, the labels, the classifier version, the book in use, the pattern facts, the date,
the request) gives a new key, so the stale entry is never read; the file beside the database survives a restart."""
import chess
import pytest

from zugzwang.core import insights_cache as IC
from zugzwang.core.database import Database
from tests.runs import mark_complete

PARAMS = {"color": "all", "speeds": [], "since": None, "rated": "all", "include_local": False, "view": "v2"}


def _game(db, n, color="white"):
    b = chess.Board()
    b.push_san("e4")
    return db.save_game(played_at=f"2026-11-{n:02d}T10:00:00+00:00", player_color=color, skill_level=0,
                        result="1-0", termination="resignation", move_count=1,
                        pgn='[Event "x"]\n[Result "1-0"]\n\n1. e4 1-0', final_fen=b.fen(),
                        source="chesscom", external_id=f"g{n}")


def _run(db, gid, cls="best"):
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=14)
    db._conn.execute(
        "INSERT INTO move_analyses (run_id, ply, fen_before, played_uci, pv_uci, classification) VALUES (?,?,?,?,?,?)",
        (run, 0, chess.STARTING_FEN, "e2e4", "e2e4", cls))
    db._conn.commit()
    return mark_complete(db, run)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "z.db")
    _run(d, _game(d, 1))
    yield d
    d.close()


def _counted(cache, db, params=PARAMS, today="2026-11-26"):
    built = []

    def build():
        built.append(1)
        return {"n": len(built)}
    out = cache.get_or_build(db, params, build, today=today)
    return out, len(built)


def test_the_same_state_is_built_once(db, tmp_path):
    c = IC.InsightsCache(tmp_path / "cache" / "insights.json")
    assert _counted(c, db)[1] == 1
    assert _counted(c, db)[1] == 0
    assert (c.hits, c.misses) == (1, 1)


@pytest.mark.parametrize("change", ["game", "run", "relabel", "classifier_version", "colour", "facts", "book",
                                    "classifier_code", "date", "params"])
def test_each_thing_the_payload_reads_gives_a_new_key(db, tmp_path, monkeypatch, change):
    c = IC.InsightsCache(None)
    _counted(c, db)
    params, today = PARAMS, "2026-11-26"
    if change == "game":
        _game(db, 2)
    elif change == "run":
        _run(db, _game(db, 3))
    elif change == "relabel":
        db._conn.execute("UPDATE move_analyses SET classification = 'blunder'")
    elif change == "classifier_version":
        db._conn.execute("UPDATE analysis_runs SET classifier_version = 99")
    elif change == "colour":
        db._conn.execute("UPDATE games SET player_color = 'black'")
    elif change == "facts":
        rid = db._conn.execute("SELECT id FROM analysis_runs").fetchone()[0]
        db._conn.execute("INSERT INTO pattern_facts (run_id, facts_version, classifier_version, rule_version,"
                         " computed_at, facts_json) VALUES (?, 2, 8, 1, '2026-11-26', '{}')", (rid,))
    elif change == "book":
        from zugzwang.core import books
        monkeypatch.setattr(books, "active_state", lambda: {"id": "x", "sha256": "y", "relabelled": True})
    elif change == "classifier_code":
        import zugzwang.core.classification as cls
        monkeypatch.setattr(cls, "CLASSIFIER_VERSION", cls.CLASSIFIER_VERSION + 1)
    elif change == "date":
        today = "2026-11-27"
    elif change == "params":
        params = {**PARAMS, "color": "white"}
    db._conn.commit()
    assert _counted(c, db, params, today)[1] == 1


def test_the_file_survives_a_restart_and_a_bad_file_is_ignored(db, tmp_path):
    path = tmp_path / "cache" / "insights.json"
    _counted(IC.InsightsCache(path), db)
    assert _counted(IC.InsightsCache(path), db)[1] == 0          # a new process, nothing changed
    path.write_text("{not json")
    assert _counted(IC.InsightsCache(path), db)[1] == 1          # unreadable: built as before
    assert _counted(IC.InsightsCache(path), db)[1] == 0          # and written again


def test_at_most_max_entries_are_kept(db):
    c = IC.InsightsCache(None)
    for i in range(IC.MAX_ENTRIES + 3):
        _counted(c, db, {**PARAMS, "since": f"2026-0{1 + i % 9}-{10 + i}"})
    assert len(c._mem) == IC.MAX_ENTRIES
