"""COACH-1 D: draw offers against Stockfish (COACH.md ruling 8; DESIGN.md "Owner rulings, 2026-11-23")."""
import types

import chess
import pytest

import sidecar.main as sidecar
from sidecar.main import draw_decision
from zugzwang.config import DRAW_FAVOUR_CP, DRAW_FROM_MOVE
from zugzwang.core.database import Database


@pytest.fixture
def server(monkeypatch):
    """A Server with no threads or boot; its frames go nowhere."""
    monkeypatch.setattr(sidecar, "_send", lambda obj: None)
    return object.__new__(sidecar.Server)

LOCKED = "4k3/8/8/p1p1p1p1/P1P1P1P1/8/8/4K3 w - - 0 40"


def test_before_move_30_the_offer_waits_whatever_the_evaluation():
    assert DRAW_FROM_MOVE == 30
    for move in (1, 15, 29):
        assert draw_decision(move, ("x", -500, None)) == "Draw offers open after move 30."


def test_from_move_30_accepted_when_the_engine_does_not_favour_it():
    assert draw_decision(30, ("x", 0, None)) is None
    assert draw_decision(31, ("x", DRAW_FAVOUR_CP, None)) is None
    assert draw_decision(45, ("x", -300, None)) is None
    assert draw_decision(45, ("x", None, -4)) is None          # the engine is being mated


def test_from_move_30_declined_when_the_engine_favours_it():
    assert draw_decision(30, ("x", DRAW_FAVOUR_CP + 1, None)) == "Stockfish declined the draw."
    assert draw_decision(60, ("x", None, 7)) == "Stockfish declined the draw."
    assert draw_decision(60, None) == "Stockfish declined the draw."   # no evaluation of its own
    assert draw_decision(60, ("x", 300, None), opponent="The coach") == "The coach declined the draw."


@pytest.mark.parametrize("cp,mate", [(500, None), (None, 3), (-500, None), (0, None)])
def test_no_message_states_or_implies_an_evaluation(cp, mate):
    for move in (5, 40):
        msg = draw_decision(move, ("x", cp, mate))
        if msg is None:
            continue
        assert msg in ("Draw offers open after move 30.", "Stockfish declined the draw.")
        low = msg.lower()
        for word in ("better", "worse", "winning", "losing", "advantage", "equal", "eval", "pawn", "level"):
            assert word not in low


def _play(server, tmp_path, last_eval, fen=LOCKED, colour="black"):
    server._engine = types.SimpleNamespace(cancel=lambda: None, request_move=lambda *a: None,
                                           last_eval=None)
    server._openings = None
    server._db = Database(tmp_path / "draw.db")
    server.rpc_new_game(color=colour, skill=3, fen=fen)
    b = chess.Board(fen)
    server._engine.last_eval = (b.fen(), *last_eval) if last_eval else None
    mv = next(iter(b.legal_moves))
    server._apply_engine_move(mv)
    return server


def test_rpc_draw_agreed_in_a_level_position_after_move_30(server, tmp_path):
    _play(server, tmp_path, (0, None))
    res = server.rpc_draw()
    assert res["end"]["termination"] == "draw_agreed" and res["end"]["result"] == "1/2-1/2"


def test_rpc_draw_declined_when_stockfish_favours_it_and_the_game_goes_on(server, tmp_path):
    _play(server, tmp_path, (250, None))
    res = server.rpc_draw()
    assert res == {"end": None, "declined": "Stockfish declined the draw."}
    assert server._session is not None and not server._session.over


def test_rpc_draw_before_move_30(server, tmp_path):
    server._engine = types.SimpleNamespace(cancel=lambda: None, request_move=lambda *a: None, last_eval=None)
    server._openings = None
    server._db = Database(tmp_path / "draw.db")
    server.rpc_new_game(color="white", skill=3)
    res = server.rpc_draw()
    assert res == {"end": None, "declined": "Draw offers open after move 30."}


def test_rpc_draw_ignores_an_evaluation_from_another_game(server, tmp_path):
    _play(server, tmp_path, (0, None))
    server._engine.last_eval = ("8/8/8/8/8/8/8/K6k w - - 0 1", 0, None)   # not this game's position
    assert server.rpc_draw()["declined"] == "Stockfish declined the draw."


def test_resign_stays(server, tmp_path):
    _play(server, tmp_path, (900, None))
    end = server.rpc_resign()["end"]
    assert end["termination"] == "resignation"
