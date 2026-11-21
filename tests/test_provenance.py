"""RUN-PROVENANCE: every analysis run records what produced it (`core/provenance.py`)."""

import json
import sqlite3

import zugzwang.config as C
from zugzwang.core import provenance
from zugzwang.core.database import Database


def _game(db: Database) -> int:
    return db.save_game(
        played_at="2026-11-06T00:00:00+00:00", player_color="white", skill_level=0,
        result="1-0", termination="checkmate", move_count=1,
        pgn='[Event "?"]\n\n1. e4 *', final_fen="x", source="chesscom", external_id="1",
    )


def test_v16_adds_a_nullable_provenance_column(tmp_path):
    db = Database(tmp_path / "t.db")
    cols = {r[1]: r for r in db._conn.execute("PRAGMA table_info(analysis_runs)")}
    assert "provenance_json" in cols
    assert cols["provenance_json"][3] == 0          # nullable: NULL = before provenance


def test_v16_is_idempotent_on_reopen(tmp_path):
    Database(tmp_path / "t.db").close()
    Database(tmp_path / "t.db").close()
    c = sqlite3.connect(tmp_path / "t.db")
    cols = [r[1] for r in c.execute("PRAGMA table_info(analysis_runs)")]
    assert cols.count("provenance_json") == 1


def test_a_run_without_a_stamp_stores_null(tmp_path):
    db = Database(tmp_path / "t.db")
    run = db.save_analysis_run(game_id=_game(db), engine_name="Stockfish", depth=14)
    row = db._conn.execute("SELECT provenance_json FROM analysis_runs WHERE id=?",
                           (run,)).fetchone()
    assert row[0] is None


def test_engine_stamp_round_trips_and_records_the_configuration(tmp_path):
    binary = tmp_path / "sf"
    binary.write_bytes(b"not really stockfish")
    stamp = provenance.engine_run(engine_name="Stockfish 18", engine_path=binary,
                                  depth=14, has_book=False)
    db = Database(tmp_path / "t.db")
    run = db.save_analysis_run(game_id=_game(db), engine_name="Stockfish", depth=14,
                               provenance=stamp)
    got = json.loads(db._conn.execute(
        "SELECT provenance_json FROM analysis_runs WHERE id=?", (run,)).fetchone()[0])
    assert got == stamp
    assert got["kind"] == "engine"
    assert got["engine"] == "Stockfish 18"
    assert got["engine_sha256"] == provenance.file_sha256(str(binary))
    assert (got["depth"], got["after_move_depth"]) == (14, 10)
    assert got["threads"] == C.ANALYSIS_THREADS == 1
    assert got["hash_mb"] == C.ANALYSIS_HASH_MB
    assert got["multipv"] == C.ANALYSIS_MULTIPV
    assert got["pv_store_len"] == C.ANALYSIS_PV_STORE_LEN
    assert got["final_position_searched"] is True
    assert "stamped_at" in got and "commit" in got and "dirty" in got


def test_no_book_is_recorded_as_null_not_omitted():
    stamp = provenance.engine_run(engine_name=None, engine_path=None, depth=14,
                                  has_book=False)
    assert "book" in stamp and stamp["book"] is None
    assert stamp["engine_sha256"] is None


def test_a_loaded_book_is_recorded_by_hash(tmp_path):
    book = tmp_path / "book.bin"
    book.write_bytes(b"\x00" * 16)
    state = provenance.book_state(True, book)
    assert state == {"file": "book.bin", "sha256": provenance.file_sha256(str(book))}


def test_evals_stamp_has_no_engine_fields():
    stamp = provenance.evals_run(has_book=False)
    assert stamp["kind"] == "lichess_evals"
    assert "engine" not in stamp and "depth" not in stamp
    assert stamp["book"] is None


def test_commit_is_this_checkout():
    got = provenance.code_commit()
    assert got["commit"] is None or len(got["commit"]) == 40


def test_every_new_run_records_the_classifier_version(tmp_path):
    """W22: the column existed since v10 and nothing wrote it."""
    from zugzwang.core.classification import CLASSIFIER_VERSION
    db = Database(tmp_path / "t.db")
    run = db.save_analysis_run(game_id=_game(db), engine_name="Stockfish", depth=14)
    got = db._conn.execute("SELECT classifier_version FROM analysis_runs WHERE id=?",
                           (run,)).fetchone()[0]
    assert got == CLASSIFIER_VERSION == 8


def test_both_stamps_carry_the_classifier_version(tmp_path):
    from zugzwang.core.classification import CLASSIFIER_VERSION
    e = provenance.engine_run(engine_name="x", engine_path=None, depth=14, has_book=False)
    assert e["classifier_version"] == CLASSIFIER_VERSION
    assert provenance.evals_run(has_book=False)["classifier_version"] == CLASSIFIER_VERSION
