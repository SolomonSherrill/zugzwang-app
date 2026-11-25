"""VAL-DEATH: engine death is an error, never an empty ply (approved 2026-10-22).

Every path `review/scratch/engine_death.py` measured is here, killed mid-job the way that
probe killed them: a real SIGKILL of the real Stockfish process. The kill is triggered at
a chosen position by wrapping `SimpleEngine.popen_uci` — the one call every runner opens
its engine with, before and after the fix — so these tests drive the runners through their
own entry points and assert on events and on the database, not on internals.

  * Re-analyse — before: 90 of 95 plies came out empty and the run reported done.
  * Sync — before: every remaining game saved as analysed with 0 plies, in seconds.
  * FEN path and Try it — before: every later request failed until restart.
  * Live play — before: no move and no error; the Play screen waited forever.

Each kill test was run against the pre-fix code and fails there (FIXPLAN VAL-DEATH).
Needs the bundled Stockfish; skipped without it.
"""

import importlib.util
import os
import queue
import signal

# Windows has no SIGKILL; os.kill there with SIGTERM is TerminateProcess, the same
# unannounced death (BETA item 7: these tests now run on the Windows runner).
KILL = getattr(signal, "SIGKILL", signal.SIGTERM)
import time
from pathlib import Path

import chess
import chess.engine
import pytest

from zugzwang.core.database import Database
from zugzwang.core.engine_locator import find_stockfish

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "zugzwang_sidecar_main_death", _REPO / "sidecar" / "main.py"
)
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

DEPTH = 8

#: Short games with distinct openings, so a position after any move is unique to its game.
GAMES = {
    "9000001": "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 1-0",
    "9000002": "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 0-1",
    "9000003": "1. c4 e5 2. Nc3 Nf6 3. Nf3 Nc6 4. g3 d5 5. cxd5 Nxd5 1/2-1/2",
    "9000004": "1. Nf3 d5 2. g3 Nf6 3. Bg2 e6 4. O-O Be7 5. d3 O-O 1-0",
    "9000005": "1. b3 e5 2. Bb2 Nc6 3. e3 d5 4. Bb5 Bd6 5. f4 Qh4+ 0-1",
}


@pytest.fixture(autouse=True)
def _standard_depth_8(monkeypatch):
    """RUNS-DEPTH: only a run at the standard depth satisfies a sync. These tests search at
    depth 8 for speed, so the standard depth is 8 here (production: 14)."""
    import zugzwang.config as _cfg
    monkeypatch.setattr(_cfg, "ANALYSIS_STANDARD_DEPTH", 8)


def _fen_at(movetext: str, ply: int) -> str:
    """The position before ply *ply* (0-based) of a game."""
    board = chess.Board()
    for san in [t for t in movetext.split() if not t[0].isdigit()][:ply]:
        board.push_san(san)
    return board.fen()


@pytest.fixture(scope="module")
def stockfish():
    path = find_stockfish()
    if path is None:
        pytest.skip("Stockfish not found")
    return str(path)


@pytest.fixture
def events(monkeypatch):
    out: list[tuple[str, dict]] = []
    monkeypatch.setattr(sidecar, "_emit", lambda ev, data: out.append((ev, data)))
    return out


class Killer:
    """SIGKILLs an engine the moment it is asked about one of *fens*, at most *times*
    times in all (None: every time). The search then runs on the dead process, so what
    follows is the genuine death path, exit code included."""

    def __init__(self, monkeypatch, fens, times=1):
        self.fens = set(fens)
        self.remaining = times
        self.kills: list[str] = []
        self.configured: list[tuple[int, dict]] = []   # (engine #, options)
        self.opened = 0
        real = chess.engine.SimpleEngine.popen_uci

        def popen(*args, **kwargs):
            engine = real(*args, **kwargs)
            self.opened += 1
            number = self.opened
            for name in ("analyse", "analysis", "play"):
                setattr(engine, name, self._wrap(engine, getattr(engine, name)))
            configure = engine.configure

            def recording_configure(options, *a, **k):
                self.configured.append((number, dict(options)))
                return configure(options, *a, **k)
            engine.configure = recording_configure
            return engine
        monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", popen)

    def _wrap(self, engine, method):
        def wrapped(board, *args, **kwargs):
            if board.fen() in self.fens and (self.remaining is None or self.remaining > 0):
                if self.remaining is not None:
                    self.remaining -= 1
                os.kill(engine.transport.get_pid(), KILL)
                self.kills.append(board.fen())
            return method(board, *args, **kwargs)
        return wrapped


