"""BETA item 6: a database from an older build opens in this one.

Migrations are additive and probe `PRAGMA table_info` themselves (CLAUDE.md, SQLite), so
a tester's database written by beta.1 must open in beta.N. This walks the oldest shapes the
repository can produce forward: fixtures written by its first commit, ca20aa7 (see
`fixtures/make_old_schema_fixtures.py`) — its bare schema (pre-v3) and its full v9 database.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest

from zugzwang.core import relabel
from zugzwang.core.classification import CLASSIFIER_VERSION
from zugzwang.core.database import SCHEMA_VERSION, Database

FIX = Path(__file__).parent / "fixtures"
OLD = ["schema_base_ca20aa7.db", "schema_v9_ca20aa7.db"]


def _columns(db: Path) -> dict[str, list[str]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'puzzle_themes_fts_%'")]
        return {t: sorted(r[1] for r in con.execute(f"PRAGMA table_info({t})")) for t in tables}
    finally:
        con.close()


@pytest.fixture
def fresh_columns(tmp_path):
    Database(tmp_path / "fresh.db").close()
    return _columns(tmp_path / "fresh.db")


@pytest.mark.parametrize("name", OLD)
def test_old_database_walks_forward(tmp_path, name, fresh_columns):
    db = tmp_path / name
    shutil.copy(FIX / name, db)
    assert _columns(db) != fresh_columns               # it really is old

    Database(db).close()
    assert _columns(db) == fresh_columns               # every table, every column

    con = sqlite3.connect(db)
    assert con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] \
        == str(SCHEMA_VERSION)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    g = con.execute("SELECT result, termination, opening_name, move_count, source "
                    "FROM games").fetchall()
    assert g == [("1-0", "checkmate", "Bishop's Opening", 7, "local")]
    assert [r[0] for r in con.execute(
        "SELECT played_uci FROM move_analyses ORDER BY ply")] == \
        ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]
    # The one non-additive step, measured here: v5 DROPS a pre-v5 `puzzles` stub (no
    # `rating_deviation`) and rebuilds it empty — the puzzles are re-imported from the
    # CSV. The rating row survives. No beta database can predate v5.
    want = [] if name == "schema_base_ca20aa7.db" else [("00008", 1913)]
    assert con.execute("SELECT id, rating FROM puzzles").fetchall() == want
    rating = [(1234.5,)] if name == "schema_base_ca20aa7.db" else []   # v9: none was written
    assert con.execute("SELECT rating FROM puzzle_rating").fetchall() == rating
    con.close()

    # Readable through today's API, and the run counts as complete (v14's backfill: it
    # stores exactly its PGN's plies).
    d = Database(db)
    try:
        run = d.load_latest_run(1)
        assert run is not None
        assert len(d.load_move_analyses(run.id)) == 7
        assert d.audit_run_completeness() == []
    finally:
        d.close()


@pytest.mark.parametrize("name", OLD)
def test_reopening_is_idempotent(tmp_path, name):
    db = tmp_path / name
    shutil.copy(FIX / name, db)
    Database(db).close()
    once = _columns(db)
    Database(db).close()
    assert _columns(db) == once


@pytest.mark.parametrize("name", OLD)
def test_walked_database_then_relabels(tmp_path, name):
    """The whole update path on the oldest data: migrations, then relabel on update. Its
    run predates classifier versioning (NULL), so the update relabels it."""
    db = tmp_path / name
    shutil.copy(FIX / name, db)
    Database(db).close()
    out = relabel.relabel_stale(db)
    assert out["runs"] == 1 and out["unstamped"] == 0 and out["integrity"] == "ok"
    con = sqlite3.connect(db)
    assert con.execute("SELECT classifier_version FROM analysis_runs").fetchone()[0] \
        == CLASSIFIER_VERSION
    con.close()
