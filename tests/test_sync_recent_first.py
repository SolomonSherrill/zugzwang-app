"""BETA-PUB Q4 (owner, 2026-11-12): a sync works newest first, analyses only each account's
100 most recent games automatically, and leaves the rest to "Analyse more", in a step the
user chooses or all. Before it, the queue ran oldest first and a sync analysed every
pending game — a tester with years of games saw years-old reviews first. These fail on
that code.

The engine is not needed: the runner's per-game analysis is replaced by one that stamps a
complete run and records the order games were taken in, which is what is under test."""

import types

import chess
import pytest

import zugzwang.config as C
from zugzwang.core.database import Database
from tests.runs import mark_complete
from tests.test_sidecar_rpc import sidecar

MOVETEXT = "1. e4 e5 2. Nf3 Nc6 *"


def _game(source: str, n: int) -> types.SimpleNamespace:
    """Game *n* of an account: a higher n is a later game."""
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6"):
        board.push_san(san)
    day = f"{2020 + n // 300}-{1 + (n // 25) % 12:02d}-{1 + n % 25:02d}T{n % 24:02d}:00:00+00:00"
    return types.SimpleNamespace(
        played_at=day, player_color="white", result="*", termination="",
        move_count=4, pgn=f'[Event "{source}{n}"]\n[Result "*"]\n\n{MOVETEXT}',
        final_fen=board.fen(), opening_eco=None, opening_name=None,
        external_id=f"{source}-{n:04d}", not_owner=False,
    )


def _save(db: Database, source: str, g) -> int:
    return db.save_game(
        played_at=g.played_at, player_color=g.player_color, skill_level=0,
        result=g.result, termination=g.termination, move_count=g.move_count, pgn=g.pgn,
        final_fen=g.final_fen, source=source, external_id=g.external_id)


def _analysed(db: Database, game_id: int, depth: int = 14) -> None:
    mark_complete(db, db.save_analysis_run(game_id=game_id, engine_name="Stockfish",
                                           depth=depth))


@pytest.fixture
def runner(monkeypatch):
    """A SyncRunner whose per-game analysis stamps a complete depth-14 run and logs the
    game; `runner.taken` is the order games were analysed in."""
    monkeypatch.setattr(sidecar, "_emit", lambda *a, **k: None)
    r = sidecar.SyncRunner(lambda fn: fn(), sidecar.EngineBudget(cores=1, idle_ceiling=1))
    r.taken = []

    def fake(db, openings, rec):
        r.taken.append(rec.external_id)
        _analysed(db, rec.id)
        return True
    r._analyze_from_evals = fake
    yield r
    r._quit_engine()


def _fetcher(games):
    return lambda username, usernames=None, openings=None: list(games)


# ── the query ────────────────────────────────────────────────────────────────

def test_pending_games_come_newest_first(tmp_path):
    db = Database(tmp_path / "z.db")
    for n in (3, 1, 7, 5):
        _save(db, "chesscom", _game("chesscom", n))
    assert [g.external_id for g in db.games_pending_analysis("chesscom", 14)] == [
        "chesscom-0007", "chesscom-0005", "chesscom-0003", "chesscom-0001"]


def test_the_recent_window_counts_analysed_games_too(tmp_path):
    """The window is the account's N most recent games, analysed or not: with the newest
    two analysed, a window of 3 leaves one game to do, not three."""
    db = Database(tmp_path / "z.db")
    ids = {n: _save(db, "lichess", _game("lichess", n)) for n in range(6)}
    _analysed(db, ids[5])
    _analysed(db, ids[4])
    assert [g.external_id for g in db.games_pending_analysis("lichess", 14, recent=3)] == [
        "lichess-0003"]
    assert [g.external_id for g in db.games_pending_analysis("lichess", 14, limit=2)] == [
        "lichess-0003", "lichess-0002"]


# ── sync ─────────────────────────────────────────────────────────────────────

def test_a_first_sync_analyses_the_100_most_recent_newest_first(tmp_path, runner, monkeypatch):
    assert C.SYNC_AUTO_ANALYSE_RECENT == 100
    games = [_game("chesscom", n) for n in range(130)]
    monkeypatch.setitem(sidecar.SyncRunner._FETCHERS, "chesscom", _fetcher(games))
    db = Database(tmp_path / "z.db")
    new, analysed = runner._sync_source(db, None, "chesscom", "someone", ["someone"], 14)
    assert (new, analysed) == (130, 100)
    assert runner.taken == [f"chesscom-{n:04d}" for n in range(129, 29, -1)]
    left = db.games_pending_analysis("chesscom", 14)
    assert [g.external_id for g in left] == [f"chesscom-{n:04d}" for n in range(29, -1, -1)]