def _save_games(db, ids):
    gids = {}
    for n, ext in enumerate(ids):
        movetext = GAMES[ext]
        gids[ext] = db.save_game(
            played_at=f"2026-10-0{n + 1}T12:00:00+00:00", player_color="white",
            skill_level=0, result=movetext.split()[-1], termination="resignation",
            move_count=len([t for t in movetext.split() if not t[0].isdigit()]),
            pgn=f'[Event "t"]\n[White "me"]\n[Black "opp"]\n\n{movetext}',
            final_fen="x", source="chesscom", external_id=ext,
        )
    return gids


def _plies(db, run_id):
    return db._conn.execute(
        "SELECT COUNT(*) FROM move_analyses WHERE run_id = ?", (run_id,)).fetchone()[0]


def _runs(db, gid):
    """(id, stored plies, accuracy written) for every run of a game."""
    return [(rid, _plies(db, rid), acc is not None) for rid, acc in db._conn.execute(
        "SELECT id, white_accuracy FROM analysis_runs WHERE game_id = ? ORDER BY id",
        (gid,))]


def _failures(db):
    return db._conn.execute(
        "SELECT context, external_id, ply, fen, engine FROM engine_failures").fetchall()


# ── Re-analyse ────────────────────────────────────────────────────────────────

def _reanalyse(server, inbox, events, gid, timeout=60):
    mark = len(events)
    run_id = server.rpc_analyze_game(gid, depth=DEPTH)["runId"]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            inbox.get(timeout=0.05)()
        except queue.Empty:
            pass
        if any(ev in ("analysis_done", "analysis_error", "analysis_cancelled")
               for ev, _ in events[mark:]):
            break
    while not inbox.empty():
        inbox.get()()
    return run_id, [ev for ev, _ in events[mark:]]


@pytest.fixture
def reanalyse_server(tmp_path):
    db = Database(tmp_path / "r.db")
    inbox: queue.Queue = queue.Queue()
    server = object.__new__(sidecar.Server)
    server._db = db
    server._openings = None
    server._analysis = sidecar.AnalysisRunner(inbox.put)
    yield server, inbox, db
    server._analysis.shutdown()


def test_reanalyse_survives_one_death_and_stores_every_ply(
        stockfish, monkeypatch, events, reanalyse_server):
    server, inbox, db = reanalyse_server
    ext = "9000001"
    gid = _save_games(db, [ext])[ext]
    killer = Killer(monkeypatch, [_fen_at(GAMES[ext], 4)])

    run_id, kinds = _reanalyse(server, inbox, events, gid)

    assert killer.kills, "the engine was never killed"
    assert "analysis_error" not in kinds
    assert kinds.count("analysis_done") == 1
    plies =[ma.ply for ma in db.load_move_analyses(run_id)]
    assert plies == list(range(10))                       # every ply, none empty
    assert kinds.count("analysis_ply") == 10
    assert db.load_latest_run(gid).id == run_id
    assert db.audit_run_completeness() == []


def test_reanalyse_poison_position_is_an_error_and_keeps_the_previous_run(
        stockfish, monkeypatch, events, reanalyse_server):
    server, inbox, db = reanalyse_server
    ext = "9000002"
    gid = _save_games(db, [ext])[ext]
    poison = _fen_at(GAMES[ext], 5)
    killer = Killer(monkeypatch, [poison], times=0)                 # armed below
    good_run, kinds = _reanalyse(server, inbox, events, gid)       # a clean first run
    assert "analysis_done" in kinds and not killer.kills
    killer.remaining = 2                                            # kills it, and the retry

    run_id, kinds = _reanalyse(server, inbox, events, gid)

    assert "analysis_done" not in kinds                  # never done after a death
    assert len(killer.kills) == 2
    assert kinds[-1] == "analysis_error"
    message = events[-1][1]["message"]
    assert "crashed twice" in message
    assert db.load_latest_run(gid).id == good_run        # the good run is untouched
    assert _plies(db, good_run) == 10
    assert db._conn.execute("SELECT completed_at FROM analysis_runs WHERE id = ?",
                            (run_id,)).fetchone()[0] is None
    ((context, failed_ext, ply, fen, engine),) = _failures(db)
    assert (context, failed_ext, fen) == ("reanalyse", ext, poison)
    assert ply in (4, 5) and engine.startswith("Stockfish")

    # A retry is safe: the engine is back, and the game analyses whole.
    run_id, kinds = _reanalyse(server, inbox, events, gid)
    assert kinds.count("analysis_done") == 1
    assert db.load_latest_run(gid).id == run_id and _plies(db, run_id) == 10
    assert [rid for rid, _, _ in _runs(db, gid)] == [run_id]


# ── Sync ──────────────────────────────────────────────────────────────────────

def _sync(tmp_path, ids):
    db_path = tmp_path / "s.db"
    db = Database(db_path)
    gids = _save_games(db, ids)
    db.close()
    runner = sidecar.SyncRunner(lambda fn: fn(), sidecar.EngineBudget(cores=1, idle_ceiling=1))
    return runner, db_path, gids


