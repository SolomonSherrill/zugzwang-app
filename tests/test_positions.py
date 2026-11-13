"""VAL-FEN: an illegal position never reaches an engine (FIXPLAN, 2026-10-22).

`chess.Board(fen)` accepts well-formed illegal positions. Against the bundled
Stockfish a position with no kings segfaults the engine, and the other shapes below
are analysed silently into confident nonsense (`review/scratch/val_illegal_engine.out`).
"""

import importlib.util
from pathlib import Path

import chess
import pytest

from zugzwang.core.analysis import analyze_game_plies
from zugzwang.core.game import GameSession
from zugzwang.core.positions import IllegalPosition, legal_board

ILLEGAL = [
    ("8/8/8/8/8/8/8/8 w - - 0 1", "no king"),
    ("4k3/8/8/8/8/8/8/K3K3 w - - 0 1", "more than one king"),
    ("4k3/8/8/8/8/8/8/P3K3 w - - 0 1", "first or last rank"),
    ("4k3/4Q3/8/8/8/8/8/4K3 w - - 0 1", "side not to move is in check"),
]
LEGAL = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"

_REPO = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("sidecar_main_val", _REPO / "sidecar" / "main.py")
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)


@pytest.mark.parametrize("fen, reason", ILLEGAL)
def test_an_illegal_position_is_refused_with_its_reason(fen, reason):
    assert chess.Board(fen) is not None          # python-chess alone accepts it
    with pytest.raises(IllegalPosition, match=reason):
        legal_board(fen)


def test_a_legal_position_passes_and_a_malformed_fen_still_fails_as_before():
    assert legal_board(LEGAL).fen() == LEGAL
    with pytest.raises(ValueError):
        legal_board("not a fen")


class _NoEngine:
    def __getattr__(self, name):
        raise AssertionError("an illegal position reached the engine")


@pytest.mark.parametrize("fen, move", [
    (ILLEGAL[1][0], "Kb1"), (ILLEGAL[2][0], "Kd1"), (ILLEGAL[3][0], "Kd1"),
])
def test_a_pgn_with_an_illegal_start_never_reaches_the_engine(fen, move):
    """A move python-chess will replay from that start, so the game has plies and the
    analysis would otherwise search them."""
    pgn = f'[Event "t"]\n[SetUp "1"]\n[FEN "{fen}"]\n[Result "*"]\n\n1. {move} *'
    events = list(analyze_game_plies(_NoEngine(), pgn, 10))
    assert events[0][0] == "error" and "Illegal position" in events[0][1]


def test_a_kingless_pgn_has_no_moves_to_search():
    """No kings, no legal moves at all: python-chess replays nothing, and the
    analysis ends before any search — the engine is never asked."""
    pgn = f'[Event "t"]\n[SetUp "1"]\n[FEN "{ILLEGAL[0][0]}"]\n[Result "*"]\n\n*'
    assert list(analyze_game_plies(_NoEngine(), pgn, 10)) == [("done", {}, [])]


@pytest.mark.parametrize("fen, reason", ILLEGAL)
def test_play_from_an_illegal_fen_is_refused(fen, reason):
    with pytest.raises(IllegalPosition):
        GameSession(chess.WHITE, 5, starting_fen=fen)


@pytest.mark.parametrize("method, params", [
    ("analyze_fen", {"fen": ILLEGAL[0][0]}),
    ("judge_move", {"fen": ILLEGAL[1][0], "uci": "a1b1"}),
    ("probe_move", {"fen": ILLEGAL[3][0], "uci": "e1d1"}),
])
def test_the_rpc_boundary_replies_with_the_reason(method, params, monkeypatch):
    """A bare server with no engine runners: the request must be refused before it
    gets anywhere near one, and the caller told why."""
    sent = []
    monkeypatch.setattr(sidecar, "_send", sent.append)
    server = object.__new__(sidecar.Server)
    server._handle_request({"id": 7, "method": method, "params": params})
    assert sent[0]["id"] == 7
    assert "Illegal position" in sent[0]["error"]["message"]
