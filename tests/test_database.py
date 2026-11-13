import sqlite3
import tempfile
from pathlib import Path

import pytest

import zugzwang.config as C
from zugzwang.core.database import SCHEMA_VERSION, Database, GameRecord

from tests.runs import mark_complete  # noqa: E402


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


def _sample(db, **overrides):
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


def test_save_and_list(db):
    gid = _sample(db)
    assert gid == 1

    games = db.list_games()
    assert len(games) == 1
    g = games[0]
    assert g.result == "1-0"
    assert g.termination == "checkmate"
    assert g.skill_level == 10
    assert g.player_color == "white"


def test_get_game(db):
    gid = _sample(db)
    g = db.get_game(gid)
    assert g is not None
    assert g.id == gid
    assert "Zugzwang" in g.pgn


def test_multiple_games_order(db):
    _sample(db, played_at="2026-01-01T00:00:00+00:00", result="0-1")
    _sample(db, played_at="2026-06-01T00:00:00+00:00", result="1-0")
    games = db.list_games()
    assert games[0].result == "1-0"   # newest first


def test_schema_tables(db):
    conn = sqlite3.connect(str(db._conn.execute("PRAGMA database_list").fetchone()[2]))
    # The database file is at the path used in the fixture; check tables via raw connection
    tables = {
        r[0] for r in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "games" in tables
    assert "analysis_runs" in tables
    assert "puzzles" in tables
    assert "meta" in tables


def test_get_nonexistent(db):
    assert db.get_game(999) is None


# ── Analysis run + move analysis ──────────────────────────────────────────────

from zugzwang.core.database import AnalysisRun, IncompleteRun, MoveAnalysis


def _sample_ma(ply: int, cls: str = "best") -> MoveAnalysis:
    return MoveAnalysis(
        ply=ply,
        fen_before="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        played_uci="e2e4",
        best_uci="e2e4",
        pv_uci="e2e4 e7e5",
        score_before_cp=20,
        score_before_mate=None,
        score_after_cp=20,
        score_after_mate=None,
        second_best_uci="d2d4",
        second_best_cp=18,
        second_best_mate=None,
        classification=cls,
        is_book=False,
    )


def test_save_and_load_analysis_run(db):
    gid = _sample(db)
    run_id = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=18)
    assert run_id == 1
    assert db.load_latest_run(gid) is None          # not the game's until complete

    db.complete_analysis_run(run_id, {}, plies=[_sample_ma(0), _sample_ma(1)])
    run = db.load_latest_run(gid)
    assert run is not None
    assert run.game_id == gid
    assert run.depth == 18


def test_load_latest_run_none_when_empty(db):
    gid = _sample(db)
    assert db.load_latest_run(gid) is None


def test_list_games_with_runs_agrees_with_the_per_game_path(db):
    # The whole point of the JOIN is that it answers exactly what 1 859 calls to
    # `load_latest_run` answered, so that is what it is measured against — over a
    # mix of unanalysed, analysed-without-accuracies, and scored games.
    plain = _sample(db, played_at="2026-01-01T00:00:00+00:00")
    scored = _sample(db, played_at="2026-02-01T00:00:00+00:00")
    unscored = _sample(db, played_at="2026-03-01T00:00:00+00:00")
    run = db.save_analysis_run(game_id=scored, engine_name="Stockfish", depth=18)
    mark_complete(db, run, white_accuracy=91.5, black_accuracy=80.25)
    mark_complete(db, db.save_analysis_run(game_id=unscored, engine_name="Lichess evals",
                                           depth=0))

    rows = db.list_games_with_runs()
    assert [rec.id for rec, _ in rows] == [unscored, scored, plain]  # newest first
    for rec, summary in rows:
        want = db.load_latest_run(rec.id)
        if want is None:
            assert summary is None
        else:
            assert summary is not None
            assert (summary.id, summary.white_accuracy, summary.black_accuracy) == (
                want.id, want.white_accuracy, want.black_accuracy
            )


def test_list_games_with_runs_carries_the_platform_game_id(db):
    # The Games screen's search finds a game by its chess.com / Lichess id
    # (`desktop/src/lib/gameSearch.ts`), and that id reaches it only through this
    # list. Before 2026-11-11 the SELECT omitted it and every record read None.
    platform = _sample(db, source="chesscom", external_id="900000000001",
                       played_at="2026-02-01T00:00:00+00:00")
    local = _sample(db, played_at="2026-01-01T00:00:00+00:00")
    by_id = {rec.id: rec for rec, _ in db.list_games_with_runs()}
    assert by_id[platform].external_id == "900000000001"
    assert by_id[local].external_id is None

    from sidecar.main import _game_dict
    assert _game_dict(by_id[platform])["externalId"] == "900000000001"
    assert _game_dict(by_id[local])["externalId"] is None


