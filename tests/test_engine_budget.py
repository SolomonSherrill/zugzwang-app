"""ENG-ALLOC: one thread per engine, bulk analysis on several single-threaded engines,
and a budget sized to the performance cores with live play and the FEN path reserved
while their screens are open (owner ruling 2026-10-22, FIXPLAN ENG-ALLOC).

The budget tests need no engine. The sync and reproducibility tests use the bundled
Stockfish at a shallow depth and are skipped without it.
"""

import importlib.util
import io
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import pytest

import zugzwang.config as C
from zugzwang.core.analysis import analyze_game_plies, configure_engine_for_analysis
from zugzwang.core.database import Database
from zugzwang.core.engine_locator import find_stockfish

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "zugzwang_sidecar_main_budget", _REPO / "sidecar" / "main.py"
)
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)

GAMES = [
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 1-0",
    "1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O 6. Nf3 h6 7. Bh4 b6 0-1",
    "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Be3 e5 7. Nb3 Be6 1/2-1/2",
]


# ── the budget ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _standard_depth_8(monkeypatch):
    """RUNS-DEPTH: only a run at the standard depth satisfies a sync. These tests search at
    depth 8 for speed, so the standard depth is 8 here (production: 14)."""
    import zugzwang.config as _cfg
    monkeypatch.setattr(_cfg, "ANALYSIS_STANDARD_DEPTH", 8)


@pytest.mark.parametrize("screen, slots", [
    (None, 8), ("home", 8), ("games", 8), ("settings", 8),
    ("play", 3), ("review", 3), ("puzzles", 3),
])
def test_bulk_gets_what_the_screen_on_view_leaves(screen, slots):
    """ENGINE-BUDGET-M4B (owner, 2026-11-07): 8 with no interactive screen open; the
    with-screen reserve is unchanged, out of the 4 performance cores."""
    budget = sidecar.EngineBudget(cores=4, idle_ceiling=8)
    budget.set_screen(screen)
    assert budget.bulk_slots() == slots


def test_a_reanalysis_takes_a_slot_while_it_runs():
    budget = sidecar.EngineBudget(cores=4, idle_ceiling=8)
    budget.set_screen("review")
    budget.reanalysis(True)
    assert budget.bulk_slots() == 2      # the proposal's "two while the user reviews"
    budget.reanalysis(False)
    assert budget.bulk_slots() == 3


def test_a_reanalysis_off_screen_takes_a_slot_from_the_idle_ceiling():
    budget = sidecar.EngineBudget(cores=4, idle_ceiling=8)
    budget.set_screen("games")
    budget.reanalysis(True)
    assert budget.bulk_slots() == 7


def test_opening_play_drops_bulk_from_the_ceiling_to_the_reserve():
    budget = sidecar.EngineBudget(cores=4, idle_ceiling=8)
    assert budget.bulk_slots() == 8
    budget.set_screen("play")
    assert budget.bulk_slots() == 3
    budget.set_screen("games")
    assert budget.bulk_slots() == 8


def test_the_ceiling_is_never_below_the_cores():
    budget = sidecar.EngineBudget(cores=4, idle_ceiling=2)
    assert budget.ceiling == 4 and budget.bulk_slots() == 4


def test_the_shipped_ceiling():
    assert C.ENGINE_BUDGET_IDLE_CEILING >= C.ENGINE_BUDGET_CORES
    assert C.ENGINE_BUDGET_IDLE_CEILING <= 8


def test_bulk_always_keeps_one_engine():
    budget = sidecar.EngineBudget(cores=2, idle_ceiling=2)
    budget.set_screen("review")
    budget.reanalysis(True)
    budget.reanalysis(True)
    assert budget.bulk_slots() == 1


def test_one_thread_per_analysis_engine():
    """At fixed depth extra threads were slower (57.0 s on 1 against 168.9 s on 9)
    and made the search irreproducible (0/20 identical scores at 9 threads)."""
    assert C.ANALYSIS_THREADS == 1
    assert C.ENGINE_BUDGET_CORES >= 2


def test_set_active_screen_reaches_the_budget():
    server = object.__new__(sidecar.Server)
    server._budget = sidecar.EngineBudget(cores=4, idle_ceiling=8)
    out = server.rpc_set_active_screen("play")
    assert out == {"screen": "play", "bulkSlots": 3, "cores": 4, "ceiling": 8}


# ── with an engine ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def stockfish():
    path = find_stockfish()
    if path is None:
        pytest.skip("Stockfish not found")
    return str(path)


def _fresh(path):
    engine = chess.engine.SimpleEngine.popen_uci(path)
    configure_engine_for_analysis(engine)
    return engine


