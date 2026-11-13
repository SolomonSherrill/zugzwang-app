"""Dedup, external-id extraction, and migration-idempotency tests
(Phase 2, priority 2 — R1).

Covers the platform-sync dedup contract: external_id extraction from PGN
headers, the (source, external_id) unique index, existing_external_ids scoping,
and that re-opening a DB re-runs all migrations without error.
"""

import sqlite3

import pytest

from zugzwang.core.database import Database
from zugzwang.core.import_pgn import _external_id


# ── external_id extraction (import_pgn) ──────────────────────────────────────

def test_external_id_lichess_site():
    assert _external_id({"Site": "https://lichess.org/abcd1234"}) == "abcd1234"


def test_external_id_chesscom_link():
    assert (
        _external_id({"Link": "https://www.chess.com/game/live/9988776655"})
        == "9988776655"
    )


def test_external_id_strips_trailing_slash():
    assert _external_id({"Site": "https://lichess.org/abcd1234/"}) == "abcd1234"


def test_external_id_strips_query_and_fragment():
    assert _external_id({"Site": "https://lichess.org/abcd1234?foo=1"}) == "abcd1234"
    assert _external_id({"Site": "https://lichess.org/abcd1234#move-7"}) == "abcd1234"


def test_external_id_none_for_unknown_url():
    assert _external_id({"Site": "https://example.com/whatever"}) is None


def test_external_id_none_for_empty_headers():
    assert _external_id({}) is None


def test_external_id_site_preferred_over_link():
    # Lichess Site is checked before Chess.com Link.
    headers = {
        "Site": "https://lichess.org/aaaa1111",
        "Link": "https://www.chess.com/game/live/2222",
    }
    assert _external_id(headers) == "aaaa1111"


@pytest.mark.xfail(
    reason="TEST REVEALS BUG: _external_id does not strip a colour suffix despite "
    "its docstring claiming awareness of one. A URL ending '/white' or '/black' "
    "(as Lichess web URLs do) yields the literal 'black'/'white' as the game id. "
    "Two different black games then collide on (source, external_id) and the "
    "second is rejected by the unique index / IntegrityError.",
    strict=True,
)
def test_external_id_strips_color_suffix():
    assert _external_id({"Site": "https://lichess.org/abcd1234/black"}) == "abcd1234"


# ── dedup unique index ───────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _save(db, **overrides):
    kwargs = dict(
        played_at="2026-05-26T12:00:00+00:00",
        player_color="white",
        skill_level=10,
        result="1-0",
        termination="checkmate",
        move_count=40,
        pgn='[Event "Zugzwang"]\n\n1. e4 e5 *',
        final_fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    )
    kwargs.update(overrides)
    return db.save_game(**kwargs)


def test_duplicate_external_id_same_source_rejected(db):
    _save(db, source="lichess", external_id="dup1")
    with pytest.raises(sqlite3.IntegrityError):
        _save(db, source="lichess", external_id="dup1")


def test_same_external_id_different_source_allowed(db):
    _save(db, source="lichess", external_id="shared")
    _save(db, source="chesscom", external_id="shared")
    assert len(db.list_games()) == 2


def test_null_external_id_allows_duplicates(db):
    # Locally-played games have no external_id; many such rows must coexist.
    _save(db, source="local", external_id=None)
    _save(db, source="local", external_id=None)
    assert len(db.list_games()) == 2


def test_existing_external_ids_scoped_by_source(db):
    _save(db, source="lichess", external_id="L1")
    _save(db, source="lichess", external_id="L2")
    _save(db, source="chesscom", external_id="C1")
    _save(db, source="local", external_id=None)
    assert db.existing_external_ids("lichess") == {"L1", "L2"}
    assert db.existing_external_ids("chesscom") == {"C1"}
    assert db.existing_external_ids("local") == set()


# ── migration idempotency ────────────────────────────────────────────────────

def _columns(db, table):
    return {r[1] for r in db._conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_reopening_db_reruns_migrations_cleanly(tmp_path):
    path = tmp_path / "reopen.db"
    Database(path)
    # Second open must re-run every _migrate_vN without error (all column-guarded).
    db2 = Database(path)
    cols = _columns(db2, "games")
    assert {"external_id", "source", "speed", "rated"} <= cols


def test_migrations_added_all_expected_columns(db):
    games_cols = _columns(db, "games")
    assert {
        "external_id", "source", "speed", "rated", "opening_eco", "opening_name",
    } <= games_cols
    runs_cols = _columns(db, "analysis_runs")
    assert {"white_accuracy", "black_accuracy"} <= runs_cols
    ma_cols = _columns(db, "move_analyses")
    assert "lines_json" in ma_cols


def test_unique_index_exists(db):
    idx = {
        r[0]
        for r in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_games_external" in idx