def test_list_games_with_runs_distinguishes_no_run_from_no_accuracies(db):
    # `analyzed` is not derivable from the accuracies: a run written before v4
    # added the columns has both as NULL. Collapsing the two would have told the
    # Games screen a v3-era analysed game was never analysed.
    plain = _sample(db, played_at="2026-01-01T00:00:00+00:00")
    unscored = _sample(db, played_at="2026-02-01T00:00:00+00:00")
    mark_complete(db, db.save_analysis_run(game_id=unscored, engine_name="Lichess evals",
                                           depth=0))

    by_id = {rec.id: summary for rec, summary in db.list_games_with_runs()}
    assert by_id[plain] is None
    assert by_id[unscored] is not None
    assert by_id[unscored].white_accuracy is None


def test_list_games_with_runs_picks_the_highest_run_id(db):
    # Completing a run deletes the game's others, so two complete runs for one game
    # only arise in databases that predate that. Inserted directly, because the API
    # cannot produce the state this has to be correct on.
    gid = _sample(db)
    first = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=12)
    mark_complete(db, first, white_accuracy=10.0, black_accuracy=10.0)
    db._conn.execute(
        "INSERT INTO analysis_runs"
        " (game_id, engine_name, depth, created_at, payload_json, white_accuracy,"
        "  completed_at)"
        " VALUES (?, 'Stockfish', 20, '2020-01-01T00:00:00+00:00', '{}', 99.0,"
        "  '2020-01-01T00:00:00+00:00')",
        (gid,),
    )
    db._conn.commit()

    (_, summary), = db.list_games_with_runs()
    assert summary is not None
    assert summary.white_accuracy == 99.0
    assert summary.id == db.load_latest_run(gid).id


def test_list_games_with_runs_honours_limit(db):
    for i in range(3):
        _sample(db, played_at=f"2026-0{i + 1}-01T00:00:00+00:00")
    assert len(db.list_games_with_runs(limit=2)) == 2


def test_analysis_runs_are_indexed_by_game(db):
    # Without this index every reader of `analysis_runs` scans the whole table;
    # `games_pending_analysis` does so once per candidate game.
    plan = db._conn.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM analysis_runs WHERE game_id=1"
        " ORDER BY id DESC LIMIT 1"
    ).fetchall()
    assert any("idx_analysis_runs_game" in str(row[-1]) for row in plan), plan


def test_best_uci_round_trips_as_null(db):
    # "no best move was established" must survive storage as itself, not as the
    # played move and not as `''` — both of which read as an answer.
    gid = _sample(db)
    run_id = db.save_analysis_run(game_id=gid, engine_name="Lichess evals", depth=0)
    ma = _sample_ma(0)
    ma.best_uci = None
    db.save_move_analysis(run_id, ma)
    assert db.load_move_analyses(run_id)[0].best_uci is None


def test_legacy_empty_best_uci_reads_as_null(db):
    # Rows written before the column could hold NULL spell absence `''`. They are
    # normalised on read rather than backfilled, so what is stored stays as
    # whatever wrote it.
    gid = _sample(db)
    run_id = db.save_analysis_run(game_id=gid, engine_name="Lichess evals", depth=0)
    db.save_move_analysis(run_id, _sample_ma(0))
    db._conn.execute("UPDATE move_analyses SET best_uci = '' WHERE run_id = ?", (run_id,))
    assert db.load_move_analyses(run_id)[0].best_uci is None