def _scores(engine, movetext, depth=8):
    pgn = f'[Event "t"]\n[Result "*"]\n\n{movetext}'
    return [
        (ev[3].score_before_cp, ev[3].score_before_mate, ev[3].best_uci,
         ev[3].score_after_cp, ev[3].classification)
        for ev in analyze_game_plies(engine, pgn, depth) if ev[0] == "ply"
    ]


def test_a_game_analyses_the_same_whatever_the_engine_searched_before(stockfish):
    """`ucinewgame` at each game's start clears the hash, so a game's analysis is a
    function of the game alone — the property parallel workers need, since which
    worker runs which game, after what, is scheduling."""
    alone = _fresh(stockfish)
    after_another = _fresh(stockfish)
    try:
        _scores(after_another, GAMES[0])
        assert _scores(after_another, GAMES[1]) == _scores(alone, GAMES[1])
    finally:
        alone.quit()
        after_another.quit()


def _db_with_games(tmp_path) -> Database:
    db = Database(tmp_path / "z.db")
    for i, movetext in enumerate(GAMES):
        game = chess.pgn.read_game(io.StringIO(movetext))
        board = game.end().board()
        db.save_game(
            played_at=f"2026-01-0{i + 1}T00:00:00+00:00", player_color="white",
            skill_level=0, result="*", termination="", move_count=board.ply(),
            pgn=f'[Event "t{i}"]\n[Result "*"]\n\n{movetext}',
            final_fen=board.fen(), source="lichess", external_id=f"g{i}",
        )
    return db


def test_parallel_sync_saves_every_game_whole(stockfish, tmp_path, monkeypatch):
    monkeypatch.setattr(sidecar, "_emit", lambda *a, **k: None)
    db = _db_with_games(tmp_path)
    runner = sidecar.SyncRunner(lambda fn: fn(), sidecar.EngineBudget(cores=2, idle_ceiling=2))
    try:
        assert runner._analyze_pending(db, None, "lichess", 8) == 3
    finally:
        runner._quit_engine()
    assert db.games_pending_analysis("lichess", 8) == []
    for rec_id in (1, 2, 3):
        run = db.load_latest_run(rec_id)
        assert run is not None and run.depth == 8
        assert len(db.load_move_analyses(run.id)) == 14


def test_a_sync_finishes_when_the_budget_holds_a_worker_back(stockfish, tmp_path, monkeypatch):
    """Two workers, one slot (Review is open). The held-back worker must still exit
    once the queue drains. It used to check the queue only after passing the gate,
    so it waited for a slot forever and the sync never returned — found when the
    ENG-ALLOC timing run hung on Review. Run in a thread so a regression fails here
    instead of hanging the suite."""
    import threading
    monkeypatch.setattr(sidecar, "_emit", lambda *a, **k: None)
    db_path = tmp_path / "z.db"
    _db_with_games(tmp_path).close()
    budget = sidecar.EngineBudget(cores=2, idle_ceiling=2)
    budget.set_screen("review")
    assert budget.bulk_slots() == 1
    runner = sidecar.SyncRunner(lambda fn: fn(), budget)
    result = {}

    def go():
        db = Database(db_path)
        try:
            result["n"] = runner._analyze_pending(db, None, "lichess", 8)
            result["left"] = len(db.games_pending_analysis("lichess", 8))
        finally:
            db.close()
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout=60)
    runner._quit_engine()
    assert not t.is_alive(), "sync did not finish: a held-back worker never exited"
    assert result == {"n": 3, "left": 0}


def test_a_cancelled_sync_saves_no_partial_run(stockfish, tmp_path, monkeypatch):
    """Cancelled *mid-game*, after plies have been computed. A half-written run
    counts as done in `games_pending_analysis`, so before this change a cancel there
    left that game permanently unanalysed; now the game is saved whole or not at all,
    and it is still pending afterwards."""
    monkeypatch.setattr(sidecar, "_emit", lambda *a, **k: None)
    db = _db_with_games(tmp_path)
    runner = sidecar.SyncRunner(lambda fn: fn(), sidecar.EngineBudget(cores=1, idle_ceiling=1))
    real = sidecar.analyze_game_plies

    def cancel_after_three_plies(*args, **kwargs):
        for n, event in enumerate(real(*args, **kwargs)):
            if n == 3:
                runner.cancel()
            yield event
    monkeypatch.setattr(sidecar, "analyze_game_plies", cancel_after_three_plies)
    try:
        runner._analyze_pending(db, None, "lichess", 8)
    finally:
        runner._quit_engine()
    for rec_id in (1, 2, 3):
        assert db.load_latest_run(rec_id) is None
    assert len(db.games_pending_analysis("lichess", 8)) == 3