def test_sync_survives_one_death_and_saves_every_game_whole(
        stockfish, monkeypatch, events, tmp_path):
    ids = ["9000001", "9000002", "9000003", "9000004"]
    runner, db_path, gids = _sync(tmp_path, ids)
    killer = Killer(monkeypatch, [_fen_at(GAMES["9000002"], 6)])

    runner._run_analyze(["chesscom"], db_path, DEPTH)

    assert killer.kills
    db = Database(db_path)
    for ext in ids:
        (run, stored, scored), = _runs(db, gids[ext])
        assert stored == 10 and scored, (ext, stored)
    assert db.games_pending_analysis("chesscom", DEPTH) == []
    assert db.audit_run_completeness() == []
    assert not [e for e in events if e[0] in ("sync_error", "sync_warning")]


def test_sync_skips_a_poison_game_unsaved_and_carries_on(
        stockfish, monkeypatch, events, tmp_path):
    ids = ["9000001", "9000002", "9000003", "9000004"]
    runner, db_path, gids = _sync(tmp_path, ids)
    poison = _fen_at(GAMES["9000002"], 3)
    killer = Killer(monkeypatch, [poison], times=2)

    runner._run_analyze(["chesscom"], db_path, DEPTH)

    db = Database(db_path)
    assert _runs(db, gids["9000002"]) == []              # skipped, not saved
    assert len(killer.kills) == 2
    for ext in ("9000001", "9000003", "9000004"):        # the run went on
        (_, stored, scored), = _runs(db, gids[ext])
        assert stored == 10 and scored
    assert [g.external_id for g in db.games_pending_analysis("chesscom", DEPTH)] == ["9000002"]
    ((context, failed_ext, ply, fen, engine),) = _failures(db)
    assert (context, failed_ext, fen) == ("sync", "9000002", poison)
    warnings = [d["message"] for e, d in events if e == "sync_warning"]
    assert len(warnings) == 1 and "crashed twice" in warnings[0]
    assert not [e for e in events if e[0] == "sync_error"]


def test_sync_stops_after_repeated_deaths(stockfish, monkeypatch, events, tmp_path):
    ids = list(GAMES)
    runner, db_path, gids = _sync(tmp_path, ids)
    # Every game's position after its first move kills the engine, every time.
    Killer(monkeypatch, [_fen_at(GAMES[ext], 1) for ext in ids], times=None)

    runner._run_analyze(["chesscom"], db_path, DEPTH)

    db = Database(db_path)
    assert db._conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0] == 0
    assert len(db.games_pending_analysis("chesscom", DEPTH)) == len(ids)
    # Two poison games are four deaths, past the limit of three: the rest never start.
    assert len(_failures(db)) == 2
    errors = [d["message"] for e, d in events if e == "sync_error"]
    assert len(errors) == 1 and errors[0].startswith("Stopped: the engine died")
    assert events[-1][0] == "sync_finished"


# ── FEN path and Try it ───────────────────────────────────────────────────────