def test_migration_makes_best_uci_nullable(tmp_path):
    # A database created under the old schema must end up accepting NULL, since
    # the NOT NULL is what forced `''` to exist in the first place.
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        -- The v1 shape, not a one-column stand-in: `_SCHEMA` declares an index on
        -- `analysis_runs(game_id)`, and `CREATE TABLE IF NOT EXISTS` will not add a
        -- column to a table that already exists, so a stub narrower than any real
        -- database fails to open for a reason no real database would.
        CREATE TABLE analysis_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      INTEGER NOT NULL,
            engine_name  TEXT    NOT NULL,
            depth        INTEGER NOT NULL,
            created_at   TEXT    NOT NULL,
            payload_json TEXT    NOT NULL);
        CREATE TABLE move_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
            ply INTEGER NOT NULL, fen_before TEXT NOT NULL,
            played_uci TEXT NOT NULL, best_uci TEXT NOT NULL, pv_uci TEXT NOT NULL,
            score_before_cp INTEGER, score_before_mate INTEGER,
            score_after_cp INTEGER, score_after_mate INTEGER,
            second_best_uci TEXT, second_best_cp INTEGER, second_best_mate INTEGER,
            classification TEXT NOT NULL, is_book INTEGER NOT NULL DEFAULT 0,
            lines_json TEXT, UNIQUE(run_id, ply));
        INSERT INTO analysis_runs
            (id, game_id, engine_name, depth, created_at, payload_json)
        VALUES (1, 1, 'Stockfish', 18, '2026-01-01T00:00:00+00:00', '{}');
        INSERT INTO move_analyses
            (run_id, ply, fen_before, played_uci, best_uci, pv_uci, classification)
        VALUES (1, 0, 'fen', 'e2e4', '', '', 'good');
    """)
    conn.commit()
    conn.close()

    db = Database(path)
    best = next(r for r in db._conn.execute("PRAGMA table_info(move_analyses)")
                if r[1] == "best_uci")
    assert not best[3], "best_uci should no longer be NOT NULL"
    # The pre-existing row is carried across untouched, `''` and all.
    assert db._conn.execute(
        "SELECT best_uci FROM move_analyses").fetchone()[0] == ""


def test_local_game_records_the_ladder_it_was_played_on(db):
    g = db.get_game(_sample(db))
    assert g.ladder_version == C.ENGINE_LADDER_VERSION


def test_synced_game_has_no_ladder_version(db):
    # skill_level is a placeholder 0 for a game the app did not configure, so
    # stamping a ladder onto it would claim something about a human opponent.
    for source in ("lichess", "chesscom", "imported"):
        g = db.get_game(_sample(db, source=source, skill_level=0))
        assert g.ladder_version is None, source


def test_migration_adds_ladder_version_without_backfilling(tmp_path):
    # A game stored before the ladder was recorded must read as NULL, not as
    # today's version: its level number was chosen on a ladder we cannot name.
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            played_at TEXT NOT NULL, player_color TEXT NOT NULL,
            skill_level INTEGER NOT NULL, result TEXT NOT NULL,
            termination TEXT NOT NULL, move_count INTEGER NOT NULL,
            opening_eco TEXT, opening_name TEXT,
            pgn TEXT NOT NULL, final_fen TEXT NOT NULL);
        INSERT INTO games
            (played_at, player_color, skill_level, result, termination,
             move_count, pgn, final_fen)
        VALUES ('2026-01-01T00:00:00+00:00', 'white', 10, '1-0', 'checkmate',
                40, '[Event "Zugzwang"]\n\n1. e4 *', 'fen');
    """)
    conn.commit()
    conn.close()

    db = Database(path)
    assert db.get_game(1).ladder_version is None
    # And a game saved after the migration is stamped, so the two are telling
    # apart exactly the games whose level numbers are not comparable.
    assert db.get_game(_sample(db)).ladder_version == C.ENGINE_LADDER_VERSION