def test_a_library_already_analysed_re_runs_nothing(tmp_path, runner, monkeypatch):
    """The owner's case: his recent games are analysed, so a sync re-runs nothing analysed. An old
    unanalysed game outside the window but inside the analysed span (a gap) is analysed by the next
    sync (FIX-B8 D, owner note 12: before, it stayed pending after every sync)."""
    db = Database(tmp_path / "z.db")
    games = [_game("chesscom", n) for n in range(150)]
    for g in games:
        gid = _save(db, "chesscom", g)
        if g.external_id != "chesscom-0003":           # one old game never analysed
            _analysed(db, gid)
    monkeypatch.setitem(sidecar.SyncRunner._FETCHERS, "chesscom", _fetcher(games))
    assert runner._sync_source(db, None, "chesscom", "x", ["x"], 14) == (0, 1)
    assert runner.taken == ["chesscom-0003"]           # the gap, and nothing analysed again
    # Two new games played since: those, and only those, are analysed.
    newer = games + [_game("chesscom", 150), _game("chesscom", 151)]
    monkeypatch.setitem(sidecar.SyncRunner._FETCHERS, "chesscom", _fetcher(newer))
    assert runner._sync_source(db, None, "chesscom", "x", ["x"], 14) == (2, 2)
    assert runner.taken == ["chesscom-0003", "chesscom-0151", "chesscom-0150"]
    assert db.games_pending_analysis("chesscom", 14) == []


def test_note12_games_a_later_sync_brings_in_inside_the_analysed_span_are_analysed(tmp_path, runner, monkeypatch):
    """FIX-B8 D, owner note 12 (reproduced on a copy of the 2026-11-25 backup: 9 Chess.com games from March to
    September, synced after the newest 100 had moved on, never analysed by any sync, so Settings kept saying
    "9 games from Chess.com waiting for analysis"). A first sync of 130 games analyses the newest 100 (Q4); a
    second sync with nothing new leaves the 30 older ones for "Analyse more" (Q4's backlog: older than every
    analysed game); a third brings in 9 games dated among the analysed ones, and those are analysed."""
    db = Database(tmp_path / "z.db")
    games = [_game("chesscom", n) for n in range(0, 260, 2)]           # 130 games
    monkeypatch.setitem(sidecar.SyncRunner._FETCHERS, "chesscom", _fetcher(games))
    assert runner._sync_source(db, None, "chesscom", "x", ["x"], 14) == (130, 100)
    runner.taken.clear()
    assert runner._sync_source(db, None, "chesscom", "x", ["x"], 14) == (0, 0)
    assert len(db.games_pending_analysis("chesscom", 14)) == 30
    late = [_game("chesscom", n) for n in range(61, 79, 2)]              # 9 games among the analysed ones
    monkeypatch.setitem(sidecar.SyncRunner._FETCHERS, "chesscom", _fetcher(games + late))
    assert runner._sync_source(db, None, "chesscom", "x", ["x"], 14) == (9, 9)
    assert runner.taken == [g.external_id for g in reversed(late)]
    assert len(db.games_pending_analysis("chesscom", 14)) == 30          # only Q4's backlog is left


# ── Analyse more ─────────────────────────────────────────────────────────────

def _two_accounts(tmp_path) -> Database:
    db = Database(tmp_path / "z.db")
    for n in range(0, 40, 2):
        _save(db, "lichess", _game("lichess", n))
    for n in range(1, 40, 2):
        _save(db, "chesscom", _game("chesscom", n))
    return db


def test_analyse_more_in_a_step_takes_the_newest_across_accounts(tmp_path, runner):
    _two_accounts(tmp_path).close()
    runner._run_analyze(["lichess", "chesscom"], tmp_path / "z.db", 14, 5)
    assert runner.taken == ["lichess-0038", "lichess-0036",           # lichess is run first,
                            "chesscom-0039", "chesscom-0037", "chesscom-0035"]  # each newest first
    db = Database(tmp_path / "z.db")
    left = {g.external_id for s in ("lichess", "chesscom")
            for g in db.games_pending_analysis(s, 14)}
    assert len(left) == 35
    assert {"chesscom-0039", "lichess-0038", "chesscom-0037", "lichess-0036",
            "chesscom-0035"}.isdisjoint(left)


def test_analyse_more_all_takes_every_pending_game(tmp_path, runner):
    _two_accounts(tmp_path).close()
    runner._run_analyze(["lichess", "chesscom"], tmp_path / "z.db", 14, None)
    assert len(runner.taken) == 40
    db = Database(tmp_path / "z.db")
    assert db.games_pending_analysis("lichess", 14) == []
    assert db.games_pending_analysis("chesscom", 14) == []


def test_the_rpc_passes_the_step(tmp_path, monkeypatch):
    seen = {}

    class FakeSync:
        def running(self):
            return False

        def start_analyze(self, **kw):
            seen.update(kw)
    server = object.__new__(sidecar.Server)
    server._sync = FakeSync()
    server._db_path = tmp_path / "z.db"
    assert server.rpc_analyze_pending(count=50)["count"] == 50
    assert seen["count"] == 50 and seen["sources"] == ["lichess", "chesscom"]
    server.rpc_analyze_pending(source="lichess")
    assert seen["count"] is None and seen["sources"] == ["lichess"]
    with pytest.raises(RuntimeError):
        server.rpc_analyze_pending(count=0)