def _wait(events, pred, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hit = [d for e, d in list(events) if pred(e, d)]
        if hit:
            return hit[0]
        time.sleep(0.02)
    return None


FEN_A = "r1bq1k1r/1pp1b1pp/p2p1p2/2n5/3P4/1B3Q2/PPP1RPPP/RNB3K1 b - - 1 12"
FEN_B = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"


def test_fen_path_reports_a_death_and_the_next_request_works(
        stockfish, monkeypatch, events):
    killer = Killer(monkeypatch, [FEN_A])
    runner = sidecar.FenAnalysisRunner()
    try:
        runner.analyze(FEN_A)
        err = _wait(events, lambda e, d: e == "analysis_error")
        assert killer.kills and err is not None

        runner.analyze(FEN_B)
        ok = _wait(events, lambda e, d: e == "fen_analyzed" and d["fen"] == FEN_B)
        assert ok is not None and ok["bestUci"]          # the next request works
        assert [e for e, _ in events].count("analysis_error") == 1
        assert "restarted" in err["message"]
        assert err["fen"] == FEN_A    # a live position's failure names it (UI-BUILD-3 C)
    finally:
        runner.shutdown()


def test_try_it_reports_a_death_and_the_next_judgement_works(
        stockfish, monkeypatch, events):
    killer = Killer(monkeypatch, [FEN_A])
    runner = sidecar.FenAnalysisRunner()
    try:
        first = runner.judge(FEN_A, "h7h5")
        err = _wait(events, lambda e, d: e == "move_judged" and d["token"] == first)
        assert killer.kills and "error" in err

        second = runner.judge(FEN_A, "h7h5")
        verdict = _wait(events, lambda e, d: e == "move_judged" and d["token"] == second)
        assert verdict is not None and "error" not in verdict   # the next judgement works
        assert verdict["san"] == "h5"
        assert "restarted" in err["error"]
    finally:
        runner.shutdown()


# ── Live play ─────────────────────────────────────────────────────────────────

def _live(stockfish):
    worker = sidecar.EngineWorker()
    worker.start(stockfish)
    assert worker.ready.wait(15) and worker.error is None
    return worker


def test_live_play_restarts_reconfigures_and_still_moves(stockfish, monkeypatch, events):
    killer = Killer(monkeypatch, [FEN_B])
    worker = _live(stockfish)
    moved: list[str] = []
    try:
        worker.request_move(FEN_B, 5, lambda m: moved.append(m.uci()))
        end = time.monotonic() + 15
        while not moved and time.monotonic() < end:
            time.sleep(0.05)
        assert killer.kills
        assert moved and chess.Move.from_uci(moved[0]) in chess.Board(FEN_B).legal_moves
        assert not [e for e, _ in events if e == "engine_error"]
        # The replacement engine plays at the requested level, not at full strength.
        elo = sidecar.skill_to_elo(5)
        assert (2, {"UCI_LimitStrength": True, "UCI_Elo": elo}) in killer.configured
    finally:
        worker.shutdown()


def test_live_play_reports_an_engine_that_will_not_stay_up(stockfish, monkeypatch, events):
    killer = Killer(monkeypatch, [FEN_B], times=2)
    worker = _live(stockfish)
    moved: list[str] = []
    try:
        worker.request_move(FEN_B, 5, lambda m: moved.append(m.uci()))
        err = _wait(events, lambda e, d: e == "engine_error", timeout=15)
        assert err is not None and "stopped unexpectedly" in err["message"]
        assert len(killer.kills) == 2
        assert not moved
    finally:
        worker.shutdown()


# ── W18: a non-death error after the move is an error, not a made-up score ────

def test_an_engine_error_on_the_after_search_ends_the_game(stockfish):
    """The after-move search used to answer a non-death engine error with
    `score_after = score_before` — a loss-free move on no evidence. The engine here is
    real; only the after-move search of one ply raises, the way a protocol error would."""
    from zugzwang.core.analysis import analyze_game_plies

    movetext = GAMES["9000001"]
    target = _fen_at(movetext, 5)                       # the position after ply 4's move
    engine = chess.engine.SimpleEngine.popen_uci(stockfish)
    real = engine.analyse

    def analyse(board, limit, **kwargs):
        if board.fen() == target and kwargs.get("multipv") == 1:
            raise chess.engine.EngineError("bad info line from the engine")
        return real(board, limit, **kwargs)
    engine.analyse = analyse
    try:
        events = list(analyze_game_plies(
            engine, f'[Event "t"]\n\n{movetext}', DEPTH))
    finally:
        engine.quit()

    kinds = [e[0] for e in events]
    assert "done" not in kinds
    assert kinds[-1] == "error" and "after ply 4" in events[-1][1]
    # Ply 4 is never emitted; nor is ply 3, since J1 (classifier version 4) labels two plies
    # behind and ply 3's label waits for ply 5's row.
    assert [e[1] for e in events if e[0] == "ply"] == [0, 1, 2]


# ── VAL-DEATH-2: a deterministic crash stops being queued ─────────────────────

def test_a_game_that_crashes_every_sync_is_marked_and_no_longer_queued(
        stockfish, monkeypatch, events, tmp_path):
    ids = ["9000001", "9000002"]
    runner, db_path, gids = _sync(tmp_path, ids)
    killer = Killer(monkeypatch, [_fen_at(GAMES["9000002"], 3)], times=None)

    for _ in range(3):
        runner._run_analyze(["chesscom"], db_path, DEPTH)

    # Two runs crash on it (two deaths each); the third does not try it.
    assert len(killer.kills) == 4
    db = Database(db_path)
    ((ok_run, stored, _),) = _runs(db, gids["9000001"])
    assert stored == 10 and _runs(db, gids["9000002"]) == []
    assert len(_failures(db)) == 2
    version = _failures(db)[0][4]
    assert db.needs_attention_ids("chesscom", version) == {gids["9000002"]}
    assert db.needs_attention_ids("chesscom", "Stockfish 19") == set()   # a new binary retries
    warned = [d["message"] for e, d in events if e == "sync_warning"]
    assert warned[-1].startswith("Not analysing 1 game(s)")

    # The status line counts it apart from the work the bulk action would queue.
    server = object.__new__(sidecar.Server)
    server._db = db
    server._sync = type("S", (), {"running": lambda self: False, "run_id": 0})()
    server._engine = type("E", (), {"_engine": type("X", (), {"id": {"name": version}})()})()
    c = server.rpc_sync_status(depth=DEPTH)["chesscom"]
    assert (c["needsAttention"], c["unanalysed"], c["pending"]) == (1, 0, 0)