def _meta(path, key):
    conn = sqlite3.connect(path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row and row[0]


def test_schema_version_is_stamped_to_the_version_applied(tmp_path):
    path = tmp_path / "fresh.db"
    Database(path)
    assert _meta(path, "schema_version") == str(SCHEMA_VERSION)


def test_schema_version_overwrites_a_stale_value(tmp_path):
    # The live database read '1' — the first value it was ever given, kept
    # because the old stamp was INSERT OR IGNORE. Opening it must correct that,
    # otherwise the field records when a database was created rather than what
    # schema it has.
    path = tmp_path / "stale.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '1');
        INSERT INTO meta (key, value) VALUES ('puzzles_count', '5259176');
    """)
    conn.commit()
    conn.close()

    Database(path)
    assert _meta(path, "schema_version") == str(SCHEMA_VERSION)
    # Only that key: the stamp must not disturb its neighbours in meta.
    assert _meta(path, "puzzles_count") == "5259176"


def test_save_and_load_move_analysis(db):
    gid = _sample(db)
    run_id = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=18)

    ma0 = _sample_ma(0, "best")
    ma1 = _sample_ma(1, "blunder")
    db.save_move_analysis(run_id, ma0)
    db.save_move_analysis(run_id, ma1)

    rows = db.load_move_analyses(run_id)
    assert len(rows) == 2
    assert rows[0].ply == 0
    assert rows[0].classification == "best"
    assert rows[1].ply == 1
    assert rows[1].classification == "blunder"


def test_replace_run_on_re_analyse(db):
    gid = _sample(db)
    run_id_1 = db.save_analysis_run(game_id=gid, engine_name="SF", depth=18)
    db.complete_analysis_run(run_id_1, {}, plies=[_sample_ma(0, "best"), _sample_ma(1)])

    # Re-analyse replaces the old run — when it completes, not when it starts, so a
    # re-analysis that never finishes leaves the old one in place (VAL-DEATH).
    run_id_2 = db.save_analysis_run(game_id=gid, engine_name="SF", depth=20)
    db.save_move_analysis(run_id_2, _sample_ma(0, "excellent"))
    assert db.load_latest_run(gid).id == run_id_1

    db.complete_analysis_run(run_id_2, {}, plies=[_sample_ma(1)])
    run = db.load_latest_run(gid)
    assert run.id == run_id_2
    rows = db.load_move_analyses(run.id)
    assert rows[0].classification == "excellent"
    assert [r[0] for r in db._conn.execute("SELECT id FROM analysis_runs")] == [run_id_2]


def test_a_run_missing_a_ply_cannot_complete(db):
    gid = _sample(db)                                   # 1. e4 e5 — two plies
    run = db.save_analysis_run(game_id=gid, engine_name="SF", depth=10)
    with pytest.raises(IncompleteRun):
        db.complete_analysis_run(run, {}, plies=[_sample_ma(0)])
    assert db.load_latest_run(gid) is None
    assert db.load_move_analyses(run) == []             # the refused write is rolled back
    assert [a.run_id for a in db.audit_run_completeness()] == [run]
    assert not db.audit_run_completeness()[0].completed


def test_re_analyse_overwrites_index_sourced_scores(db):
    # Owner ruling (F4b-index, 2026-10-22): opening a game never re-scores plies
    # scored from the opening index, but an explicit "Re-analyse" overwrites them,
    # because it asks for the app's own analysis. It does so by replacing the run;
    # the new rows carry score_source NULL (the run's own engine).
    gid = _sample(db)
    run_id_1 = db.save_analysis_run(game_id=gid, engine_name="SF", depth=10)
    db.save_move_analysis(run_id_1, _sample_ma(0, "book"))
    db._conn.execute(
        "UPDATE move_analyses SET score_source = 'lichess-index-v1' WHERE run_id = ?",
        (run_id_1,),
    )

    run_id_2 = db.save_analysis_run(game_id=gid, engine_name="SF", depth=14)
    db.save_move_analysis(run_id_2, _sample_ma(0, "best"))

    sources = [r[0] for r in db._conn.execute("SELECT score_source FROM move_analyses")]
    assert sources == [None]


def test_schema_has_move_analyses_table(db):
    tables = {
        r[0] for r in db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "move_analyses" in tables


def test_update_game_opening(db):
    gid = _sample(db)
    db.update_game_opening(gid, "B20", "Sicilian Defense")
    rec = db.get_game(gid)
    assert rec.opening_eco == "B20"
    assert rec.opening_name == "Sicilian Defense"


def test_update_game_opening_does_not_overwrite(db):
    gid = _sample(db, opening_eco="A00", opening_name="Already Set")
    db.update_game_opening(gid, "B20", "Sicilian Defense")
    rec = db.get_game(gid)
    # Should not overwrite — the UPDATE only touches rows where eco IS NULL
    assert rec.opening_eco == "A00"


def _pending_ids(db, source, min_depth=0):
    return [g.id for g in db.games_pending_analysis(source, min_depth)]


def test_pending_analysis_upgrade_only(db):
    gid = _sample(db, source="lichess", external_id="abc")

    # Unanalyzed: pending at any depth.
    assert _pending_ids(db, "lichess", 10) == [gid]

    # Analyzed at depth 14: a deeper request re-queues it, a shallower/equal
    # request skips it (don't downgrade existing work).
    mark_complete(db, db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=14))
    assert _pending_ids(db, "lichess", 18) == [gid]   # upgrade
    assert _pending_ids(db, "lichess", 14) == []      # equal → skip
    assert _pending_ids(db, "lichess", 10) == []      # downgrade → skip
    assert _pending_ids(db, "lichess", 0) == []       # legacy "any run counts"


def test_pending_analysis_exempts_lichess_evals(db):
    gid = _sample(db, source="lichess", external_id="def")

    # Lichess cloud evals store depth 0 but are deeper than any local search —
    # an engine-depth request must never re-queue them.
    mark_complete(db, db.save_analysis_run(game_id=gid, engine_name="Lichess evals",
                                           depth=0))
    assert _pending_ids(db, "lichess", 18) == []
    assert _pending_ids(db, "lichess", 10) == []


def _synced(db, white, black, color):
    pgn = f'[Event "Live Chess"]\n[White "{white}"]\n[Black "{black}"]\n\n1. e4 e5 *'
    return _sample(db, pgn=pgn, player_color=color, source="chesscom")


def test_repair_player_colors_fixes_a_mismatch(db):
    gid = _synced(db, "opp", "me2", "white")
    assert db.repair_player_colors(["me2"]) == 1
    assert db.get_game(gid).player_color == "black"


def test_repair_player_colors_leaves_unmatched_games_alone(db):
    # W11: a game from another of the user's accounts matches no configured
    # handle. Repair used to reset it to the import default, white.
    gid = _synced(db, "opp", "other_account", "black")
    assert db.repair_player_colors(["me2"]) == 0
    assert db.get_game(gid).player_color == "black"


# ── attribution (FIXPLAN O5) ─────────────────────────────────────────────────

from zugzwang.core.database import AttributionPending  # noqa: E402

_CHESSCOM = dict(source="chesscom", result="1-0")


def _with_run(db, gid, accuracy=80.0):
    run = db.save_analysis_run(game_id=gid, engine_name="Stockfish", depth=10)
    mark_complete(db, run, white_accuracy=accuracy, black_accuracy=accuracy)


def test_the_attribution_migration_does_not_run_on_open(tmp_path):
    """The owner ruled it does not run unattended: every other migration runs on
    every open, this one only when called."""
    db = Database(tmp_path / "a.db")
    assert not db.attribution_migrated
    db.close()
    assert not Database(tmp_path / "a.db").attribution_migrated


def test_an_unattributable_game_is_refused_before_the_migration(db):
    with pytest.raises(AttributionPending):
        _sample(db, player_color=None, source="imported")
    with pytest.raises(AttributionPending):
        _sample(db, player_color=None, source="imported", not_owner=True)
    assert db.list_games() == []


def test_the_migration_keeps_every_row_and_the_cascade(tmp_path):
    db = Database(tmp_path / "m.db")
    ids = [_sample(db, external_id=f"x{i}", **_CHESSCOM) for i in range(3)]
    for gid in ids:
        _with_run(db, gid)
    before = [tuple(dict(r).items()) for r in db._conn.execute("SELECT * FROM games ORDER BY id")]
    assert db.migrate_attribution() is True
    assert db.migrate_attribution() is False          # idempotent
    after = [tuple((k, v) for k, v in dict(r).items() if k != "not_owner")
             for r in db._conn.execute("SELECT * FROM games ORDER BY id")]
    assert after == before
    assert db._conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.delete_game(ids[0]) == 1               # cascade still wired to games
    assert db._conn.execute(
        "SELECT COUNT(*) FROM analysis_runs WHERE game_id = ?", (ids[0],)).fetchone()[0] == 0
    db.close()
    assert Database(tmp_path / "m.db").attribution_migrated   # survives a reopen


def test_a_not_owner_game_is_excluded_from_insights_and_accuracy(tmp_path):
    """Game 41's case (`someone_else` vs `another_player`): stored, marked, and in
    no aggregate about the user — not in the counts, not in the accuracy trend."""
    db = Database(tmp_path / "n.db")
    db.migrate_attribution()
    mine = _sample(db, external_id="mine", **_CHESSCOM)
    theirs = _sample(db, player_color=None, not_owner=True, external_id="theirs", **_CHESSCOM)
    unknown = _sample(db, player_color=None, external_id="unknown", **_CHESSCOM)
    for gid in (mine, theirs, unknown):
        _with_run(db, gid)
    assert db.get_game(theirs).not_owner == 1
    overview = db.insights_overview()
    assert (overview["total"], overview["analyzed"]) == (1, 1)
    assert [r[0] for r in db.insights_accuracy_trend()] == [mine]
    assert db.games_pending_analysis("chesscom") == []   # not re-queued either


def test_repair_marks_a_not_owner_game_and_finds_a_former_handle(tmp_path, monkeypatch):
    from zugzwang.core import handles
    monkeypatch.setattr(handles, "former_handles", lambda: {"new_handle": ["old_handle"]})
    db = Database(tmp_path / "r.db")
    db.migrate_attribution()
    pgn = '[White "{w}"]\n[Black "{b}"]\n\n1. e4 e5 *'
    former = _sample(db, player_color="white", source="imported",
                     pgn=pgn.format(w="some_opponent", b="old_handle"))
    foreign = _sample(db, player_color="white", source="imported",
                      pgn=pgn.format(w="someone_else", b="another_player"))
    assert db.repair_player_colors(["new_handle"]) == 2
    assert db.get_game(former).player_color == "black"
    got = db.get_game(foreign)
    assert (got.player_color, got.not_owner) == (None, 1)
