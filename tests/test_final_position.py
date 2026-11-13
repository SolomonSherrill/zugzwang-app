"""STORE-FINALPLY (owner ruling 2026-10-23): analysis also searches each game's final
position, so the last move has a stored refutation like every other — ply N+1's lines
for move N, the final position's for the last move (ARCH-0.1-N1: 265 errors were final
plies, 126 of them resignations and 83 timeouts). Needs the bundled Stockfish."""

import chess

from tests.test_engine_death import (  # noqa: F401  (fixtures)
    DEPTH, GAMES, Killer, _fen_at, _reanalyse, _runs, _save_games, _sync, events,
    reanalyse_server, sidecar, stockfish,
)
from zugzwang.core.analysis import analyze_game_plies, lines_after
from zugzwang.core.database import Database

MATED = "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0"


def _final_board(movetext):
    board = chess.Board()
    for san in [t for t in movetext.split() if not t[0].isdigit()]:
        board.push_san(san)
    return board


def test_reanalyse_stores_the_final_positions_lines(stockfish, events, reanalyse_server):
    server, inbox, db = reanalyse_server
    ext = "9000001"                                       # ends after 5...Be7, resigned
    gid = _save_games(db, [ext])[ext]
    _reanalyse(server, inbox, events, gid)

    run = db.load_latest_run(gid)
    plies = db.load_move_analyses(run.id)
    final = run.final_lines
    board = _final_board(GAMES[ext])
    assert len(final) == 3
    assert all(chess.Move.from_uci(line["uci"][0]) in board.legal_moves for line in final)
    assert lines_after(plies, final, len(plies) - 1) == final          # the last move
    assert lines_after(plies, final, 3) == plies[4].lines             # any other move


def test_a_mated_position_has_nothing_to_search(stockfish):
    engine = chess.engine.SimpleEngine.popen_uci(stockfish)
    try:
        events = list(analyze_game_plies(engine, f'[Event "t"]\n\n{MATED}', DEPTH))
    finally:
        engine.quit()
    assert events[-1][0] == "done" and events[-1][2] == []


def test_sync_stores_the_final_positions_lines(stockfish, events, tmp_path):
    runner, db_path, gids = _sync(tmp_path, ["9000002"])
    runner._run_analyze(["chesscom"], db_path, DEPTH)
    db = Database(db_path)
    final = db.load_latest_run(gids["9000002"]).final_lines
    board = _final_board(GAMES["9000002"])
    assert len(final) == 3 and chess.Move.from_uci(final[0]["uci"][0]) in board.legal_moves


def test_an_engine_death_on_the_final_position_is_a_death(stockfish, monkeypatch, events,
                                                          tmp_path):
    """Searched like any position, so killed like any: twice is poison and the game is
    not saved, rather than saved without its final lines."""
    runner, db_path, gids = _sync(tmp_path, ["9000003"])
    final_fen = _final_board(GAMES["9000003"]).fen()
    killer = Killer(monkeypatch, [final_fen], times=None)
    # The last ply's after-move search reaches the same position at a shallower depth;
    # only the final search (MultiPV 3) is the one under test, so spare the other.
    real = killer._wrap

    def wrap(engine, method):
        killing = real(engine, method)

        def wrapped(board, limit, *a, **k):
            if k.get("multipv") == 1:
                return method(board, limit, *a, **k)
            return killing(board, limit, *a, **k)
        return wrapped
    killer._wrap = wrap

    runner._run_analyze(["chesscom"], db_path, DEPTH)

    db = Database(db_path)
    assert len(killer.kills) == 2
    assert _runs(db, gids["9000003"]) == []
    (ply,) = [r[0] for r in db._conn.execute("SELECT ply FROM engine_failures")]
    assert ply == 10                                     # the final position: ply = total


def test_stored_lines_keep_the_engines_whole_pv_up_to_the_cap(stockfish):
    """STORE-PVCAP: lines are stored up to ANALYSIS_PV_STORE_LEN, not cut at 6."""
    import zugzwang.config as C
    engine = chess.engine.SimpleEngine.popen_uci(stockfish)
    try:
        events = list(analyze_game_plies(engine, f'[Event "t"]\n\n{GAMES["9000003"]}', 14))
    finally:
        engine.quit()
    plies = [e[3] for e in events if e[0] == "ply"]
    lengths = [len(line["uci"]) for p in plies for line in p.lines]
    assert max(lengths) > 6 and max(lengths) <= C.ANALYSIS_PV_STORE_LEN
    assert all(len(line["san"]) == len(line["uci"]) for p in plies for line in p.lines)
    assert max(len(p.pv_uci.split()) for p in plies) > 6
